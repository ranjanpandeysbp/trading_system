"""
mf_fire_engine.py
-----------------
MF FIRE planner — Mutual Funds path to Financial Independence / Retire Early.

Source: https://www.youtube.com/watch?v=HmW6T6i2Okc&t=6s
("He Became Financially Free at 38 With Mutual Funds. Here’s How")

Core principles from the video (education / research only — not advice):
  1. 25× annual expenses = FI benchmark; ~35× for a longer inflation-aware runway
  2. 1% rule — portfolio large enough that a 1% up-day ≈ monthly salary
  3. Prefer mutual funds over direct stock picking / trading
  4. 100% equity in accumulation until a sizable corpus (e.g. ₹2–5 Cr)
  5. Power through the first ₹1 Cr (hardest mile)
  6. Don't rush to pre-close low-interest debt (e.g. home loan) if it starves compounding
  7. Retirement before kids' education as #1 capital priority
  8. Maximise peak earning years (~35–40) + dual income into SIPs

Research / education only — not financial advice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

YOUTUBE_URL = "https://www.youtube.com/watch?v=HmW6T6i2Okc&t=6s"
STRATEGY_ID = "mf_fire"
STRATEGY_NAME = "MF FIRE"

CRORE = 10_000_000.0

HOW_IT_WORKS = """
### How MF FIRE works (from the video)

**1. The 25× framework**  
Financial independence ≈ **25 × annual expenses**. That corpus is meant to fund retirement /
give you the confidence to take career risks. Around **35×**, with ~6–7% inflation and a
conservative withdrawal rate, the portfolio can last 50+ years more comfortably.

**2. The 1% rule (psychological confidence)**  
Grow the portfolio until a **1% market move ≈ one month of salary**. If you work ~200 hours for
that salary, watching wealth earn it in a day shows capital is doing the heavy lifting.

**3. Mutual funds over direct stocks / trading**  
After stock losses (e.g. DHFL) and blue-chip underperformance vs FDs, the speaker moved to
**~98–99% mutual funds** (mainly mid/small-cap). Outsource stock-picking stress to fund managers.
Trading is framed as a “quick money scheme” that is injurious to wealth.

**4. 100% equity while accumulating**  
Traditional debt/gold mixes preserve wealth; they don’t create it as fast. Until a sizable corpus
(e.g. **₹2–5 Cr**), stay **100% equity** via MFs to maximise compounding.

**5. First ₹1 Cr is the hardest**  
It took ~8 years to the first crore, then ~2 years to the second — compounding + higher SIPs.

**6. Don’t blindly pre-close low-interest home loans**  
Diverting every rupee to prepay can delay the first crore and starve compounding if the loan
rate is well below expected equity MF returns.

**7. Retirement first**  
You can loan for a child’s education; nobody loans you a retirement. Make FI corpus priority #1.

**8. Peak earning years (~35–40)**  
Aggressively raise income (promotions, dual income) and pump surplus into SIPs.

Use this planner to size your 25×/35× number, 1% confidence portfolio, crore milestones, and
SIP runway — then pick schemes via **Best MF**. Not financial advice.
""".strip()

PRINCIPLES = [
    {
        "id": "25x",
        "title": "25× Framework",
        "summary": "FI corpus ≈ 25 × annual expenses; 35× for a longer inflation-aware runway.",
    },
    {
        "id": "one_pct",
        "title": "1% Rule",
        "summary": "Portfolio where a 1% up-move equals your monthly salary — wealth does the heavy lifting.",
    },
    {
        "id": "mf_not_stocks",
        "title": "Mutual Funds over Direct Stocks",
        "summary": "Outsource picking to fund managers; avoid trading as a wealth shortcut.",
    },
    {
        "id": "full_equity",
        "title": "100% Equity in Accumulation",
        "summary": "Asset allocation preserves wealth; equity compounds it until a sizable corpus.",
    },
    {
        "id": "first_crore",
        "title": "Power Through the First ₹1 Cr",
        "summary": "Hardest milestone — patience + rising SIPs unlock the second crore faster.",
    },
    {
        "id": "home_loan",
        "title": "Don’t Pre-Close Low-Interest Debt Blindly",
        "summary": "Prepaying a cheap home loan can delay compounding if it starves MF SIPs.",
    },
    {
        "id": "retirement_first",
        "title": "Retirement Is Priority #1",
        "summary": "Fund FI before kids’ education corpus — education can be loaned; retirement cannot.",
    },
    {
        "id": "peak_years",
        "title": "Capitalise on Peak Earning Years",
        "summary": "Ages ~35–40: raise income hard and route surplus into equity MFs.",
    },
]


@dataclass
class MfFireConfig:
    annual_expenses: float = 600_000.0
    monthly_salary: float = 100_000.0
    current_corpus: float = 0.0
    monthly_sip: float = 25_000.0
    expected_equity_return_pct: float = 12.0
    inflation_pct: float = 6.5
    fire_multiple: float = 25.0
    long_runway_multiple: float = 35.0
    equity_only_until_cr: float = 3.0  # ₹ Cr — stay 100% equity until this corpus
    age: int | None = 35
    home_loan_balance: float = 0.0
    home_loan_rate_pct: float = 8.5
    extra_emi_toward_loan: float = 0.0  # monthly amount considered for prepay vs SIP
    dual_income: bool = False
    principles_checklist: list[str] = field(default_factory=list)


def _round_money(x: float) -> float:
    return round(float(x), 2)


def _fmt_inr(x: float) -> str:
    return f"₹{x:,.0f}"


def _fmt_cr(x: float) -> str:
    return f"₹{x / CRORE:,.2f} Cr"


def _months_to_target(
    *,
    present: float,
    monthly_sip: float,
    annual_return_pct: float,
    target: float,
    max_months: int = 600,
) -> dict[str, Any]:
    """Solve months to reach target with monthly compounding SIP."""
    if target <= 0:
        return {"months": 0, "years": 0.0, "reachable": True, "note": "Target already met or zero."}
    if present >= target:
        return {"months": 0, "years": 0.0, "reachable": True, "note": "Already at or above target."}

    r = annual_return_pct / 100.0 / 12.0
    p = max(0.0, present)
    pmt = max(0.0, monthly_sip)

    if pmt <= 0 and (r <= 0 or p <= 0):
        return {
            "months": None,
            "years": None,
            "reachable": False,
            "note": "Need a monthly SIP (or existing corpus growing) to reach this target.",
        }

    if r <= 0:
        # Linear accumulation only
        if pmt <= 0:
            return {"months": None, "years": None, "reachable": False, "note": "Zero return and no SIP."}
        need = target - p
        months = int(math.ceil(need / pmt))
        return {
            "months": months,
            "years": round(months / 12.0, 2),
            "reachable": months <= max_months,
            "note": "Assumes 0% return (linear SIP only).",
        }

    # Closed form: FV = P(1+r)^n + PMT*((1+r)^n - 1)/r
    # (1+r)^n = (FV*r + PMT) / (P*r + PMT)
    numer = target * r + pmt
    denom = p * r + pmt
    if denom <= 0 or numer / denom <= 1:
        # Fall back to iteration
        bal = p
        for m in range(1, max_months + 1):
            bal = bal * (1 + r) + pmt
            if bal >= target:
                return {"months": m, "years": round(m / 12.0, 2), "reachable": True, "note": None}
        return {
            "months": None,
            "years": None,
            "reachable": False,
            "note": f"Not reachable within {max_months // 12} years at current SIP / return.",
        }

    n = math.log(numer / denom) / math.log(1 + r)
    months = int(math.ceil(n))
    if months < 0:
        months = 0
    if months > max_months:
        return {
            "months": months,
            "years": round(months / 12.0, 2),
            "reachable": False,
            "note": f"Would take ~{months / 12:.1f} years — raise SIP or return assumptions.",
        }
    return {"months": months, "years": round(months / 12.0, 2), "reachable": True, "note": None}


def _project_corpus(
    *,
    present: float,
    monthly_sip: float,
    annual_return_pct: float,
    years: int,
) -> list[dict[str, Any]]:
    r = annual_return_pct / 100.0 / 12.0
    bal = max(0.0, present)
    pmt = max(0.0, monthly_sip)
    out: list[dict[str, Any]] = []
    for y in range(1, max(1, years) + 1):
        for _ in range(12):
            bal = bal * (1 + r) + pmt if r > 0 else bal + pmt
        out.append({
            "year": y,
            "corpus": _round_money(bal),
            "corpus_cr": round(bal / CRORE, 4),
            "label": _fmt_cr(bal),
        })
    return out


def _home_loan_vs_sip(
    *,
    extra_monthly: float,
    loan_rate_pct: float,
    equity_return_pct: float,
    years: int = 10,
) -> dict[str, Any] | None:
    if extra_monthly <= 0:
        return None
    # Rough side-by-side: investing the same monthly amount in equity MF vs "saving" interest
    # by prepaying (interest avoided ≈ loan_rate on prepaid principal path — simplified).
    eq = _project_corpus(
        present=0.0,
        monthly_sip=extra_monthly,
        annual_return_pct=equity_return_pct,
        years=years,
    )
    loan_side = _project_corpus(
        present=0.0,
        monthly_sip=extra_monthly,
        annual_return_pct=loan_rate_pct,
        years=years,
    )
    eq_end = eq[-1]["corpus"] if eq else 0.0
    loan_end = loan_side[-1]["corpus"] if loan_side else 0.0
    edge = eq_end - loan_end
    return {
        "horizon_years": years,
        "extra_monthly": _round_money(extra_monthly),
        "equity_mf_future_value": _round_money(eq_end),
        "loan_rate_equivalent_fv": _round_money(loan_end),
        "equity_edge": _round_money(edge),
        "plain_english": (
            f"If you divert {_fmt_inr(extra_monthly)}/mo for {years} years: "
            f"equity MF path ≈ {_fmt_inr(eq_end)}; "
            f"same cash “earning” at loan rate {loan_rate_pct:.1f}% ≈ {_fmt_inr(loan_end)}. "
            + (
                f"Equity edge ≈ {_fmt_inr(edge)} — video bias: don’t starve SIPs to prepay a cheap loan."
                if edge > 0
                else f"Loan-rate path leads by {_fmt_inr(abs(edge))} — prepay may win if equity assumptions are lower."
            )
        ),
    }


def plan_mf_fire(cfg: MfFireConfig | None = None) -> dict[str, Any]:
    cfg = cfg or MfFireConfig()
    annual_exp = max(0.0, float(cfg.annual_expenses))
    monthly_sal = max(0.0, float(cfg.monthly_salary))
    corpus = max(0.0, float(cfg.current_corpus))
    sip = max(0.0, float(cfg.monthly_sip))
    ret = float(cfg.expected_equity_return_pct)
    infl = float(cfg.inflation_pct)
    m25 = max(1.0, float(cfg.fire_multiple))
    m35 = max(m25, float(cfg.long_runway_multiple))

    fire_25 = annual_exp * m25
    fire_35 = annual_exp * m35
    # Safe withdrawal rough: 4% rule ↔ 25×; show annual withdraw capacity at 4%
    withdraw_4pct = fire_25 * 0.04

    one_pct_target = monthly_sal * 100.0  # 1% of P = monthly salary
    one_pct_today = corpus * 0.01

    gap_25 = max(0.0, fire_25 - corpus)
    gap_35 = max(0.0, fire_35 - corpus)
    gap_one_pct = max(0.0, one_pct_target - corpus)

    progress_25 = min(100.0, (corpus / fire_25 * 100.0) if fire_25 > 0 else 0.0)
    progress_35 = min(100.0, (corpus / fire_35 * 100.0) if fire_35 > 0 else 0.0)
    progress_one_pct = min(100.0, (corpus / one_pct_target * 100.0) if one_pct_target > 0 else 0.0)

    first_cr = CRORE
    second_cr = 2 * CRORE
    to_first = _months_to_target(present=corpus, monthly_sip=sip, annual_return_pct=ret, target=first_cr)
    to_second = _months_to_target(present=corpus, monthly_sip=sip, annual_return_pct=ret, target=second_cr)
    to_fire_25 = _months_to_target(present=corpus, monthly_sip=sip, annual_return_pct=ret, target=fire_25)
    to_fire_35 = _months_to_target(present=corpus, monthly_sip=sip, annual_return_pct=ret, target=fire_35)
    to_one_pct = _months_to_target(present=corpus, monthly_sip=sip, annual_return_pct=ret, target=one_pct_target)

    equity_until = float(cfg.equity_only_until_cr) * CRORE
    equity_phase = corpus < equity_until
    allocation = {
        "mode": "100% equity (accumulation)" if equity_phase else "Consider introducing preservation sleeve",
        "equity_pct_suggested": 100 if equity_phase else 70,
        "debt_gold_pct_suggested": 0 if equity_phase else 30,
        "threshold_cr": float(cfg.equity_only_until_cr),
        "plain_english": (
            f"Corpus {_fmt_cr(corpus)} is below the {_fmt_cr(equity_until)} accumulation threshold — "
            "video guidance: stay 100% equity mutual funds to maximise compounding."
            if equity_phase
            else (
                f"Corpus {_fmt_cr(corpus)} is at/above ~{_fmt_cr(equity_until)}. "
                "Video: asset allocation matters more for *preserving* wealth after a sizable corpus — "
                "consider adding debt/gold only when protecting FI, not while still creating it."
            )
        ),
    }

    age = cfg.age
    peak = {
        "in_peak_band": age is not None and 35 <= int(age) <= 40,
        "age": age,
        "dual_income": bool(cfg.dual_income),
        "plain_english": (
            "You are in the video’s peak earning window (~35–40) — push income and SIP hard."
            if age is not None and 35 <= int(age) <= 40
            else (
                "Approaching peak earning years — build SIP muscle and income trajectory now."
                if age is not None and int(age) < 35
                else "Past the classic 35–40 peak band — still compound aggressively; raise SIP with every hike."
                if age is not None
                else "Set your age to personalise peak-earning guidance."
            )
        ),
        "actions": [
            "Increase SIP on every salary hike (pay yourself first).",
            "Prefer equity mutual funds over stock trading for sleep-well compounding.",
            "Keep retirement / FI SIP as priority #1 before discretionary goals.",
            *(["Leverage dual income — route second surplus fully into SIPs."] if cfg.dual_income else []),
        ],
    }

    loan_cmp = _home_loan_vs_sip(
        extra_monthly=float(cfg.extra_emi_toward_loan or 0),
        loan_rate_pct=float(cfg.home_loan_rate_pct),
        equity_return_pct=ret,
        years=10,
    )

    projection_years = 15
    projection = _project_corpus(
        present=corpus, monthly_sip=sip, annual_return_pct=ret, years=projection_years,
    )

    status = "ACCUMULATING"
    if corpus >= fire_35:
        status = "LONG_RUNWAY_FI"
    elif corpus >= fire_25:
        status = "FI_25X"
    elif corpus >= first_cr:
        status = "PAST_FIRST_CRORE"

    checklist = []
    for p in PRINCIPLES:
        checklist.append({
            **p,
            "checked": p["id"] in (cfg.principles_checklist or []),
        })

    scorecard = [
        {
            "id": "fire_25x",
            "label": f"{m25:.0f}× FIRE number",
            "target": _round_money(fire_25),
            "target_label": _fmt_inr(fire_25),
            "gap": _round_money(gap_25),
            "progress_pct": round(progress_25, 1),
            "eta": to_fire_25,
        },
        {
            "id": "fire_35x",
            "label": f"{m35:.0f}× long runway",
            "target": _round_money(fire_35),
            "target_label": _fmt_inr(fire_35),
            "gap": _round_money(gap_35),
            "progress_pct": round(progress_35, 1),
            "eta": to_fire_35,
        },
        {
            "id": "one_pct_rule",
            "label": "1% rule portfolio",
            "target": _round_money(one_pct_target),
            "target_label": _fmt_inr(one_pct_target),
            "gap": _round_money(gap_one_pct),
            "progress_pct": round(progress_one_pct, 1),
            "eta": to_one_pct,
        },
        {
            "id": "first_crore",
            "label": "First ₹1 Cr",
            "target": _round_money(first_cr),
            "target_label": _fmt_cr(first_cr),
            "gap": _round_money(max(0.0, first_cr - corpus)),
            "progress_pct": round(min(100.0, corpus / first_cr * 100.0), 1),
            "eta": to_first,
        },
        {
            "id": "second_crore",
            "label": "Second ₹1 Cr (₹2 Cr total)",
            "target": _round_money(second_cr),
            "target_label": _fmt_cr(second_cr),
            "gap": _round_money(max(0.0, second_cr - corpus)),
            "progress_pct": round(min(100.0, corpus / second_cr * 100.0), 1),
            "eta": to_second,
        },
    ]

    plain = (
        f"Status: {status.replace('_', ' ')}. "
        f"Your {m25:.0f}× FI number is {_fmt_inr(fire_25)} "
        f"({progress_25:.0f}% there; gap {_fmt_inr(gap_25)}). "
        f"1% rule target portfolio {_fmt_inr(one_pct_target)} "
        f"(today 1% of corpus ≈ {_fmt_inr(one_pct_today)} vs monthly salary {_fmt_inr(monthly_sal)}). "
    )
    if to_fire_25.get("reachable") and to_fire_25.get("years") is not None:
        plain += f"At SIP {_fmt_inr(sip)}/mo and {ret:.1f}% assumed return, ~{to_fire_25['years']} years to {m25:.0f}×. "
    plain += "Prefer equity mutual funds; avoid trading shortcuts. Research only — not advice."

    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "how_it_works": HOW_IT_WORKS,
        "principles": PRINCIPLES,
        "checklist": checklist,
        "status": status,
        "plain_english": plain,
        "inputs": {
            "annual_expenses": _round_money(annual_exp),
            "monthly_salary": _round_money(monthly_sal),
            "current_corpus": _round_money(corpus),
            "monthly_sip": _round_money(sip),
            "expected_equity_return_pct": ret,
            "inflation_pct": infl,
            "fire_multiple": m25,
            "long_runway_multiple": m35,
            "equity_only_until_cr": float(cfg.equity_only_until_cr),
            "age": age,
            "home_loan_balance": _round_money(float(cfg.home_loan_balance or 0)),
            "home_loan_rate_pct": float(cfg.home_loan_rate_pct),
            "extra_emi_toward_loan": _round_money(float(cfg.extra_emi_toward_loan or 0)),
            "dual_income": bool(cfg.dual_income),
        },
        "fire": {
            "annual_expenses": _round_money(annual_exp),
            "multiple_25": m25,
            "multiple_35": m35,
            "corpus_25x": _round_money(fire_25),
            "corpus_35x": _round_money(fire_35),
            "corpus_25x_cr": round(fire_25 / CRORE, 4),
            "corpus_35x_cr": round(fire_35 / CRORE, 4),
            "gap_25x": _round_money(gap_25),
            "gap_35x": _round_money(gap_35),
            "progress_25x_pct": round(progress_25, 1),
            "progress_35x_pct": round(progress_35, 1),
            "annual_withdraw_4pct_at_25x": _round_money(withdraw_4pct),
            "inflation_note": (
                f"Video cites ~{infl:.1f}% inflation context for long-runway sizing — "
                "raise the multiple (toward 35×) if you want a thicker buffer."
            ),
        },
        "one_percent_rule": {
            "monthly_salary": _round_money(monthly_sal),
            "target_portfolio": _round_money(one_pct_target),
            "target_portfolio_cr": round(one_pct_target / CRORE, 4),
            "one_pct_of_corpus_today": _round_money(one_pct_today),
            "gap": _round_money(gap_one_pct),
            "progress_pct": round(progress_one_pct, 1),
            "hours_worked_proxy": 200,
            "plain_english": (
                f"1% of {_fmt_inr(one_pct_target)} = {_fmt_inr(monthly_sal)} (one month’s salary). "
                f"Today, 1% of your corpus is {_fmt_inr(one_pct_today)}."
            ),
        },
        "milestones": {
            "first_crore": {
                "target": first_cr,
                "remaining": _round_money(max(0.0, first_cr - corpus)),
                "eta": to_first,
                "done": corpus >= first_cr,
            },
            "second_crore": {
                "target": second_cr,
                "remaining": _round_money(max(0.0, second_cr - corpus)),
                "eta": to_second,
                "done": corpus >= second_cr,
            },
        },
        "scorecard": scorecard,
        "allocation": allocation,
        "peak_earning_years": peak,
        "home_loan_vs_sip": loan_cmp,
        "projection": {
            "years": projection_years,
            "annual_return_pct": ret,
            "monthly_sip": _round_money(sip),
            "series": projection,
        },
        "next_steps": [
            {
                "title": "Lock your FI number",
                "detail": f"Treat {_fmt_inr(fire_25)} as the minimum FI corpus; stretch to {_fmt_inr(fire_35)} for longevity.",
            },
            {
                "title": "Automate equity MF SIPs",
                "detail": "Route surplus into diversified equity mutual funds — use Best MF to shortlist schemes.",
                "link": "/best-mf",
            },
            {
                "title": "Protect the first crore focus",
                "detail": "Avoid trading and don’t starve SIPs to prepay cheap loans until the compounding engine is humming.",
            },
            {
                "title": "Retirement before education corpus",
                "detail": "Keep FI SIP sacred; education can use loans later — retirement cannot.",
            },
        ],
        "links": [
            {"label": "Best MF (rank schemes)", "to": "/best-mf"},
            {"label": "Investing Agent (FA)", "to": "/investing-agent"},
            {"label": "Strategy video", "href": YOUTUBE_URL},
        ],
        "disclaimer": (
            "Research / education only — not financial advice. Returns are assumed, not guaranteed. "
            "Mutual fund investments are subject to market risks."
        ),
        "ai_context": plain,
    }


def build_mf_fire_ai_prompt(result: dict[str, Any]) -> str:
    fire = result.get("fire") or {}
    one = result.get("one_percent_rule") or {}
    return "\n".join([
        "MF FIRE planner result (mutual-fund financial independence framework).",
        f"Status: {result.get('status')}",
        f"Plain English: {result.get('plain_english')}",
        f"25× corpus: {fire.get('corpus_25x')} | 35×: {fire.get('corpus_35x')}",
        f"1% rule target: {one.get('target_portfolio')}",
        f"Allocation: {result.get('allocation')}",
        f"Milestones: {result.get('milestones')}",
        "Advise using mutual funds for accumulation; discourage speculative trading.",
        "Remind: not financial advice.",
    ])
