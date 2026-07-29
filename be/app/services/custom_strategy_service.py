"""Strategy Lab — saved custom strategies (Builder + AI Strategy Creator)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import CustomStrategy
from app.services.ai_service import call_ai_report
from app.services.settings_service import SettingsService

AI_STRATEGY_SYSTEM_PROMPT = """You are an expert quantitative trading strategy designer. Convert the user's plain-English
description or transcript of a trading strategy into a strict JSON object this exact backtesting engine can execute.

Respond with ONLY a single JSON object — no markdown fences, no commentary — matching this schema:
{
  "description": "<one-paragraph summary of the strategy>",
  "recommended_timeframe": "<one of: 1m,3m,5m,15m,30m,1h,4h,1d,1wk>",
  "recommended_sl": <number, stop-loss percent, e.g. 2.0>,
  "recommended_tp": <number, take-profit percent, e.g. 4.0>,
  "direction_mode": "<one of: long_only, short_only, long_short>",
  "indicators": [ {"type": "<indicator type>", ...params} ],
  "entry_rules": [ {"left": "<column>", "op": "<operator>", "right_type": "value|indicator", "right_val": "<string>"} ],
  "exit_rules": [ {"left": "<column>", "op": "<operator>", "right_type": "value|indicator", "right_val": "<string>"} ],
  "entry_mode": "AND|OR",
  "exit_mode": "AND|OR"
}

Available indicator types and their EXACT params (include every listed param, and the resulting column name(s)
you may reference in "left"/"right_val" when right_type is "indicator"):
- {"type": "ema", "period": int} -> column "ema_{period}"
- {"type": "sma", "period": int} -> column "sma_{period}"
- {"type": "vwap"} -> column "vwap"
- {"type": "rsi", "period": int} -> column "rsi_{period}"
- {"type": "bb", "period": int, "std_dev": float} -> columns "bb_upper_{period}_{std_dev}", "bb_middle_{period}_{std_dev}", "bb_lower_{period}_{std_dev}"
- {"type": "atr", "period": int} -> column "atr_{period}"
- {"type": "supertrend", "period": int, "multiplier": float} -> columns "supertrend_{period}_{multiplier}", "supertrend_dir_{period}_{multiplier}"
- {"type": "macd", "fast": int, "slow": int, "signal": int} -> columns "macd_{fast}_{slow}", "macd_signal_{fast}_{slow}_{signal}", "macd_hist_{fast}_{slow}_{signal}"
- {"type": "stochastic", "k_period": int, "d_period": int} -> columns "stoch_k_{k_period}", "stoch_d_{k_period}_{d_period}"
- {"type": "adx", "period": int} -> columns "adx_{period}", "plus_di_{period}", "minus_di_{period}"
- {"type": "obv"} -> column "obv"
- {"type": "vol_sma", "period": int} -> columns "vol_sma_{period}", "vol_ratio_{period}"
- {"type": "pivots"} -> columns "pivot", "pivot_r1", "pivot_s1", "pivot_r2", "pivot_s2"
- {"type": "fibonacci", "lookback": int} -> columns "fib_high_{lookback}", "fib_low_{lookback}", "fib_0.236_{lookback}", "fib_0.382_{lookback}", "fib_0.5_{lookback}", "fib_0.618_{lookback}", "fib_0.786_{lookback}"
- {"type": "cci", "period": int} -> column "cci_{period}"
- {"type": "roc", "period": int} -> column "roc_{period}"
- {"type": "williams_r", "period": int} -> column "williams_r_{period}"
- {"type": "mfi", "period": int} -> column "mfi_{period}"
- {"type": "donchian", "period": int} -> columns "donchian_upper_{period}", "donchian_lower_{period}", "donchian_middle_{period}"

Base OHLCV columns always available: "open", "high", "low", "close", "volume".

Operators allowed in "op": ">", "<", ">=", "<=", "==", "crosses above", "crosses below".
"right_type": "value" means right_val is a literal number (as a string); "right_type": "indicator" means right_val
is one of the column names above (or a base OHLCV column).

Rules:
- Only reference columns produced by an indicator you actually included in "indicators", or a base OHLCV column.
- Keep the ruleset small and faithful to what the user described — do not invent extra filters they didn't mention.
- If the user's description is ambiguous about SL/TP, pick sensible defaults for the described style
  (e.g. tighter for scalping, wider for swing)."""


def _parse_json_strategy(raw: str) -> dict[str, Any]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("AI response was not a JSON object.")
    return data


def _parse_json_list(raw: str | None) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


class CustomStrategyService:
    def __init__(self, db: AsyncSession, settings: SettingsService):
        self.db = db
        self.settings = settings

    async def list_strategies(self, user_id: int, *, market: str | None = None) -> list[dict[str, Any]]:
        q = select(CustomStrategy).where(CustomStrategy.user_id == user_id)
        if market:
            q = q.where(CustomStrategy.market == market)
        q = q.order_by(CustomStrategy.id.desc())
        result = await self.db.execute(q)
        return [self._dict(s) for s in result.scalars().all()]

    async def create_strategy(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        row = CustomStrategy(
            user_id=user_id,
            name=str(payload["name"]).strip(),
            market=payload["market"],
            asset_class=payload.get("asset_class") or "india",
            description=payload.get("description"),
            timeframe=payload.get("timeframe") or "1d",
            indicators_json=json.dumps(payload.get("indicators") or []),
            entry_rules_json=json.dumps(payload.get("entry_rules") or []),
            exit_rules_json=json.dumps(payload.get("exit_rules") or []),
            entry_mode=payload.get("entry_mode") or "AND",
            exit_mode=payload.get("exit_mode") or "AND",
            direction_mode=payload.get("direction_mode") or "long_only",
            position_sizing=payload.get("position_sizing") or "pct_of_capital",
            capital_allocation_pct=float(payload.get("capital_allocation_pct") or 95.0),
            risk_pct=float(payload.get("risk_pct") or 1.0),
            sl_pct=float(payload.get("sl_pct") or 0.0),
            tp_pct=float(payload.get("tp_pct") or 0.0),
            source=payload.get("source") or "manual",
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return self._dict(row)

    async def update_strategy(self, user_id: int, strategy_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = await self._get(user_id, strategy_id)
        if not row:
            return None
        if "name" in payload and payload["name"]:
            row.name = str(payload["name"]).strip()
        if "description" in payload:
            row.description = payload["description"]
        if "timeframe" in payload and payload["timeframe"]:
            row.timeframe = payload["timeframe"]
        if "indicators" in payload and payload["indicators"] is not None:
            row.indicators_json = json.dumps(payload["indicators"])
        if "entry_rules" in payload and payload["entry_rules"] is not None:
            row.entry_rules_json = json.dumps(payload["entry_rules"])
        if "exit_rules" in payload and payload["exit_rules"] is not None:
            row.exit_rules_json = json.dumps(payload["exit_rules"])
        for key in (
            "entry_mode", "exit_mode", "direction_mode", "position_sizing",
            "capital_allocation_pct", "risk_pct", "sl_pct", "tp_pct",
        ):
            if key in payload and payload[key] is not None:
                setattr(row, key, payload[key])
        row.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(row)
        return self._dict(row)

    async def delete_strategy(self, user_id: int, strategy_id: int) -> bool:
        row = await self._get(user_id, strategy_id)
        if not row:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def _get(self, user_id: int, strategy_id: int) -> CustomStrategy | None:
        result = await self.db.execute(
            select(CustomStrategy).where(CustomStrategy.id == strategy_id, CustomStrategy.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def ai_generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = await self.settings.get_ai_provider()
        model = await self.settings.get_ai_model(provider)
        api_key = await self.settings.get_api_key_for_provider(provider)

        text = str(payload["text"]).strip()
        name_hint = payload.get("strategy_name") or "the described strategy"
        report = call_ai_report(
            text,
            AI_STRATEGY_SYSTEM_PROMPT,
            provider,
            model,
            api_key,
            user_intro=f"Convert {name_hint} below into the strategy JSON schema:",
            max_tokens=2000,
        )
        if report.startswith("Missing") or report.startswith("AI report error") or report.startswith("Groq SDK") or report.startswith("Google Gemini"):
            raise ValueError(report)

        parsed = _parse_json_strategy(report)
        return {
            "name": payload.get("strategy_name") or "AI-generated strategy",
            "description": parsed.get("description") or "",
            "recommended_timeframe": parsed.get("recommended_timeframe") or "1d",
            "recommended_sl": parsed.get("recommended_sl"),
            "recommended_tp": parsed.get("recommended_tp"),
            "direction_mode": parsed.get("direction_mode") or "long_only",
            "indicators": parsed.get("indicators") or [],
            "entry_rules": parsed.get("entry_rules") or [],
            "exit_rules": parsed.get("exit_rules") or [],
            "entry_mode": parsed.get("entry_mode") or "AND",
            "exit_mode": parsed.get("exit_mode") or "AND",
            "provider": provider,
            "model": model,
        }

    @staticmethod
    def _dict(row: CustomStrategy) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "market": row.market,
            "asset_class": row.asset_class,
            "description": row.description,
            "timeframe": row.timeframe,
            "indicators": _parse_json_list(row.indicators_json),
            "entry_rules": _parse_json_list(row.entry_rules_json),
            "exit_rules": _parse_json_list(row.exit_rules_json),
            "entry_mode": row.entry_mode,
            "exit_mode": row.exit_mode,
            "direction_mode": row.direction_mode,
            "position_sizing": row.position_sizing,
            "capital_allocation_pct": row.capital_allocation_pct,
            "risk_pct": row.risk_pct,
            "sl_pct": row.sl_pct,
            "tp_pct": row.tp_pct,
            "source": row.source,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
