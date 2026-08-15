"""ETF TA IN service — ETF Shop 4.0, one independent shop per asset class
(india/us/crypto/commodity) — each with its own capital pool, universe,
currency, and lot ledger, since ₹ and $ capital can't be meaningfully
combined into one number.

Two layers:
  - Stateless `scan`/`recommend` — quick "what-if" checks, portfolio passed in by caller.
  - Persisted portfolio (`EtfShopConfig` + `EtfShopLot`) — the real, durable per-user
    per-asset-class shop ledger used by the UI's one-click buy/sell and by the daily
    schedule worker, so capital settings, open lots and the latched SIP-locked symbol
    set survive across devices/browsers instead of living only in localStorage.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.etf_ta.india_etf_universe import (
    ETF_PRESETS,
    ETF_SHOP_39_PRIMARY,
    GROWW_INDIA_MARKET,
    MASTER_INDIA_ETFS,
    default_etf_universe,
    underlying_for_symbol,
)
from app.etf_ta.multi_asset_etf_universe import (
    MULTI_ASSET_ETF_UNIVERSE,
    default_universe_for,
    get_usd_inr_rate,
    preset_asset_class,
    underlying_label_for,
)
from app.etf_ta import stf_shop_engine as eng
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.serialize import json_safe
from app.models.db_models import EtfShopConfig, EtfShopLot
from app.services.settings_service import SettingsService

_CONFIG_FIELDS = (
    "deposited_capital",
    "growth_amount",
    "dividend_withdrawn",
    "shop_start_date",
    "preset",
    "custom_symbols",
    "exchange",
    "sell_mode",
    "profit_target_pct",
    "profit_target_inr",
    "min_profit_inr",
    "slots_divisor",
    "prefer_sip",
    "averaging_trigger_pct",
    "notify_telegram",
    "notify_email",
)

_DEFAULT_PRESET_BY_ASSET_CLASS: dict[str, str] = {
    "india": "ETF Shop 4.0 — 39 distinct (recommended)",
    "us": "US ETF Shop — broad + sector (recommended)",
    "crypto": "Crypto Shop — top 15 liquid coins (recommended)",
    "commodity": "Commodity ETF Shop — metals + energy + agri (recommended)",
}


class EtfTaService:
    def __init__(self, settings: SettingsService, db: AsyncSession | None = None):
        self.settings = settings
        self.db = db

    async def _groww_token(self) -> str:
        return await self.settings.get_groww_token() or ""

    async def _exchange(self) -> str:
        return await self.settings.get_groww_exchange()

    async def _asset_ctx(self, asset_class: str) -> tuple[str, str, str]:
        """Returns (market, default_exchange, currency) for the fetch/format
        layer — mirrors ProTradeService._asset_ctx, plus the currency symbol
        since ETF Shop displays money amounts in its reason strings."""
        if asset_class == "india" or asset_class not in MULTI_ASSET_ETF_UNIVERSE:
            return GROWW_INDIA_MARKET, await self.settings.get_groww_exchange(), "₹"
        entry = MULTI_ASSET_ETF_UNIVERSE[asset_class]
        return str(entry["market"]), str(entry["exchange"]), str(entry["currency"])

    def _presets_for(self, asset_class: str) -> dict[str, list[str]]:
        if asset_class == "india" or asset_class not in MULTI_ASSET_ETF_UNIVERSE:
            return dict(ETF_PRESETS)
        return dict(MULTI_ASSET_ETF_UNIVERSE[asset_class]["presets"])  # type: ignore[arg-type]

    def _default_universe_for(self, asset_class: str) -> list[str]:
        if asset_class == "india" or asset_class not in MULTI_ASSET_ETF_UNIVERSE:
            return default_etf_universe()
        return default_universe_for(asset_class)

    def _underlying_label(self, asset_class: str, symbol: str) -> str:
        if asset_class == "india" or asset_class not in MULTI_ASSET_ETF_UNIVERSE:
            return underlying_for_symbol(symbol)
        return underlying_label_for(asset_class, symbol)

    def _convert_analyses_to_inr(self, analyses: list[dict[str, Any]], asset_class: str) -> None:
        """US/Crypto/Commodity genuinely trade in USD — this mutates `price`/
        `sma20` in place to a live-rate INR value so the shop's capital pool,
        slot sizing, and quantity math all run in ₹ throughout, exactly like
        a multi-currency brokerage statement converted to a home-currency
        view. `pct_from_dma` (the ranking basis) is a ratio of the two, so
        multiplying both by the same rate never changes which instrument
        ranks #1 — only the numbers shown. No-op for India (already ₹)."""
        if asset_class == "india":
            return
        rate = get_usd_inr_rate()
        for row in analyses:
            if row.get("price") is not None:
                row["price"] = round(float(row["price"]) * rate, 4)
            if row.get("sma20") is not None:
                row["sma20"] = round(float(row["sma20"]) * rate, 4)

    def universe(self, asset_class: str = "india") -> dict:
        if asset_class == "india" or asset_class not in MULTI_ASSET_ETF_UNIVERSE:
            return {
                "asset_class": "india",
                "currency": "₹",
                "presets": {k: v for k, v in ETF_PRESETS.items()},
                "default_symbols": default_etf_universe(),
                "shop_39": ETF_SHOP_39_PRIMARY,
                "master_backup": MASTER_INDIA_ETFS,
            }
        entry = MULTI_ASSET_ETF_UNIVERSE[asset_class]
        return {
            "asset_class": asset_class,
            "currency": entry["currency"],
            "presets": dict(entry["presets"]),  # type: ignore[arg-type]
            "default_symbols": list(entry["primary"]),  # type: ignore[arg-type]
            "shop_39": list(entry["primary"]),  # type: ignore[arg-type]
            "master_backup": list(entry["master"]),  # type: ignore[arg-type]
        }

    async def scan(
        self, symbols: list[str] | None = None, exchange: str = "NSE", asset_class: str = "india",
    ) -> dict:
        syms = symbols or self._default_universe_for(asset_class)
        token = await self._groww_token()
        market, default_exchange, _currency = await self._asset_ctx(asset_class)
        ex = exchange or default_exchange

        def _run():
            set_groww_token(token)
            analyses = eng.scan_etf_universe(syms, groww_token=token, exchange=ex, market=market)
            self._convert_analyses_to_inr(analyses, asset_class)
            for row in analyses:
                sym = row.get("symbol")
                if sym:
                    row["underlying"] = self._underlying_label(asset_class, str(sym))
            return {
                "symbols": syms,
                "exchange": ex,
                "asset_class": asset_class,
                "analyses": analyses,
                "data_errors": eng.data_error_symbols(analyses),
            }

        return json_safe(await asyncio.to_thread(_run))

    async def recommend(self, payload: dict[str, Any]) -> dict:
        """Stateless what-if recommendation — portfolio supplied by the caller."""
        asset_class = str(payload.get("asset_class") or "india")
        token = await self._groww_token()
        market, default_exchange, currency = await self._asset_ctx(asset_class)
        ex = payload.get("exchange") or default_exchange
        symbols = payload.get("symbols") or self._default_universe_for(asset_class)
        portfolio = payload.get("portfolio") or []
        sip_locked = set(payload.get("sip_locked") or [])

        def _run():
            set_groww_token(token)
            analyses = eng.scan_etf_universe(symbols, groww_token=token, exchange=ex, market=market)
            self._convert_analyses_to_inr(analyses, asset_class)
            for row in analyses:
                sym = row.get("symbol")
                if sym:
                    row["underlying"] = self._underlying_label(asset_class, str(sym))

            rec = eng.daily_stf_recommendation(
                deposited_capital=float(payload.get("deposited_capital") or 500_000),
                growth_amount=float(payload.get("growth_amount") or 0),
                dividend_withdrawn=float(payload.get("dividend_withdrawn") or 0),
                portfolio=portfolio,
                analyses=analyses,
                sell_mode=payload.get("sell_mode") or "combined",
                profit_target_pct=float(payload.get("profit_target_pct") or eng.DEFAULT_PROFIT_TARGET_PCT),
                profit_target_inr=float(payload.get("profit_target_inr") or eng.DEFAULT_PROFIT_TARGET_INR),
                min_profit_inr=float(payload.get("min_profit_inr") or eng.DEFAULT_MIN_PROFIT_INR),
                slots_divisor=int(payload.get("slots_divisor") or eng.SLOTS_DIVISOR),
                sip_locked=sip_locked,
                shop_start_date=payload.get("shop_start_date"),
                prefer_sip_when_available=bool(payload.get("prefer_sip", True)),
                weakness_threshold_pct=float(
                    payload.get("averaging_trigger_pct") or eng.SIP_WEAKNESS_THRESHOLD_PCT
                ),
                currency=currency,
            )
            rec["analyses"] = analyses
            rec["symbols"] = symbols
            rec["asset_class"] = asset_class
            rec["currency"] = currency
            return rec

        return json_safe(await asyncio.to_thread(_run))

    # ── Persisted portfolio ────────────────────────────────────────────────

    def _config_to_dict(self, cfg: EtfShopConfig) -> dict[str, Any]:
        _, _, currency = (
            (GROWW_INDIA_MARKET, "NSE", "₹") if cfg.asset_class == "india"
            else (
                str(MULTI_ASSET_ETF_UNIVERSE.get(cfg.asset_class, {}).get("market", "")),
                str(MULTI_ASSET_ETF_UNIVERSE.get(cfg.asset_class, {}).get("exchange", "")),
                str(MULTI_ASSET_ETF_UNIVERSE.get(cfg.asset_class, {}).get("currency", "$")),
            )
        )
        return {
            "asset_class": cfg.asset_class,
            "currency": currency,
            "deposited_capital": cfg.deposited_capital,
            "growth_amount": cfg.growth_amount,
            "dividend_withdrawn": cfg.dividend_withdrawn,
            "shop_start_date": cfg.shop_start_date,
            "preset": cfg.preset,
            "custom_symbols": cfg.custom_symbols,
            "exchange": cfg.exchange,
            "sell_mode": cfg.sell_mode,
            "profit_target_pct": cfg.profit_target_pct,
            "profit_target_inr": cfg.profit_target_inr,
            "min_profit_inr": cfg.min_profit_inr,
            "slots_divisor": cfg.slots_divisor,
            "prefer_sip": cfg.prefer_sip,
            "averaging_trigger_pct": cfg.averaging_trigger_pct,
            "sip_locked_symbols": sorted(json.loads(cfg.sip_locked_json or "[]")),
            "notify_telegram": cfg.notify_telegram,
            "notify_email": cfg.notify_email,
        }

    def _lot_to_dict(self, lot: EtfShopLot) -> dict[str, Any]:
        return {
            "id": lot.id,
            "slot_id": str(lot.id),
            "asset_class": lot.asset_class,
            "symbol": lot.symbol,
            "purchase_price": lot.purchase_price,
            "purchase_date": lot.purchase_date,
            "amount": lot.amount,
            "quantity": lot.quantity,
            "lot_type": lot.lot_type,
            "status": lot.status,
            "closed_date": lot.closed_date,
            "sale_price": lot.sale_price,
            "sale_amount": lot.sale_amount,
            "gross_profit": lot.gross_profit,
            "net_profit": lot.net_profit,
        }

    def _resolve_symbols(self, cfg: EtfShopConfig) -> list[str]:
        if cfg.custom_symbols and cfg.custom_symbols.strip():
            return [s.strip().upper() for s in cfg.custom_symbols.replace("\n", ",").split(",") if s.strip()]
        presets = self._presets_for(cfg.asset_class)
        return presets.get(cfg.preset) or self._default_universe_for(cfg.asset_class)

    async def get_or_create_config(self, user_id: int, asset_class: str = "india") -> EtfShopConfig:
        assert self.db is not None, "EtfTaService requires a db session for persisted-portfolio methods"
        row = await self.db.execute(
            select(EtfShopConfig).where(
                EtfShopConfig.user_id == user_id, EtfShopConfig.asset_class == asset_class,
            )
        )
        cfg = row.scalar_one_or_none()
        if cfg is None:
            _market, default_exchange, _currency = await self._asset_ctx(asset_class)
            cfg = EtfShopConfig(
                user_id=user_id,
                asset_class=asset_class,
                preset=_DEFAULT_PRESET_BY_ASSET_CLASS.get(asset_class, _DEFAULT_PRESET_BY_ASSET_CLASS["india"]),
                exchange=default_exchange,
            )
            self.db.add(cfg)
            await self.db.commit()
            await self.db.refresh(cfg)
        return cfg

    async def update_config(self, user_id: int, payload: dict[str, Any], asset_class: str = "india") -> dict[str, Any]:
        cfg = await self.get_or_create_config(user_id, asset_class)
        for field in _CONFIG_FIELDS:
            if field in payload and payload[field] is not None:
                setattr(cfg, field, payload[field])
        await self.db.commit()
        await self.db.refresh(cfg)
        return self._config_to_dict(cfg)

    async def list_lots(self, user_id: int, asset_class: str = "india", status: str | None = None) -> list[dict[str, Any]]:
        stmt = select(EtfShopLot).where(EtfShopLot.user_id == user_id, EtfShopLot.asset_class == asset_class)
        if status:
            stmt = stmt.where(EtfShopLot.status == status)
        stmt = stmt.order_by(EtfShopLot.purchase_date, EtfShopLot.id)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self._lot_to_dict(r) for r in rows]

    async def portfolio(self, user_id: int, asset_class: str = "india") -> dict[str, Any]:
        """Open + closed lots, with open lots enriched with a live current price,
        %/currency profit since bought, an "eligible for profit booking" flag (reusing the
        same FIFO sell-trigger check the daily recommendation uses), and — when a
        lot's symbol has fallen past the configured averaging-down trigger — a
        suggested averaging amount (reusing the existing dynamic-SIP ranking logic)."""
        cfg = await self.get_or_create_config(user_id, asset_class)
        lots = await self.list_lots(user_id, asset_class)
        open_lots = [lot for lot in lots if lot["status"] == "open"]
        market, default_exchange, currency = await self._asset_ctx(asset_class)

        if open_lots:
            symbols = sorted({lot["symbol"] for lot in open_lots})
            token = await self._groww_token()
            ex = cfg.exchange or default_exchange
            sip_locked = set(json.loads(cfg.sip_locked_json or "[]"))
            portfolio_rows = [
                {
                    "slot_id": str(lot["id"]),
                    "symbol": lot["symbol"],
                    "purchase_price": lot["purchase_price"],
                    "purchase_date": lot["purchase_date"],
                    "amount": lot["amount"],
                    "quantity": lot["quantity"],
                    "status": lot["status"],
                }
                for lot in open_lots
            ]

            def _run():
                set_groww_token(token)
                analyses = eng.scan_etf_universe(symbols, groww_token=token, exchange=ex, market=market)
                self._convert_analyses_to_inr(analyses, asset_class)
                price_map = {a["symbol"]: a.get("price") for a in analyses if a.get("price")}

                sells = eng.sell_candidates_fifo(
                    portfolio_rows,
                    analyses,
                    sell_mode=cfg.sell_mode,
                    profit_target_pct=cfg.profit_target_pct,
                    profit_target_inr=cfg.profit_target_inr,
                    min_profit_inr=cfg.min_profit_inr,
                    currency=currency,
                )
                eligible_by_slot = {s["slot_id"]: s for s in sells}

                locked = eng.update_sip_locked_symbols(
                    portfolio_rows, analyses, sip_locked,
                    weakness_threshold_pct=cfg.averaging_trigger_pct,
                )
                sip_candidates = eng.rank_sip_candidates(portfolio_rows, analyses, locked)
                averaging_by_symbol = {c["symbol"]: c for c in sip_candidates}
                return price_map, eligible_by_slot, averaging_by_symbol

            price_map, eligible_by_slot, averaging_by_symbol = await asyncio.to_thread(_run)

            for lot in open_lots:
                price = price_map.get(lot["symbol"])
                buy_px = float(lot["purchase_price"] or 0)
                lot["current_price"] = price
                if price is not None and buy_px > 0:
                    profit_pct = (float(price) - buy_px) / buy_px * 100.0
                    lot["profit_since_bought_pct"] = round(profit_pct, 2)
                    lot["profit_since_bought_inr"] = round(
                        (float(price) - buy_px) * float(lot["quantity"] or 0), 2
                    )
                else:
                    lot["profit_since_bought_pct"] = None
                    lot["profit_since_bought_inr"] = None

                elig = eligible_by_slot.get(str(lot["id"]))
                lot["eligible_for_profit_booking"] = bool(elig)
                lot["profit_booking_reason"] = elig["reason"] if elig else None

                avg = averaging_by_symbol.get(lot["symbol"])
                if avg:
                    lot["averaging_suggested"] = True
                    lot["averaging_fall_from_last_buy_pct"] = avg.get("fall_from_last_buy_pct")
                    lot["averaging_amount"] = avg.get("sip_amount")
                    fall = avg.get("fall_from_last_buy_pct") or 0.0
                    amt = avg.get("sip_amount") or 0.0
                    invested = avg.get("total_invested") or 0.0
                    lot["averaging_reason"] = (
                        f"{lot['symbol']} has fallen {fall:.2f}% below your last buy price — past the "
                        f"{cfg.averaging_trigger_pct:.1f}% averaging-down trigger. Strategy suggests averaging "
                        f"with ~{currency}{amt:,.0f} (10% of {currency}{invested:,.0f} already invested in this ETF)."
                    )
                else:
                    lot["averaging_suggested"] = False
                    lot["averaging_fall_from_last_buy_pct"] = None
                    lot["averaging_amount"] = None
                    lot["averaging_reason"] = None

        return {"config": self._config_to_dict(cfg), "lots": lots}

    async def add_lot(
        self,
        user_id: int,
        *,
        symbol: str,
        price: float,
        amount: float,
        lot_type: str = "standard",
        purchase_date: str | None = None,
        asset_class: str = "india",
    ) -> dict[str, Any]:
        if not symbol.strip():
            raise ValueError("Symbol is required")
        if price <= 0:
            raise ValueError("Buy price must be > 0")
        if amount <= 0:
            raise ValueError("Amount must be > 0")

        qty = amount / price
        pdate = purchase_date or datetime.now().strftime("%Y-%m-%d")
        lot = EtfShopLot(
            user_id=user_id,
            asset_class=asset_class,
            symbol=symbol.upper().strip(),
            purchase_price=round(float(price), 4),
            purchase_date=pdate,
            amount=round(float(amount), 2),
            quantity=round(qty, 4),
            lot_type=lot_type,
            status="open",
        )
        self.db.add(lot)

        cfg = await self.get_or_create_config(user_id, asset_class)
        if not cfg.shop_start_date:
            cfg.shop_start_date = pdate

        await self.db.commit()
        await self.db.refresh(lot)
        return self._lot_to_dict(lot)

    async def close_lot(
        self,
        user_id: int,
        lot_id: int,
        *,
        sale_price: float,
        sale_date: str | None = None,
        dividend_pct: float = 0.0,
    ) -> dict[str, Any]:
        """Book a FIFO sell — records real sale price/profit and feeds the
        realized gain back into the capital pool (growth reinvested vs
        personal dividend draw), so the shop actually compounds."""
        if sale_price <= 0:
            raise ValueError("Sale price must be > 0")

        lot = await self.db.get(EtfShopLot, lot_id)
        if lot is None or lot.user_id != user_id:
            raise ValueError("Lot not found")
        if lot.status == "closed":
            raise ValueError("Lot already closed")

        sale_amount = round(float(sale_price) * lot.quantity, 2)
        gross_profit = round(sale_amount - lot.amount, 2)
        net = eng.net_profit_after_costs(gross_profit, sale_amount=sale_amount)

        lot.status = "closed"
        lot.closed_date = sale_date or datetime.now().strftime("%Y-%m-%d")
        lot.sale_price = round(float(sale_price), 4)
        lot.sale_amount = sale_amount
        lot.gross_profit = gross_profit
        lot.net_profit = net["net_profit"]

        split = eng.split_profit_reinvestment(net["net_profit"], dividend_pct)
        cfg = await self.get_or_create_config(user_id, lot.asset_class)
        cfg.growth_amount = round(cfg.growth_amount + split["growth_add"], 2)
        if split["dividend"]:
            cfg.dividend_withdrawn = round(cfg.dividend_withdrawn + split["dividend"], 2)

        await self.db.commit()
        await self.db.refresh(lot)
        out = self._lot_to_dict(lot)
        out["net_after_costs"] = net
        out["reinvest_split"] = split
        return out

    async def daily(self, user_id: int, asset_class: str = "india") -> dict[str, Any]:
        """Run today's buy/sell recommendation from the persisted config + lot
        ledger (no client-shuttled portfolio needed) and latch any newly-triggered
        SIP-locked symbols back into the config. Closed lots are included too —
        the engine's own open/closed filters need both for FIFO sell candidates
        (open) and the realized-profit summary (closed) to work correctly."""
        cfg = await self.get_or_create_config(user_id, asset_class)
        lots = await self.list_lots(user_id, asset_class)
        portfolio = [
            {
                "slot_id": str(lot["id"]),
                "symbol": lot["symbol"],
                "purchase_price": lot["purchase_price"],
                "purchase_date": lot["purchase_date"],
                "amount": lot["amount"],
                "quantity": lot["quantity"],
                "status": lot["status"],
                "lot_type": lot["lot_type"],
                "gross_profit": lot["gross_profit"],
                "net_profit": lot["net_profit"],
                "sale_amount": lot["sale_amount"],
            }
            for lot in lots
        ]
        symbols = self._resolve_symbols(cfg)
        token = await self._groww_token()
        market, default_exchange, currency = await self._asset_ctx(asset_class)
        ex = cfg.exchange or default_exchange
        sip_locked = set(json.loads(cfg.sip_locked_json or "[]"))

        def _run():
            set_groww_token(token)
            analyses = eng.scan_etf_universe(symbols, groww_token=token, exchange=ex, market=market)
            self._convert_analyses_to_inr(analyses, asset_class)
            for row in analyses:
                sym = row.get("symbol")
                if sym:
                    row["underlying"] = self._underlying_label(asset_class, str(sym))

            rec = eng.daily_stf_recommendation(
                deposited_capital=cfg.deposited_capital,
                growth_amount=cfg.growth_amount,
                dividend_withdrawn=cfg.dividend_withdrawn,
                portfolio=portfolio,
                analyses=analyses,
                sell_mode=cfg.sell_mode,
                profit_target_pct=cfg.profit_target_pct,
                profit_target_inr=cfg.profit_target_inr,
                min_profit_inr=cfg.min_profit_inr,
                slots_divisor=cfg.slots_divisor,
                sip_locked=sip_locked,
                shop_start_date=cfg.shop_start_date,
                prefer_sip_when_available=cfg.prefer_sip,
                weakness_threshold_pct=cfg.averaging_trigger_pct,
                currency=currency,
            )
            rec["analyses"] = analyses
            rec["symbols"] = symbols
            rec["asset_class"] = asset_class
            rec["currency"] = currency
            return rec

        rec = json_safe(await asyncio.to_thread(_run))

        new_locked = set(rec.get("sip_locked_symbols") or [])
        if new_locked != sip_locked:
            cfg.sip_locked_json = json.dumps(sorted(new_locked))
            await self.db.commit()

        return rec

    def etf_28_sma_universe(self) -> dict[str, Any]:
        from app.etf_ta.etf_28_sma_engine import universe_payload

        return universe_payload()

    async def etf_28_sma_scan(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.etf_ta.etf_28_sma_engine import (
            ETF_28_SMA_AI_SYSTEM,
            Etf28SmaConfig,
            build_etf_28_sma_ai_prompt,
            parse_holdings,
            scan_universe,
        )
        from app.etf_ta.etf_28_sma_universe import ETF_28_SMA_PRESETS, fire_28_sma_symbols

        token = await self._groww_token()
        preset = payload.get("preset")
        tickers = list(payload.get("tickers") or [])
        if not tickers and preset and preset in ETF_28_SMA_PRESETS:
            tickers = list(ETF_28_SMA_PRESETS[preset])
        if not tickers:
            tickers = fire_28_sma_symbols()

        asset_class = str(
            payload.get("asset_class")
            or preset_asset_class(str(preset) if preset else None, tickers=tickers)
            or "india"
        )
        market, default_exchange, _currency = await self._asset_ctx(asset_class)
        exchange = str(payload.get("exchange") or default_exchange or await self._exchange() or "NSE")

        cfg = Etf28SmaConfig(
            total_capital=float(payload.get("total_capital") or 500_000),
            averaging_reserve_pct=float(payload.get("averaging_reserve_pct") or 30),
            max_etfs=int(payload.get("max_etfs") or 20),
            max_new_buys_per_day=int(payload.get("max_new_buys_per_day") or 4),
            sell_mode=payload.get("sell_mode") or "FIFO",  # type: ignore[arg-type]
            capital_exhausted=bool(payload.get("capital_exhausted")),
            profit_target_pct=float(payload.get("profit_target_pct") or 3.14),
            avg_min_drop_pct=float(payload.get("avg_min_drop_pct") or 5.0),
            fast_momentum_pct=float(payload.get("fast_momentum_pct") or 18.0),
            lookback_bars=int(payload.get("lookback_bars") or 400),
        )
        holdings = parse_holdings(payload.get("holdings"))

        def _run():
            set_groww_token(token)
            return scan_universe(
                tickers,
                cfg=cfg,
                groww_token=token,
                exchange=exchange,
                market=market,
                holdings=holdings,
            )

        out = json_safe(await asyncio.to_thread(_run))
        for r in out.get("results") or []:
            if isinstance(r, dict) and not r.get("error"):
                r["ai_context"] = build_etf_28_sma_ai_prompt(r)
        out["ai_system_prompt"] = ETF_28_SMA_AI_SYSTEM
        out["preset"] = preset
        out["asset_class"] = asset_class
        out["market"] = market
        return out

    def etf_top_down_universe(self) -> dict[str, Any]:
        from app.etf_ta.etf_top_down_engine import universe_payload

        return universe_payload()

    async def etf_top_down_scan(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.etf_ta.etf_top_down_engine import (
            ETF_TOP_DOWN_AI_SYSTEM,
            EtfTopDownConfig,
            build_etf_top_down_ai_prompt,
            scan_universe,
            universe_payload,
        )

        token = await self._groww_token()
        preset = payload.get("preset")
        tickers = list(payload.get("tickers") or [])
        uni = universe_payload()
        presets = uni.get("presets") or {}
        if not tickers and preset and preset in presets:
            tickers = list(presets[preset])
        if not tickers:
            tickers = list(uni.get("default_symbols") or [])

        asset_class = str(
            payload.get("asset_class")
            or preset_asset_class(str(preset) if preset else None, tickers=tickers)
            or "india"
        )
        market, default_exchange, _currency = await self._asset_ctx(asset_class)
        exchange = str(payload.get("exchange") or default_exchange or await self._exchange() or "NSE")

        cfg = EtfTopDownConfig(
            top_n=int(payload.get("top_n") or 20),
            renko_box_pct=float(payload.get("renko_box_pct") or 1.0),
            pn_f_box_pct=float(payload.get("pn_f_box_pct") or 0.25),
            d_smart_period=int(payload.get("d_smart_period") or 10),
            lookback_bars=int(payload.get("lookback_bars") or 400),
            max_etfs_hold=int(payload.get("max_etfs_hold") or 10),
        )

        def _run():
            set_groww_token(token)
            return scan_universe(
                tickers,
                cfg=cfg,
                groww_token=token,
                exchange=exchange,
                market=market,
            )

        out = json_safe(await asyncio.to_thread(_run))
        for r in out.get("results") or []:
            if isinstance(r, dict) and not r.get("error"):
                r["ai_context"] = build_etf_top_down_ai_prompt(r)
        out["ai_system_prompt"] = ETF_TOP_DOWN_AI_SYSTEM
        out["preset"] = preset
        out["asset_class"] = asset_class
        out["market"] = market
        return out
