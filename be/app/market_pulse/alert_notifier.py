"""Telegram and email alert delivery (credentials from project .env)."""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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


def telegram_configured() -> bool:
    return bool(get_telegram_bot_token() and get_telegram_chat_id())


def email_configured() -> bool:
    return bool(
        get_smtp_host()
        and get_smtp_user()
        and get_smtp_password()
        and get_alert_email_to()
    )


def send_telegram_alert(message: str) -> tuple[bool, str]:
    if not is_alerts_enabled():
        return False, "Alerts disabled (set ALERTS_ENABLED=true in .env)"
    token = get_telegram_bot_token()
    chat_id = get_telegram_chat_id()
    if not token or not chat_id:
        return False, "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env"
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        if resp.status_code != 200:
            return False, resp.text[:200]
        return True, "Telegram sent"
    except Exception as exc:
        return False, str(exc)


def send_email_alert(subject: str, body: str) -> tuple[bool, str]:
    if not is_alerts_enabled():
        return False, "Alerts disabled (set ALERTS_ENABLED=true in .env)"
    host = get_smtp_host()
    port = get_smtp_port()
    user = get_smtp_user()
    password = get_smtp_password()
    to_addr = get_alert_email_to()
    from_addr = get_smtp_from() or user

    if not all([host, user, password, to_addr]):
        return False, "Missing SMTP_HOST, SMTP_USER, SMTP_PASSWORD, or ALERT_EMAIL_TO in .env"

    try:
        msg = MIMEMultipart()
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        return True, "Email sent"
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
) -> dict:
    """Send alert on configured channels. Returns {telegram: (ok, msg), email: (ok, msg)}."""
    price_str = f"{close:,.4f}" if close is not None else "—"
    body = (
        f"🔔 Trade setup alert\n"
        f"Monitor: {monitor_name}\n"
        f"Market: {market}\n"
        f"Ticker: {ticker}\n"
        f"Timeframe: {timeframe}\n"
        f"Strategy: {strategy}\n"
        f"Signal: {signal}\n"
        f"Price: {price_str}\n"
        f"Bar: {bar_time or '—'}\n"
    )
    subject = f"[Strategy Alert] {signal} · {ticker} · {timeframe}"

    results: dict = {}
    if via_telegram:
        results["telegram"] = send_telegram_alert(body)
    if via_email:
        results["email"] = send_email_alert(subject, body)
    return results
