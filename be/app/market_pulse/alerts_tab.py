"""
alerts_tab.py
-------------
Strategy alert monitors — poll ticker × timeframe × strategy (from Multi-Combo)
and notify via Telegram / email when a live trade setup is detected.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

import pandas as pd
from backtesting.data_fetcher import get_historical_data
from app.market_pulse.alert_notifier import (
    email_configured,
    send_trade_setup_alert,
    telegram_configured,
)
from app.market_pulse.database import (
    delete_alert_monitor_by_id,
    get_alert_monitors_by_mobile,
    get_combo_outcomes_by_mobile,
    get_multi_combo_scans_by_mobile,
    save_alert_monitor,
    set_alert_monitor_enabled,
    update_alert_monitor_state,
    get_custom_strategies_by_mobile,
)
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.presets import get_presets_for_market
from app.market_pulse.ticker_utils import (
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
    market_currency,
)
from app.market_pulse.multi_combo_saves import (
    combo_outcome_label,
    resolve_strategy_config,
    strategy_config_from_row,
)
from app.market_pulse.signal_eval import evaluate_trade_setup


POLL_OPTIONS = {
    "Every 1 minute": 1,
    "Every 5 minutes": 5,
    "Every 15 minutes": 15,
    "Every 30 minutes": 30,
    "Every 1 hour": 60,
}


def get_logged_in_mobile() -> str:
    return (st.session_state.get("logged_in_mobile") or "").strip()


def _parse_db_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(str(ts)[:26], fmt)
        except ValueError:
            continue
    return None


def _combo_label(row: dict) -> str:
    return f"{row.get('Ticker', '?')} | {row.get('Timeframe', '?')} | {row.get('Strategy', '?')[:50]}"


def _scan_rows_for_market(mobile: str, market: str) -> list[dict]:
    rows: list[dict] = []
    session_rows = st.session_state.get("scan_results") or []
    if session_rows and st.session_state.get("scanner_market", market) == market:
        rows.extend(session_rows)

    for scan in get_multi_combo_scans_by_mobile(mobile):
        if scan.get("market") != market:
            continue
        try:
            for r in json.loads(scan["scan_results"]):
                r["_source_scan"] = scan["name"]
                rows.append(r)
        except (json.JSONDecodeError, TypeError):
            continue
    return rows


def _monitor_due(monitor: dict, force: bool = False) -> bool:
    if force:
        return True
    last = _parse_db_ts(monitor.get("last_checked_at"))
    if last is None:
        return True
    return datetime.now() - last >= timedelta(minutes=int(monitor.get("poll_minutes") or 15))


def run_alert_check(monitor: dict, mobile: str, *, force: bool = False) -> dict:
    """Poll one monitor; send alert on new BUY setup."""
    result = {
        "monitor_id": monitor["id"],
        "name": monitor["name"],
        "ticker": monitor["ticker"],
        "ok": False,
        "signal": "NONE",
        "alert_sent": False,
        "message": "",
    }

    if not _monitor_due(monitor, force=force):
        result["message"] = "Skipped (not due yet)"
        return result

    try:
        indicators = json.loads(monitor["indicators"])
        entry_rules = json.loads(monitor["entry_rules"])
        exit_rules = json.loads(monitor["exit_rules"])
    except (json.JSONDecodeError, TypeError):
        result["message"] = "Invalid strategy JSON in monitor"
        return result

    groww_token = get_active_groww_token()
    exchange = st.session_state.get("mega_exchange", "NSE")

    try:
        df = get_historical_data(
            symbol=monitor["ticker"],
            start_date=str(date.today() - timedelta(days=60)),
            end_date=str(date.today()),
            market=monitor["market"],
            timeframe=monitor["timeframe"],
            groww_token=groww_token,
            groww_exchange=exchange,
        )
    except Exception as exc:
        result["message"] = f"Data error: {exc}"
        update_alert_monitor_state(monitor["id"], mobile, monitor.get("last_signal") or "INACTIVE")
        return result

    eval_res = evaluate_trade_setup(
        df,
        indicators,
        entry_rules,
        exit_rules,
        entry_mode=monitor.get("entry_mode") or "AND",
    )
    result["ok"] = True
    result["signal"] = eval_res["signal"]

    prev = (monitor.get("last_signal") or "INACTIVE").upper()
    entry_active = eval_res["entry_active"]
    new_state = "ACTIVE" if entry_active else "INACTIVE"

    alert_needed = entry_active and prev != "ACTIVE"
    if alert_needed:
        send_res = send_trade_setup_alert(
            ticker=monitor["ticker"],
            timeframe=monitor["timeframe"],
            strategy=monitor["strategy_name"],
            market=monitor["market"],
            signal=eval_res["signal"],
            close=eval_res["close"],
            bar_time=eval_res["bar_time"],
            monitor_name=monitor["name"],
            via_telegram=bool(monitor.get("notify_telegram")),
            via_email=bool(monitor.get("notify_email")),
        )
        result["alert_sent"] = True
        result["send_results"] = send_res
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_alert_monitor_state(monitor["id"], mobile, new_state, last_alert_at=now)
        result["message"] = f"Alert sent · {eval_res['signal']} @ {eval_res.get('close')}"
    else:
        update_alert_monitor_state(monitor["id"], mobile, new_state)
        if entry_active:
            result["message"] = "Setup still active (no repeat alert)"
        else:
            result["message"] = "No setup"

    return result


def _render_config_status():
    st.markdown("#### 📡 Notification channels (.env)")
    c1, c2, c3 = st.columns(3)
    with c1:
        if telegram_configured():
            st.success("Telegram configured")
        else:
            st.warning("Telegram: set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`")
    with c2:
        if email_configured():
            st.success("Email configured")
        else:
            st.warning("Email: set `SMTP_*` and `ALERT_EMAIL_TO`")
    with c3:
        st.caption(
            "Optional: `ALERTS_ENABLED=true` · "
            "See project `.env` for all keys."
        )


def _render_create_monitors(mobile: str):
    st.markdown("### ➕ Create alert monitors")

    market = st.selectbox(
        "Market",
        MARKET_OPTIONS,
        key="alerts_market",
    )

    source = st.radio(
        "Pick strategies from",
        [
            "Saved scan outcomes (from 💾 Save)",
            "Current Multi-Combo results",
            "Saved Multi-Combo scan",
            "Manual strategy",
        ],
        horizontal=True,
        key="alerts_source",
    )

    selected_rows: list[dict] = []

    if source == "Saved scan outcomes (from 💾 Save)":
        saved = get_combo_outcomes_by_mobile(mobile, market)
        if not saved:
            st.info(
                "No saved outcomes yet. In **Multi-Combo Scanner**, click **💾 Save** on any "
                "result row to add it here."
            )
        else:
            labels = [combo_outcome_label(s) for s in saved]
            picked = st.multiselect(
                "Choose saved ticker × timeframe × strategy outcomes",
                labels,
                key="alerts_pick_saved_outcomes",
            )
            for s, lb in zip(saved, labels):
                if lb in picked:
                    selected_rows.append({
                        "Ticker": s["ticker"],
                        "Timeframe": s["timeframe"],
                        "Strategy": s["strategy_name"],
                        "indicators": s["indicators"],
                        "entry_rules": s["entry_rules"],
                        "exit_rules": s["exit_rules"],
                        "Status": "✅ OK",
                        "_saved_id": s["id"],
                    })

    elif source == "Current Multi-Combo results":
        rows = [
            r for r in (st.session_state.get("scan_results") or [])
            if r.get("Status") == "✅ OK"
            and st.session_state.get("scanner_market", market) == market
        ]
        if not rows:
            st.info("Run **Multi-Combo Scanner** first (Strategy Lab) or load a saved scan.")
        else:
            labels = [_combo_label(r) for r in rows]
            picked = st.multiselect(
                "Select ticker × timeframe × strategy combos",
                labels,
                key="alerts_pick_session",
            )
            selected_rows = [r for r, lb in zip(rows, labels) if lb in picked]

    elif source == "Saved Multi-Combo scan":
        scans = [s for s in get_multi_combo_scans_by_mobile(mobile) if s["market"] == market]
        if not scans:
            st.info("No saved scans for this market. Save a run from Multi-Combo Scanner.")
        else:
            scan_name = st.selectbox(
                "Saved scan",
                [s["name"] for s in scans],
                key="alerts_saved_scan",
            )
            scan = next(s for s in scans if s["name"] == scan_name)
            try:
                rows = [r for r in json.loads(scan["scan_results"]) if r.get("Status") == "✅ OK"]
            except (json.JSONDecodeError, TypeError):
                rows = []
            labels = [_combo_label(r) for r in rows]
            picked = st.multiselect("Combos to monitor", labels, key="alerts_pick_saved")
            selected_rows = [r for r, lb in zip(rows, labels) if lb in picked]

    else:
        combined = dict(get_presets_for_market(market))
        custom = {}
        target = "CoinDCX" if is_crypto_market(market) else "Groww"
        for s in get_custom_strategies_by_mobile(mobile):
            if s["market"] in (target, "Both"):
                custom[f"🤖 [CUSTOM] {s['name']}"] = s
        strat_names = list({**custom, **combined}.keys())
        strat = st.selectbox("Strategy", strat_names, key="alerts_manual_strat")
        default_ticker = (
            "RELIANCE" if is_india_market(market)
            else "BTC-USDT" if is_crypto_market(market)
            else "AAPL"
        )
        ticker = st.text_input("Ticker", value=default_ticker, key="alerts_manual_ticker")
        tf = st.selectbox("Timeframe", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=4, key="alerts_manual_tf")
        if strat and ticker:
            selected_rows = [{
                "Ticker": ticker.strip().upper(),
                "Timeframe": tf,
                "Strategy": strat,
                "Status": "✅ OK",
            }]

    st.markdown("#### ⚙️ Monitor settings")
    poll_label = st.selectbox(
        "Poll frequency",
        list(POLL_OPTIONS.keys()),
        index=2,
        key="alerts_poll",
    )
    poll_minutes = POLL_OPTIONS[poll_label]

    n1, n2 = st.columns(2)
    with n1:
        notify_tg = st.checkbox("Telegram alerts", value=telegram_configured(), key="alerts_notify_tg")
    with n2:
        notify_em = st.checkbox("Email alerts", value=False, key="alerts_notify_em")

    if st.button("Create monitor(s)", type="primary", key="alerts_create_btn"):
        if not selected_rows:
            st.error("Select at least one combo.")
            return

        created = 0
        skipped = []
        for row in selected_rows:
            strat_name = row["Strategy"]
            cfg = strategy_config_from_row(row, mobile, market)
            if not cfg:
                skipped.append(strat_name)
                continue

            safe_ticker = str(row["Ticker"]).replace(" ", "_")[:12]
            safe_tf = str(row["Timeframe"]).replace(" ", "")
            safe_strat = "".join(c if c.isalnum() else "_" for c in strat_name)[:24]
            mon_name = f"{safe_ticker}_{safe_tf}_{safe_strat}_{int(time.time()) % 100000}"

            ok = save_alert_monitor(
                mobile_number=mobile,
                name=mon_name,
                market=market,
                ticker=row["Ticker"],
                timeframe=row["Timeframe"],
                strategy_name=strat_name,
                indicators=cfg["indicators"],
                entry_rules=cfg["entry_rules"],
                exit_rules=cfg.get("exit_rules", []),
                poll_minutes=poll_minutes,
                notify_telegram=notify_tg,
                notify_email=notify_em,
            )
            if ok:
                created += 1

        if created:
            st.success(f"Created {created} alert monitor(s).")
            st.toast(f"{created} monitor(s) active", icon="🔔")
        if skipped:
            st.warning(f"Could not resolve strategy config for: {', '.join(skipped[:5])}")


def _render_monitors_and_poll(mobile: str):
    st.markdown("### 🔔 Active monitors")

    monitors = get_alert_monitors_by_mobile(mobile)
    if not monitors:
        st.info(
            "No alert monitors yet. Save combos in Multi-Combo (**💾 Save**), then create monitors here."
        )
        return

    force_poll = False
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        auto_poll = st.checkbox(
            "Auto-poll while Alerts tab is open",
            value=st.session_state.get("alerts_auto_poll", True),
            key="alerts_auto_poll_cb",
        )
        st.session_state["alerts_auto_poll"] = auto_poll
    with c2:
        if st.button("🔄 Run poll now", key="alerts_poll_now", width='stretch'):
            force_poll = True
    with c3:
        last_poll = st.session_state.get("alerts_last_poll_display", "—")
        st.caption(f"Last poll: {last_poll}")

    enabled = [m for m in monitors if m.get("enabled")]
    min_interval = min((int(m.get("poll_minutes") or 15) for m in enabled), default=15)
    last_ts = st.session_state.get("alerts_last_poll_ts", 0.0)
    due = force_poll or (
        auto_poll and enabled and (time.time() - last_ts >= min_interval * 60)
    )

    poll_log: list[dict] = []
    if due and enabled:
        with st.spinner(f"Polling {len(enabled)} monitor(s)…"):
            for mon in enabled:
                poll_log.append(run_alert_check(mon, mobile, force=force_poll))
        st.session_state["alerts_last_poll_ts"] = time.time()
        st.session_state["alerts_last_poll_display"] = datetime.now().strftime("%H:%M:%S")
        alerts_fired = [p for p in poll_log if p.get("alert_sent")]
        if alerts_fired:
            st.success(f"🔔 {len(alerts_fired)} new setup alert(s) sent!")
            for p in alerts_fired:
                st.toast(p.get("message", "Alert sent"), icon="🔔")
        elif force_poll:
            st.info("Poll complete — no new setups.")

    if poll_log:
        with st.expander("Latest poll details", expanded=bool(any(p.get("alert_sent") for p in poll_log))):
            st.dataframe(pd.DataFrame(poll_log), width='stretch', hide_index=True)

    table = []
    for m in monitors:
        table.append({
            "ID": m["id"],
            "Name": m["name"][:28],
            "Ticker": m["ticker"],
            "TF": m["timeframe"],
            "Strategy": (m["strategy_name"] or "")[:30],
            "Poll": f"{m['poll_minutes']}m",
            "TG": "✓" if m.get("notify_telegram") else "—",
            "Email": "✓" if m.get("notify_email") else "—",
            "Signal": m.get("last_signal") or "—",
            "Last check": (m.get("last_checked_at") or "—")[:16],
            "On": "✅" if m.get("enabled") else "⏸",
        })
    st.dataframe(pd.DataFrame(table), width='stretch', hide_index=True)

    for m in monitors:
        with st.container(border=True):
            st.markdown(
                f"**#{m['id']} {m['ticker']}** · `{m['timeframe']}` · {m['strategy_name'][:40]}"
            )
            st.caption(
                f"Poll every {m['poll_minutes']}m · "
                f"Last signal: **{m.get('last_signal') or '—'}** · "
                f"Market: {m['market']}"
            )
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("Poll now", key=f"alerts_one_{m['id']}"):
                    res = run_alert_check(m, mobile, force=True)
                    if res.get("alert_sent"):
                        st.success(res["message"])
                    else:
                        st.caption(res.get("message", "Done"))
            with b2:
                toggle_label = "Pause" if m.get("enabled") else "Resume"
                if st.button(toggle_label, key=f"alerts_toggle_{m['id']}"):
                    set_alert_monitor_enabled(m["id"], mobile, not m.get("enabled"))
            with b3:
                if st.button("Delete", key=f"alerts_del_{m['id']}"):
                    delete_alert_monitor_by_id(m["id"], mobile)


def render_alerts_tab():
    st.caption(
        "Monitor **Multi-Combo** strategy combos on a schedule. When a live entry setup "
        "appears on the latest candle, alerts go to Telegram and/or email. "
        "**Auto-poll runs while this tab is open** — use **Run poll now** anytime."
    )

    mobile = get_logged_in_mobile()
    if not mobile:
        st.warning("Please **log in** to create and manage strategy alerts.")
        _render_config_status()
        return

    _render_config_status()
    st.divider()
    _render_create_monitors(mobile)
    st.divider()
    _render_monitors_and_poll(mobile)

    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai("alerts")
