"""
database.py
-----------
SQLite database management with mobile-number based isolation for saving and loading trading strategies and reports.

Ported from truebacktesting/database.py. The original stored its SQLite file as
`strategies.db` next to the source file; this backend instead uses
be/data/market_pulse.db (BASE_DIR = parents[2] of this file -> be/, then data/market_pulse.db)
so it lines up with the rest of the app's data directory.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATABASE_PATH = str(BASE_DIR / "data" / "market_pulse.db")
Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes the SQLite tables."""
    conn = get_connection()
    cursor = conn.cursor()
    # Add mobile_number column to isolate strategies per user
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_number TEXT NOT NULL,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            ticker TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            initial_capital REAL NOT NULL,
            commission REAL NOT NULL,
            slippage REAL NOT NULL,
            sl_pct REAL NOT NULL,
            tp_pct REAL NOT NULL,
            indicators TEXT NOT NULL,
            entry_rules TEXT NOT NULL,
            exit_rules TEXT NOT NULL,
            metrics TEXT NOT NULL,
            report_path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mobile_number, name)
        )
    """)
    # Add user_custom_strategies table for LLM generated custom strategies
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_custom_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_number TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            market TEXT NOT NULL, -- "Groww", "CoinDCX", or "Both"
            recommended_timeframe TEXT,
            recommended_sl REAL,
            recommended_tp REAL,
            indicators TEXT NOT NULL,
            entry_rules TEXT NOT NULL,
            exit_rules TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mobile_number, name)
        )
    """)
    # Add use_later_strategies table for draft/use-later strategies
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS use_later_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_number TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            market TEXT NOT NULL, -- "Groww", "CoinDCX", or "Both"
            recommended_timeframe TEXT,
            recommended_sl REAL,
            recommended_tp REAL,
            indicators TEXT NOT NULL,
            entry_rules TEXT NOT NULL,
            exit_rules TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mobile_number, name)
        )
    """)
    # Add multi_combo_scans table for saving Multi-Combo Scanner runs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS multi_combo_scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_number TEXT NOT NULL,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            tickers TEXT NOT NULL,
            timeframes TEXT NOT NULL,
            scan_results TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mobile_number, name)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_number TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            groww_token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN groww_token TEXT")
    except sqlite3.OperationalError:
        pass
    # Add saved_screeners table for the Advanced Screener
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_screeners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_number TEXT NOT NULL,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            exchange TEXT,
            index_name TEXT,
            timeframes TEXT NOT NULL,
            lookback INTEGER,
            indicators TEXT NOT NULL,
            entry_rules TEXT NOT NULL,
            exit_rules TEXT NOT NULL,
            entry_mode TEXT,
            exit_mode TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mobile_number, name)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_combo_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_number TEXT NOT NULL,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            ticker TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            indicators TEXT NOT NULL,
            entry_rules TEXT NOT NULL,
            exit_rules TEXT NOT NULL,
            entry_mode TEXT DEFAULT 'AND',
            return_pct REAL,
            sharpe REAL,
            win_rate_pct REAL,
            trades INTEGER,
            outcome_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mobile_number, market, ticker, timeframe, strategy_name)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_alert_monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_number TEXT NOT NULL,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            ticker TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            indicators TEXT NOT NULL,
            entry_rules TEXT NOT NULL,
            exit_rules TEXT NOT NULL,
            entry_mode TEXT DEFAULT 'AND',
            poll_minutes INTEGER NOT NULL DEFAULT 15,
            notify_telegram INTEGER DEFAULT 1,
            notify_email INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            last_checked_at TIMESTAMP,
            last_signal TEXT DEFAULT 'INACTIVE',
            last_alert_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mobile_number, name)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS demo_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_number TEXT NOT NULL,
            market_type TEXT NOT NULL,
            market_label TEXT NOT NULL,
            ticker TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            direction TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 1,
            entry_price REAL NOT NULL,
            strategy_name TEXT,
            source_tab TEXT,
            stop_loss_pct REAL,
            stop_loss_amount REAL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            exit_price REAL,
            closed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_number TEXT NOT NULL,
            market_type TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mobile_number, market_type, name)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watchlist_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            display_name TEXT,
            added_price REAL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(watchlist_id, ticker)
        )
    """)
    conn.commit()
    conn.close()


init_db()


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${pwd_hash.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, pwd_hash = stored_hash.split("$", 1)
    except ValueError:
        return False
    new_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return secrets.compare_digest(new_hash.hex(), pwd_hash)


def user_exists(mobile_number: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM users WHERE mobile_number = ?", (mobile_number,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def register_user(mobile_number: str, password: str) -> tuple[bool, str]:
    """Register a new user. Returns (success, message)."""
    if user_exists(mobile_number):
        return False, "User already present with this mobile number."
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (mobile_number, password_hash) VALUES (?, ?)",
            (mobile_number, _hash_password(password)),
        )
        conn.commit()
        conn.close()
        return True, "Registration successful. Please log in."
    except Exception as e:
        print(f"Error registering user: {e}")
        return False, "Registration failed. Please try again."


def authenticate_user(mobile_number: str, password: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT password_hash FROM users WHERE mobile_number = ?",
        (mobile_number,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    return _verify_password(password, row["password_hash"])


def get_groww_token(mobile_number: str) -> str:
    """Return saved Groww bearer token for a user, or empty string."""
    if not mobile_number:
        return ""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT groww_token FROM users WHERE mobile_number = ?",
        (mobile_number.strip(),),
    )
    row = cursor.fetchone()
    conn.close()
    if not row or not row["groww_token"]:
        return ""
    return str(row["groww_token"]).strip()


def save_groww_token(mobile_number: str, token: str) -> tuple[bool, str]:
    """Persist Groww bearer token for a logged-in user."""
    if not mobile_number:
        return False, "Not logged in."
    token = (token or "").strip()
    if not token:
        return False, "Groww token cannot be empty."
    if not user_exists(mobile_number):
        return False, "User account not found."
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET groww_token = ? WHERE mobile_number = ?",
            (token, mobile_number.strip()),
        )
        conn.commit()
        conn.close()
        return True, "Groww token saved to your account."
    except Exception as e:
        print(f"Error saving Groww token: {e}")
        return False, "Failed to save Groww token. Please try again."


def delete_groww_token(mobile_number: str) -> tuple[bool, str]:
    """Remove saved Groww bearer token for a user."""
    if not mobile_number:
        return False, "Not logged in."
    if not user_exists(mobile_number):
        return False, "User account not found."
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET groww_token = NULL WHERE mobile_number = ?",
            (mobile_number.strip(),),
        )
        conn.commit()
        conn.close()
        return True, "Saved Groww token removed."
    except Exception as e:
        print(f"Error deleting Groww token: {e}")
        return False, "Failed to remove Groww token. Please try again."


def update_user_password(mobile_number: str, new_password: str) -> tuple[bool, str]:
    """Reset password for an existing user. Returns (success, message)."""
    if not user_exists(mobile_number):
        return False, "No account found with this mobile number."
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE mobile_number = ?",
            (_hash_password(new_password), mobile_number),
        )
        conn.commit()
        conn.close()
        return True, "Password updated successfully. Please log in with your new password."
    except Exception as e:
        print(f"Error updating password: {e}")
        return False, "Failed to update password. Please try again."


def save_strategy(mobile_number: str, name: str, market: str, ticker: str, timeframe: str,
                  start_date: str, end_date: str, initial_capital: float,
                  commission: float, slippage: float, sl_pct: float, tp_pct: float,
                  indicators: list, entry_rules: list, exit_rules: list,
                  metrics: dict, report_path: str) -> bool:
    """Saves a strategy to the database associated with a unique mobile number."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO saved_strategies (
                mobile_number, name, market, ticker, timeframe, start_date, end_date, initial_capital,
                commission, slippage, sl_pct, tp_pct, indicators, entry_rules, exit_rules,
                metrics, report_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mobile_number, name, market, ticker, timeframe, start_date, end_date, initial_capital,
            commission, slippage, sl_pct, tp_pct,
            json.dumps(indicators), json.dumps(entry_rules), json.dumps(exit_rules),
            json.dumps(metrics), report_path
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving strategy: {e}")
        return False

def get_strategies_by_mobile(mobile_number: str) -> list:
    """Retrieves all saved strategies matching a unique mobile number."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM saved_strategies WHERE mobile_number = ? ORDER BY created_at DESC", (mobile_number,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_strategy_by_name(mobile_number: str, name: str) -> dict:
    """Retrieves a single strategy matching a mobile number and strategy name."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM saved_strategies WHERE mobile_number = ? AND name = ?", (mobile_number, name))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_strategy(mobile_number: str, name: str) -> bool:
    """Deletes a strategy matching a mobile number and name."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM saved_strategies WHERE mobile_number = ? AND name = ?", (mobile_number, name))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting strategy: {e}")
        return False

def save_custom_strategy(mobile_number: str, name: str, description: str, market: str,
                         recommended_timeframe: str, recommended_sl: float, recommended_tp: float,
                         indicators: list, entry_rules: list, exit_rules: list) -> bool:
    """Saves a custom (LLM-generated) strategy to the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO user_custom_strategies (
                mobile_number, name, description, market, recommended_timeframe, recommended_sl, recommended_tp,
                indicators, entry_rules, exit_rules
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mobile_number, name, description, market, recommended_timeframe, recommended_sl, recommended_tp,
            json.dumps(indicators), json.dumps(entry_rules), json.dumps(exit_rules)
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving custom strategy: {e}")
        return False

def get_custom_strategies_by_mobile(mobile_number: str) -> list:
    """Retrieves all custom strategies matching a unique mobile number."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_custom_strategies WHERE mobile_number = ? ORDER BY created_at DESC", (mobile_number,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_custom_strategy(mobile_number: str, name: str) -> bool:
    """Deletes a custom strategy matching a mobile number and name."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_custom_strategies WHERE mobile_number = ? AND name = ?", (mobile_number, name))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting custom strategy: {e}")
        return False

def save_use_later_strategy(mobile_number: str, name: str, description: str, market: str,
                            recommended_timeframe: str, recommended_sl: float, recommended_tp: float,
                            indicators: list, entry_rules: list, exit_rules: list) -> bool:
    """Saves a use-later strategy to the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO use_later_strategies (
                mobile_number, name, description, market, recommended_timeframe, recommended_sl, recommended_tp,
                indicators, entry_rules, exit_rules
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mobile_number, name, description, market, recommended_timeframe, recommended_sl, recommended_tp,
            json.dumps(indicators), json.dumps(entry_rules), json.dumps(exit_rules)
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving use-later strategy: {e}")
        return False

def get_use_later_strategies_by_mobile(mobile_number: str) -> list:
    """Retrieves all use-later strategies matching a unique mobile number."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM use_later_strategies WHERE mobile_number = ? ORDER BY created_at DESC", (mobile_number,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_use_later_strategy(mobile_number: str, name: str) -> bool:
    """Deletes a use-later strategy matching a mobile number and name."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM use_later_strategies WHERE mobile_number = ? AND name = ?", (mobile_number, name))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting use-later strategy: {e}")
        return False

def save_multi_combo_scan(mobile_number: str, name: str, market: str, tickers: list,
                          timeframes: list, scan_results: list) -> bool:
    """Saves a Multi-Combo Scanner run to the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO multi_combo_scans (
                mobile_number, name, market, tickers, timeframes, scan_results
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            mobile_number, name, market,
            json.dumps(tickers), json.dumps(timeframes), json.dumps(scan_results)
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving multi combo scan: {e}")
        return False

def get_multi_combo_scans_by_mobile(mobile_number: str) -> list:
    """Retrieves all Multi-Combo Scans matching a unique mobile number."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM multi_combo_scans WHERE mobile_number = ? ORDER BY created_at DESC", (mobile_number,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_multi_combo_scan(mobile_number: str, name: str) -> bool:
    """Deletes a Multi-Combo Scan matching a mobile number and name."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM multi_combo_scans WHERE mobile_number = ? AND name = ?", (mobile_number, name))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting multi combo scan: {e}")
        return False


def save_combo_outcome(
    mobile_number: str,
    name: str,
    market: str,
    ticker: str,
    timeframe: str,
    strategy_name: str,
    indicators: list,
    entry_rules: list,
    exit_rules: list,
    *,
    return_pct: float = None,
    sharpe: float = None,
    win_rate_pct: float = None,
    trades: int = 0,
    outcome_json: dict = None,
    entry_mode: str = "AND",
) -> bool:
    """Save one Multi-Combo row (ticker x TF x strategy) for alert monitoring."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO saved_combo_outcomes (
                mobile_number, name, market, ticker, timeframe, strategy_name,
                indicators, entry_rules, exit_rules, entry_mode,
                return_pct, sharpe, win_rate_pct, trades, outcome_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mobile_number, name, market, ticker.upper().strip(), timeframe, strategy_name,
            json.dumps(indicators), json.dumps(entry_rules), json.dumps(exit_rules), entry_mode,
            return_pct, sharpe, win_rate_pct, trades,
            json.dumps(outcome_json) if outcome_json else None,
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving combo outcome: {e}")
        return False


def get_combo_outcomes_by_mobile(mobile_number: str, market: str = None) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    if market:
        cursor.execute(
            "SELECT * FROM saved_combo_outcomes WHERE mobile_number = ? AND market = ? ORDER BY created_at DESC",
            (mobile_number, market),
        )
    else:
        cursor.execute(
            "SELECT * FROM saved_combo_outcomes WHERE mobile_number = ? ORDER BY created_at DESC",
            (mobile_number,),
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_combo_outcome(mobile_number: str, outcome_id: int) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM saved_combo_outcomes WHERE id = ? AND mobile_number = ?",
            (outcome_id, mobile_number),
        )
        conn.commit()
        ok = cursor.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        print(f"Error deleting combo outcome: {e}")
        return False


def save_screener(mobile_number: str, name: str, market: str, exchange: str, index_name: str,
                  timeframes: list, lookback: int, indicators: list, entry_rules: list, exit_rules: list,
                  entry_mode: str, exit_mode: str) -> bool:
    """Saves an Advanced Screener configuration to the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO saved_screeners (
                mobile_number, name, market, exchange, index_name, timeframes, lookback,
                indicators, entry_rules, exit_rules, entry_mode, exit_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mobile_number, name, market, exchange, index_name,
            json.dumps(timeframes), lookback,
            json.dumps(indicators), json.dumps(entry_rules), json.dumps(exit_rules),
            entry_mode, exit_mode
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving screener: {e}")
        return False

def get_screeners_by_mobile(mobile_number: str) -> list:
    """Retrieves all saved screeners matching a unique mobile number."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM saved_screeners WHERE mobile_number = ? ORDER BY created_at DESC", (mobile_number,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_screener(mobile_number: str, name: str) -> bool:
    """Deletes a saved screener matching a mobile number and name."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM saved_screeners WHERE mobile_number = ? AND name = ?", (mobile_number, name))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting screener: {e}")
        return False


# --- Strategy alert monitors -----------------------------------------------

def save_alert_monitor(
    mobile_number: str,
    name: str,
    market: str,
    ticker: str,
    timeframe: str,
    strategy_name: str,
    indicators: list,
    entry_rules: list,
    exit_rules: list,
    poll_minutes: int = 15,
    notify_telegram: bool = True,
    notify_email: bool = False,
    entry_mode: str = "AND",
    enabled: bool = True,
) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO strategy_alert_monitors (
                mobile_number, name, market, ticker, timeframe, strategy_name,
                indicators, entry_rules, exit_rules, entry_mode, poll_minutes,
                notify_telegram, notify_email, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mobile_number, name, market, ticker.upper().strip(), timeframe, strategy_name,
            json.dumps(indicators), json.dumps(entry_rules), json.dumps(exit_rules),
            entry_mode, int(poll_minutes),
            1 if notify_telegram else 0, 1 if notify_email else 0,
            1 if enabled else 0,
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving alert monitor: {e}")
        return False


def get_alert_monitors_by_mobile(mobile_number: str, enabled_only: bool = False) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM strategy_alert_monitors WHERE mobile_number = ?"
    params: list = [mobile_number]
    if enabled_only:
        query += " AND enabled = 1"
    query += " ORDER BY created_at DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_alert_monitor_state(
    monitor_id: int,
    mobile_number: str,
    last_signal: str,
    *,
    last_alert_at: str | None = None,
) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        if last_alert_at:
            cursor.execute("""
                UPDATE strategy_alert_monitors
                SET last_checked_at = CURRENT_TIMESTAMP,
                    last_signal = ?,
                    last_alert_at = ?
                WHERE id = ? AND mobile_number = ?
            """, (last_signal, last_alert_at, monitor_id, mobile_number))
        else:
            cursor.execute("""
                UPDATE strategy_alert_monitors
                SET last_checked_at = CURRENT_TIMESTAMP,
                    last_signal = ?
                WHERE id = ? AND mobile_number = ?
            """, (last_signal, monitor_id, mobile_number))
        conn.commit()
        ok = cursor.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        print(f"Error updating alert monitor state: {e}")
        return False


def set_alert_monitor_enabled(monitor_id: int, mobile_number: str, enabled: bool) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE strategy_alert_monitors SET enabled = ? WHERE id = ? AND mobile_number = ?",
            (1 if enabled else 0, monitor_id, mobile_number),
        )
        conn.commit()
        ok = cursor.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        print(f"Error toggling alert monitor: {e}")
        return False


def delete_alert_monitor(mobile_number: str, name: str) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM strategy_alert_monitors WHERE mobile_number = ? AND name = ?",
            (mobile_number, name),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting alert monitor: {e}")
        return False


def delete_alert_monitor_by_id(monitor_id: int, mobile_number: str) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM strategy_alert_monitors WHERE id = ? AND mobile_number = ?",
            (monitor_id, mobile_number),
        )
        conn.commit()
        ok = cursor.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        print(f"Error deleting alert monitor: {e}")
        return False


# --- Demo (paper) trades -----------------------------------------------------

def create_demo_trade(
    mobile_number: str,
    market_type: str,
    market_label: str,
    ticker: str,
    timeframe: str,
    direction: str,
    quantity: float,
    entry_price: float,
    strategy_name: str = "",
    source_tab: str = "",
    stop_loss_pct: float = None,
    stop_loss_amount: float = None,
) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO demo_trades (
                mobile_number, market_type, market_label, ticker, timeframe,
                direction, quantity, entry_price, strategy_name, source_tab,
                stop_loss_pct, stop_loss_amount, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """, (
            mobile_number, market_type, market_label, ticker, timeframe,
            direction.upper(), quantity, entry_price, strategy_name or "Manual",
            source_tab, stop_loss_pct, stop_loss_amount,
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error creating demo trade: {e}")
        return False


def get_demo_trades(mobile_number: str, market_type: str = None, status: str = None) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM demo_trades WHERE mobile_number = ?"
    params = [mobile_number]
    if market_type:
        query += " AND market_type = ?"
        params.append(market_type)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def close_demo_trade(trade_id: int, mobile_number: str, exit_price: float) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE demo_trades
            SET status = 'CLOSED', exit_price = ?, closed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND mobile_number = ? AND status = 'OPEN'
        """, (exit_price, trade_id, mobile_number))
        conn.commit()
        ok = cursor.rowcount > 0
        conn.close()
        return ok
    except Exception as e:
        print(f"Error closing demo trade: {e}")
        return False


def delete_all_demo_trades(mobile_number: str, market_type: str) -> int:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM demo_trades WHERE mobile_number = ? AND market_type = ?",
            (mobile_number, market_type),
        )
        conn.commit()
        deleted = cursor.rowcount
        conn.close()
        return deleted
    except Exception as e:
        print(f"Error deleting demo trades: {e}")
        return 0


def create_watchlist(mobile_number: str, market_type: str, name: str) -> tuple[bool, str]:
    name = (name or "").strip()
    if not name:
        return False, "Watchlist name cannot be empty."
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO watchlists (mobile_number, market_type, name) VALUES (?, ?, ?)",
            (mobile_number, market_type, name),
        )
        conn.commit()
        return True, "Watchlist created."
    except sqlite3.IntegrityError:
        return False, f"A watchlist named '{name}' already exists for this market."
    except Exception as e:
        print(f"Error creating watchlist: {e}")
        return False, "Could not create watchlist."
    finally:
        conn.close()


def get_watchlists(mobile_number: str, market_type: str) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM watchlists WHERE mobile_number = ? AND market_type = ? ORDER BY created_at ASC",
        (mobile_number, market_type),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_watchlist(watchlist_id: int, mobile_number: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM watchlists WHERE id = ? AND mobile_number = ?",
            (watchlist_id, mobile_number),
        )
        if cursor.fetchone() is None:
            return False
        cursor.execute("DELETE FROM watchlist_items WHERE watchlist_id = ?", (watchlist_id,))
        cursor.execute(
            "DELETE FROM watchlists WHERE id = ? AND mobile_number = ?",
            (watchlist_id, mobile_number),
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting watchlist: {e}")
        return False
    finally:
        conn.close()


def add_watchlist_item(
    watchlist_id: int, mobile_number: str, ticker: str, display_name: str, added_price: float | None,
) -> tuple[bool, str]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM watchlists WHERE id = ? AND mobile_number = ?",
            (watchlist_id, mobile_number),
        )
        if cursor.fetchone() is None:
            return False, "Watchlist not found."
        cursor.execute(
            "INSERT INTO watchlist_items (watchlist_id, ticker, display_name, added_price) VALUES (?, ?, ?, ?)",
            (watchlist_id, ticker.upper(), display_name, added_price),
        )
        conn.commit()
        return True, "Added to watchlist."
    except sqlite3.IntegrityError:
        return False, f"{ticker.upper()} is already in this watchlist."
    except Exception as e:
        print(f"Error adding watchlist item: {e}")
        return False, "Could not add ticker."
    finally:
        conn.close()


def get_watchlist_items(watchlist_id: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM watchlist_items WHERE watchlist_id = ? ORDER BY added_at ASC",
        (watchlist_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_watchlist_item(item_id: int, watchlist_id: int, mobile_number: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT w.id FROM watchlists w WHERE w.id = ? AND w.mobile_number = ?",
            (watchlist_id, mobile_number),
        )
        if cursor.fetchone() is None:
            return False
        cursor.execute(
            "DELETE FROM watchlist_items WHERE id = ? AND watchlist_id = ?",
            (item_id, watchlist_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"Error removing watchlist item: {e}")
        return False
    finally:
        conn.close()
