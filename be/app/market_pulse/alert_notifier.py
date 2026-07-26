"""Telegram and email alert delivery (.env defaults + optional runtime overrides)."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests

from app.market_pulse.env_config import (
    get_alert_email_to,
    get_smtp_from,
    get_smtp_host,
    get_smtp_password,
    get_smtp_port,
    get_smtp_user,
    get_telegram_bot_token,
    get_telegram_chat_id,
    is_alerts_enabled,
)


@dataclass
class NotifyConfig:
    """Optional overrides; empty fields fall back to .env."""

    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    email_to: str | list[str] | None = None
    telegram_bot_token: str | None = None
    telegram_chat_ids: str | list[str] | None = None


def _split_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = str(value).replace(";", ",").split(",")
    return [x.strip() for x in items if x and str(x).strip()]


def notify_config_from_dict(d: dict[str, Any] | None) -> NotifyConfig | None:
    if not d:
        return None
    port = d.get("smtp_port")
    try:
        port_i = int(port) if port not in (None, "") else None
    except (TypeError, ValueError):
        port_i = None
    return NotifyConfig(
        smtp_host=(d.get("smtp_host") or None) or None,
        smtp_port=port_i,
        smtp_user=(d.get("smtp_user") or None) or None,
        smtp_password=(d.get("smtp_password") or None) or None,
        smtp_from=(d.get("smtp_from") or None) or None,
        email_to=d.get("email_to") or d.get("alert_email_to"),
        telegram_bot_token=(d.get("telegram_bot_token") or None) or None,
        telegram_chat_ids=d.get("telegram_chat_ids") or d.get("telegram_chat_id"),
    )


def telegram_configured(cfg: NotifyConfig | None = None) -> bool:
    token = (cfg.telegram_bot_token if cfg and cfg.telegram_bot_token else None) or get_telegram_bot_token()
    chats = _split_list(cfg.telegram_chat_ids if cfg else None) or _split_list(get_telegram_chat_id())
    return bool(token and chats)


def email_configured(cfg: NotifyConfig | None = None) -> bool:
    host = (cfg.smtp_host if cfg and cfg.smtp_host else None) or get_smtp_host()
    user = (cfg.smtp_user if cfg and cfg.smtp_user else None) or get_smtp_user()
    password = (cfg.smtp_password if cfg and cfg.smtp_password else None) or get_smtp_password()
    tos = _split_list(cfg.email_to if cfg else None) or _split_list(get_alert_email_to())
    return bool(host and user and password and tos)


def send_telegram_alert(message: str, cfg: NotifyConfig | None = None) -> tuple[bool, str]:
    if not is_alerts_enabled():
        return False, "Alerts disabled (set ALERTS_ENABLED=true in .env)"
    token = (cfg.telegram_bot_token if cfg and cfg.telegram_bot_token else None) or get_telegram_bot_token()
    chat_ids = _split_list(cfg.telegram_chat_ids if cfg else None) or _split_list(get_telegram_chat_id())
    if not token or not chat_ids:
        return False, "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"
    errors: list[str] = []
    ok_n = 0
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        for chat_id in chat_ids:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "text": message},
                timeout=10,
            )
            if resp.status_code == 200:
                ok_n += 1
            else:
                errors.append(f"{chat_id}: {resp.text[:120]}")
        if ok_n:
            return True, f"Telegram sent to {ok_n}/{len(chat_ids)}"
        return False, "; ".join(errors)[:200] or "Telegram failed"
    except Exception as exc:
        return False, str(exc)


def send_email_alert(subject: str, body: str, cfg: NotifyConfig | None = None) -> tuple[bool, str]:
    if not is_alerts_enabled():
        return False, "Alerts disabled (set ALERTS_ENABLED=true in .env)"
    host = (cfg.smtp_host if cfg and cfg.smtp_host else None) or get_smtp_host()
    port = (cfg.smtp_port if cfg and cfg.smtp_port else None) or get_smtp_port()
    user = (cfg.smtp_user if cfg and cfg.smtp_user else None) or get_smtp_user()
    password = (cfg.smtp_password if cfg and cfg.smtp_password else None) or get_smtp_password()
    to_addrs = _split_list(cfg.email_to if cfg else None) or _split_list(get_alert_email_to())
    from_addr = (
        (cfg.smtp_from if cfg and cfg.smtp_from else None) or get_smtp_from() or user
    )

    if not all([host, user, password]) or not to_addrs:
        return False, "Missing SMTP_HOST, SMTP_USER, SMTP_PASSWORD, or email TO list"

    try:
        msg = MIMEMultipart()
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(host, int(port or 587), timeout=15) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
        return True, f"Email sent to {len(to_addrs)} recipient(s)"
    except Exception as exc:
        return False, str(exc)


def send_trade_setup_alert(
    *,
    ticker: str,
    timeframe: str,
    strategy: str,
    market: str,
    signal: str,
    close: float | None,
    bar_time: str | None,
    monitor_name: str,
    via_telegram: bool,
    via_email: bool,
    reasons: list[str] | None = None,
    cfg: NotifyConfig | None = None,
) -> dict:
    """Send alert on configured channels. Returns {telegram: (ok, msg), email: (ok, msg)}."""
    price_str = f"{close:,.4f}" if close is not None else "—"
    reason_block = ""
    if reasons:
        reason_block = "Reasons:\n" + "\n".join(f"· {r}" for r in reasons if r) + "\n"
    body = (
        f"Trade setup alert\n"
        f"Schedule/Monitor: {monitor_name}\n"
        f"Market: {market}\n"
        f"Ticker: {ticker}\n"
        f"Timeframe: {timeframe}\n"
        f"Strategy: {strategy}\n"
        f"Signal: {signal}\n"
        f"Price: {price_str}\n"
        f"Bar: {bar_time or '—'}\n"
        f"{reason_block}"
    )
    subject = f"[Strategy Alert] {signal} · {ticker} · {timeframe} · {monitor_name}"

    results: dict = {}
    if via_telegram:
        results["telegram"] = send_telegram_alert(body, cfg)
    if via_email:
        results["email"] = send_email_alert(subject, body, cfg)
    return results
