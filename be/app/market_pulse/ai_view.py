from contextlib import nullcontext
"""
Shared AI View helpers for TrueBacktester tabs.
Provider config, API calls, and theme-friendly report rendering.
"""

import re
from groq import Groq

from app.market_pulse.env_config import (
    api_key_env_hint,
    default_ai_provider,
    default_ai_provider_index,
    get_api_key_for_provider,
    get_gemini_api_key,
    get_gemini_model,
    get_groq_model,
)
from app.market_pulse.ask_ai_context import get_ask_ai_context, sync_ask_ai_context

try:
    from google import genai as genai_new
    GENAI_NEW = True
except ImportError:
    try:
        import google.generativeai as genai
        GENAI_NEW = False
    except ImportError:
        GENAI_NEW = False
        genai = None

AI_PROVIDER_OPTIONS = ["Google Gemini", "Groq (LLaMA)", "Claude (Azure)", "OpenAI (Azure)", "Investing Agent", "Custom / Other"]
SUPPORTED_AI_PROVIDERS = ["Google Gemini", "Groq (LLaMA)", "Claude (Azure)", "OpenAI (Azure)", "Investing Agent"]
DEFAULT_AI_PROVIDER_INDEX = default_ai_provider_index()

GROQ_MODEL_OPTIONS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]

GEMINI_MODEL_OPTIONS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-flash-live-preview",
    "gemini-3-flash-preview",
]

_SHARED_PROVIDER_KEY = "shared_ai_provider"
_SHARED_GROQ_MODEL_KEY = "shared_groq_model"
_SHARED_GEMINI_MODEL_KEY = "shared_gemini_model"
_SHARED_AI_VERSION = "shared_ai_version"


def _prefix_ai_keys(key_prefix: str) -> tuple[str, str, str]:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", key_prefix or "global")
    return (
        f"{safe}_ai_provider",
        f"{safe}_ai_groq_model",
        f"{safe}_ai_gemini_model",
    )


def _init_shared_ai_state() -> None:
    if _SHARED_PROVIDER_KEY not in st.session_state:
        st.session_state[_SHARED_PROVIDER_KEY] = default_ai_provider()
    if _SHARED_GROQ_MODEL_KEY not in st.session_state:
        st.session_state[_SHARED_GROQ_MODEL_KEY] = get_groq_model()
    if _SHARED_GEMINI_MODEL_KEY not in st.session_state:
        st.session_state[_SHARED_GEMINI_MODEL_KEY] = get_gemini_model()


def _sync_prefix_to_shared(key_prefix: str) -> None:
    """Persist this section's widget values to the global AI selection."""
    pk, gk, mk = _prefix_ai_keys(key_prefix)
    provider = st.session_state.get(pk, default_ai_provider())
    st.session_state[_SHARED_PROVIDER_KEY] = provider
    if provider == "Groq (LLaMA)":
        st.session_state[_SHARED_GROQ_MODEL_KEY] = st.session_state.get(
            gk, get_groq_model(),
        )
    else:
        st.session_state[_SHARED_GEMINI_MODEL_KEY] = st.session_state.get(
            mk, get_gemini_model(),
        )
    st.session_state[_SHARED_AI_VERSION] = (
        st.session_state.get(_SHARED_AI_VERSION, 0) + 1
    )


def _ensure_prefix_matches_shared(key_prefix: str) -> None:
    """Drop stale per-section widget keys when another section changed the global selection."""
    pk, gk, mk = _prefix_ai_keys(key_prefix)
    shared_provider, shared_model, _ = get_ai_provider_settings()
    local_ver = st.session_state.get(f"{pk}_sync_ver", -1)
    global_ver = st.session_state.get(_SHARED_AI_VERSION, 0)
    local_provider = st.session_state.get(pk)
    if local_ver >= global_ver and local_provider == shared_provider:
        return
    for key in (pk, gk, mk):
        st.session_state.pop(key, None)
    st.session_state[f"{pk}_sync_ver"] = global_ver


def _on_ai_provider_change(key_prefix: str) -> None:
    _sync_prefix_to_shared(key_prefix)


def _on_ai_model_change(key_prefix: str) -> None:
    _sync_prefix_to_shared(key_prefix)


def _ai_provider_caption(provider: str, model: str, api_key: str) -> None:
    key_note = "✅ key from `.env`" if api_key else "⚠️ missing API key"
    st.caption(f"AI: **{provider}** · `{model}` · {key_note}")

TRADE_MANAGEMENT_SECTION = """
## TRADE MANAGEMENT
- Expected Holding Time: [specific duration tied to timeframe — e.g. "2-4 hours intraday", "3-7 trading days swing"]
- Max Time In Trade: [hard time stop — exit if target not reached by this time]
- Scale-Out Plan: [when to book partial profits, if applicable]

## GREEN SIGNS — STAY IN THE TRADE
- [3-5 specific observable signals that confirm the thesis is still valid — price action, indicator, volume, or level behavior]
- [Each bullet must be concrete and monitorable on the chart]

## RED FLAGS — EXIT IMMEDIATELY
- [3-5 specific invalidation triggers — broken levels, indicator reversals, volume against position, structure break]
- [Include at least one price-based and one indicator/structure-based red flag]
- Time-Based Exit: [exit even if stop not hit if trade stalls beyond expected holding window]"""

STANDARD_REPORT_FORMAT = """
Respond in EXACTLY this format:

## FINAL VERDICT
[BUY or SELL or AVOID — exactly one word]

## TRADE SETUP
- Direction: [LONG / SHORT / NONE]
- Entry: [price]
- Stop Loss: [price] — [brief reason]
- Take Profit 1: [price] — [brief reason]
- Take Profit 2: [price or N/A] — [brief reason]
- Risk:Reward: [ratio]
- Confidence: [0-100]%
""" + TRADE_MANAGEMENT_SECTION + """

## KEY REASONS
- [3-6 bullet points explaining the verdict]

## AI ANALYSIS REPORT
[Detailed analysis with clear sections including trade management playbook]"""

MTF_STANDARD_REPORT_FORMAT = """
Respond in EXACTLY this format:

## FINAL VERDICT
[BUY or SELL or AVOID — exactly one word]

## MULTI-TIMEFRAME CONFLUENCE
- Higher Timeframe Bias: [bullish / bearish / neutral]
- Mid Timeframe Bias: [bullish / bearish / neutral]
- Lower Timeframe Bias: [bullish / bearish / neutral]
- Alignment Score: [0-100]% — [how many timeframes agree]
- Dominant Trend: [one sentence]

## TRADE SETUP
- Direction: [LONG / SHORT / NONE]
- Entry: [price or zone]
- Stop Loss: [price] — [brief reason]
- Take Profit 1: [price] — [brief reason]
- Take Profit 2: [price or N/A] — [brief reason]
- Risk:Reward: [ratio]
- Confidence: [0-100]%
""" + TRADE_MANAGEMENT_SECTION + """

## KEY REASONS
- [3-6 bullet points explaining the verdict across timeframes]

## AI ANALYSIS REPORT
[Detailed MTF analysis: HTF trend context, MTF structure, LTF entry timing, conflicting signals,
confluence zones, position sizing note, and trade management playbook]"""

MTF_AI_SYSTEM = """You are an expert multi-timeframe (MTF) trader and technical analyst for Indian equities and crypto futures.

You will receive analysis output from MULTIPLE timeframes for the SAME ticker from a single scan run.
Your job is to synthesize them into ONE unified expert trade plan:

1. Higher timeframes (4h, 1d) define the primary bias and holding-period context.
2. Mid timeframes (1h, 30m) confirm structure and trend quality.
3. Lower timeframes (5m, 15m) refine entry timing and tight stop placement.
4. Weight confluence heavily — 3+ aligned timeframes = higher confidence.
5. If timeframes strongly conflict, verdict MUST be AVOID.
6. Always specify expected holding time, max time in trade, green signs to stay in, and red flags to exit.
7. Stop loss and take profit must be concrete prices derived from the supplied levels.
8. Green signs and red flags must be specific, observable, and tied to the data in the timeframe blocks.

Be data-driven. Reference specific values from the timeframe blocks below.
""" + MTF_STANDARD_REPORT_FORMAT


def combine_timeframe_sections(title: str, ticker: str, sections: list, market: str = None) -> str:
    """Merge per-timeframe prompt blocks into one MTF user prompt."""
    lines = [
        f"=== {title} ===",
        f"Ticker: {ticker}",
        f"Timeframes in this run: {len(sections)}",
    ]
    if market:
        lines.append(f"Market: {market}")
    lines.append("")
    lines.append("Synthesize ALL timeframe blocks below into one multi-timeframe trade plan.")
    lines.append("")
    for i, section in enumerate(sections, 1):
        lines.append("─" * 52)
        lines.append(f"TIMEFRAME BLOCK {i} / {len(sections)}")
        lines.append("─" * 52)
        lines.append(section)
        lines.append("")
    return "\n".join(lines)


def _model_options_with_env_default(options: list[str], env_model: str) -> list[str]:
    if env_model and env_model not in options:
        return [env_model, *options]
    return list(options)


def get_ai_provider_settings() -> tuple[str, str, str]:
    """Current provider/model/api_key from session state or `.env` defaults."""
    _init_shared_ai_state()
    provider = st.session_state.get(_SHARED_PROVIDER_KEY, default_ai_provider())
    if provider not in SUPPORTED_AI_PROVIDERS:
        provider = default_ai_provider()
    if provider == "Groq (LLaMA)":
        model = st.session_state.get(_SHARED_GROQ_MODEL_KEY, get_groq_model())
    elif provider == "Investing Agent":
        model = "superinvesting-chat"
    elif provider == "Claude (Azure)":
        import os
        model = st.session_state.get("shared_claude_model", os.getenv("CLAUDE_MODEL", "claude-sonnet-5"))
    elif provider == "OpenAI (Azure)":
        import os
        model = st.session_state.get("shared_openai_model", os.getenv("OPENAI_MODEL", "gpt-5.6-sol"))
    else:
        model = st.session_state.get(_SHARED_GEMINI_MODEL_KEY, get_gemini_model())
    api_key = get_api_key_for_provider(provider)
    if provider == "Investing Agent" and not api_key:
        try:
            import os
            api_key = (os.getenv("SUPERINVESTING_TOKEN") or "").strip()
        except Exception:
            api_key = ""
    return provider, model, api_key


def _render_ai_provider_widget_row(key_prefix: str = "global") -> tuple[str, str, str]:
    """Draw provider + model dropdowns; syncs selection globally across sections."""
    _init_shared_ai_state()
    _ensure_prefix_matches_shared(key_prefix)
    pk, gk, mk = _prefix_ai_keys(key_prefix)

    shared_provider, shared_model, _ = get_ai_provider_settings()
    prov_index = (
        SUPPORTED_AI_PROVIDERS.index(shared_provider)
        if shared_provider in SUPPORTED_AI_PROVIDERS
        else default_ai_provider_index()
    )

    col_p, col_m, col_s = st.columns([1.15, 1.55, 1.1])
    with col_p:
        prov_args: dict = {
            "label": "AI Provider",
            "options": SUPPORTED_AI_PROVIDERS,
            "key": pk,
            "help": "Switch provider if one API is down, rate-limited, or missing a key.",
            "on_change": _on_ai_provider_change,
            "args": (key_prefix,),
        }
        if pk not in st.session_state:
            prov_args["index"] = prov_index
        st.selectbox(**prov_args)
    provider = st.session_state[pk]
    with col_m:
        if provider == "Groq (LLaMA)":
            groq_opts = _model_options_with_env_default(GROQ_MODEL_OPTIONS, get_groq_model())
            groq_index = (
                groq_opts.index(shared_model)
                if shared_model in groq_opts
                else groq_opts.index(get_groq_model()) if get_groq_model() in groq_opts else 0
            )
            groq_args: dict = {
                "label": "Model",
                "options": groq_opts,
                "key": gk,
                "on_change": _on_ai_model_change,
                "args": (key_prefix,),
            }
            if gk not in st.session_state:
                groq_args["index"] = groq_index
            st.selectbox(**groq_args)
            model = st.session_state[gk]
        elif provider == "Investing Agent":
            st.caption("Fundamental Analyst chat (no model picker)")
            model = "superinvesting-chat"
        elif provider == "Claude (Azure)":
            import os
            claude_default = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
            claude_opts = _model_options_with_env_default(
                ["claude-sonnet-5", "claude-opus-4-1", "claude-sonnet-4-5", "claude-haiku-4-5"],
                claude_default,
            )
            ck = f"{key_prefix}_ai_claude_model"
            c_index = claude_opts.index(shared_model) if shared_model in claude_opts else 0
            c_args: dict = {
                "label": "Model",
                "options": claude_opts,
                "key": ck,
                "on_change": _on_ai_model_change,
                "args": (key_prefix,),
            }
            if ck not in st.session_state:
                c_args["index"] = c_index
            st.selectbox(**c_args)
            model = st.session_state[ck]
            st.session_state["shared_claude_model"] = model
        elif provider == "OpenAI (Azure)":
            import os
            openai_default = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
            openai_opts = _model_options_with_env_default(
                [
                    "gpt-5.6-sol",
                    "DeepSeek-V4-Flash",
                    "gpt-4o",
                    "o4-mini",
                    "gpt-4o-mini",
                    "gpt-5-nano",
                    "gpt-5-mini",
                    "gpt-5",
                    "gpt-4.1",
                    "gpt-4.1-mini",
                ],
                openai_default,
            )
            ok = f"{key_prefix}_ai_openai_model"
            o_index = openai_opts.index(shared_model) if shared_model in openai_opts else 0
            o_args: dict = {
                "label": "Model",
                "options": openai_opts,
                "key": ok,
                "on_change": _on_ai_model_change,
                "args": (key_prefix,),
            }
            if ok not in st.session_state:
                o_args["index"] = o_index
            st.selectbox(**o_args)
            model = st.session_state[ok]
            st.session_state["shared_openai_model"] = model
        else:
            gem_opts = _model_options_with_env_default(GEMINI_MODEL_OPTIONS, get_gemini_model())
            gem_index = (
                gem_opts.index(shared_model)
                if shared_model in gem_opts
                else gem_opts.index(get_gemini_model()) if get_gemini_model() in gem_opts else 0
            )
            gem_args: dict = {
                "label": "Model",
                "options": gem_opts,
                "key": mk,
                "on_change": _on_ai_model_change,
                "args": (key_prefix,),
            }
            if mk not in st.session_state:
                gem_args["index"] = gem_index
            st.selectbox(**gem_args)
            model = st.session_state[mk]
    st.session_state[f"{pk}_sync_ver"] = st.session_state.get(_SHARED_AI_VERSION, 0)
    api_key = get_api_key_for_provider(provider)
    with col_s:
        if api_key:
            short = {
                "Groq (LLaMA)": "Groq",
                "Google Gemini": "Gemini",
                "Claude (Azure)": "Claude",
                "OpenAI (Azure)": "OpenAI",
                "Investing Agent": "Investing",
            }.get(provider, provider)
            st.caption(f"✅ `{short}` key from `.env`")
        else:
            st.warning(api_key_env_hint(provider), icon="⚠️")
    return provider, model, api_key


def render_ai_provider_compact(
    *,
    show_label: bool = True,
    key_prefix: str = "global",
) -> tuple[str, str, str]:
    """
    AI provider + model selectors shared across AI View and Ask AI.
    Each call renders its own dropdowns (keyed by key_prefix) but keeps
    selection in sync via shared session state.
    """
    if show_label:
        st.markdown(
            '<div style="font-size:0.72rem;color:#64748b;text-transform:uppercase;'
            'letter-spacing:0.06em;margin:4px 0 2px 0;">🤖 AI Provider</div>',
            unsafe_allow_html=True,
        )
    return _render_ai_provider_widget_row(key_prefix)


def render_ai_config(key_prefix: str, caption: str = "AI View uses these settings for per-result reports."):
    """Compact AI provider row for AI View sections (selection syncs globally)."""
    if caption:
        st.caption(caption)
    return render_ai_provider_compact(show_label=False, key_prefix=key_prefix)


def call_ai_report(prompt_data, system_prompt, provider, model, api_key, user_intro=None, max_tokens=3000):
    """Call Groq, Gemini, Claude, OpenAI, or Investing Agent and return the report text."""
    if provider == "Custom / Other":
        return "❌ Custom / Other AI provider is not supported for AI View. Use Groq, Gemini, Claude, OpenAI, or Investing Agent."
    if provider in ("Investing Agent", "Claude (Azure)", "OpenAI (Azure)"):
        import os
        from app.services.ai_service import call_ai_report as _svc_call

        base_url = None
        if provider == "Claude (Azure)":
            base_url = (
                os.getenv("CLAUDE_ENDPOINT")
                or os.getenv("ANTHROPIC_FOUNDRY_BASE_URL")
                or "https://atul-mjil3w7p-swedencentral.services.ai.azure.com/anthropic"
            )
        elif provider == "OpenAI (Azure)":
            base_url = (
                os.getenv("OPENAI_ENDPOINT")
                or os.getenv("AZURE_OPENAI_ENDPOINT")
                or "https://aiadvisorassis8258039388.services.ai.azure.com/openai/v1"
            )
        return _svc_call(
            prompt_data,
            system_prompt,
            provider,
            model or ("superinvesting-chat" if provider == "Investing Agent" else ""),
            api_key or "",
            user_intro=user_intro,
            max_tokens=max_tokens,
            base_url=base_url,
        )
    if not api_key:
        return f"❌ {api_key_env_hint(provider)}"

    intro = user_intro or "Analyze the following data and give a trade verdict with setup:"
    user_msg = f"{intro}\n\n{prompt_data}"

    try:
        if provider == "Groq (LLaMA)":
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=max_tokens,
                temperature=0.35,
            )
            return resp.choices[0].message.content
        elif provider == "Google Gemini":
            if GENAI_NEW:
                client = genai_new.Client(api_key=api_key)
                combined = system_prompt + "\n\n" + user_msg
                resp = client.models.generate_content(model=model, contents=combined)
                return resp.text
            elif genai:
                genai.configure(api_key=api_key)
                gmodel = genai.GenerativeModel(model, system_instruction=system_prompt)
                resp = gmodel.generate_content(user_msg)
                return resp.text
            return "❌ Google Gemini library not installed."
    except Exception as e:
        return f"❌ AI Report Error: {str(e)}\n\nPlease check your API key and model selection."
    return "❌ Unknown AI provider. Use Google Gemini, Groq (LLaMA), Claude (Azure), OpenAI (Azure), or Investing Agent."


def safe_ai_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _parse_ai_verdict(report_text):
    match = re.search(r"##\s*FINAL\s*VERDICT\s*\n\s*(BUY|SELL|AVOID)", report_text, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(BUY|SELL|AVOID)\b", report_text[:400], re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def _escape_streamlit_markdown(text):
    return text.replace("$", "\\$")


def _strip_verdict_header(report_text):
    return re.sub(
        r"##\s*FINAL\s*VERDICT\s*\n\s*(?:BUY|SELL|AVOID)\s*\n*",
        "",
        report_text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def render_ai_report(symbol, timeframe_label, report_text, provider, model):
    """Render AI report using native Streamlit widgets."""
    if report_text.startswith("❌"):
        st.error(report_text)
        return

    verdict = _parse_ai_verdict(report_text)
    body = _strip_verdict_header(report_text)

    with st.container(border=True):
        st.caption(f"🤖 AI View · {symbol} · {timeframe_label} · {provider} · {model}")

        if verdict == "BUY":
            st.success(f"🟢 **AI FINAL VERDICT: {verdict}**")
        elif verdict == "SELL":
            st.error(f"🔴 **AI FINAL VERDICT: {verdict}**")
        elif verdict == "AVOID":
            st.warning(f"🟡 **AI FINAL VERDICT: {verdict}**")
        else:
            st.info("⚪ AI verdict could not be parsed from the response.")

        st.markdown(_escape_streamlit_markdown(body))


def ai_view_button(session_prefix, result_key, button_in_column=True):
    """Render AI View button; returns True if report should be shown."""
    safe = safe_ai_key(result_key)
    show_key = f"{session_prefix}_ai_show_{safe}"
    refresh_key = f"{session_prefix}_ai_refresh_{safe}"
    if st.button("🤖 AI View", key=f"{session_prefix}_ai_btn_{safe}", width='stretch' if button_in_column else 'content'):
        st.session_state[show_key] = True
        st.session_state[refresh_key] = True
    return st.session_state.get(show_key, False)


def _seed_block_ai_defaults(session_prefix: str, result_key: str) -> None:
    safe = safe_ai_key(result_key)
    prov_key = f"{session_prefix}_bprov_{safe}"
    if prov_key in st.session_state:
        return
    provider, model, _ = get_ai_provider_settings()
    st.session_state[prov_key] = provider
    if provider == "Groq (LLaMA)":
        st.session_state[f"{session_prefix}_bgroq_{safe}"] = model
    else:
        st.session_state[f"{session_prefix}_bgem_{safe}"] = model


def render_block_ai_settings(session_prefix: str, result_key: str) -> tuple[str, str, str]:
    """Per AI View block: Groq/Gemini provider + model selectors."""
    safe = safe_ai_key(result_key)
    _seed_block_ai_defaults(session_prefix, result_key)
    prov_key = f"{session_prefix}_bprov_{safe}"
    groq_key = f"{session_prefix}_bgroq_{safe}"
    gem_key = f"{session_prefix}_bgem_{safe}"

    st.caption("Choose **Gemini** or **Groq** and model for this report:")
    col_p, col_m, col_s = st.columns([1.15, 1.55, 1.1])
    with col_p:
        provider = st.selectbox(
            "AI Provider",
            SUPPORTED_AI_PROVIDERS,
            key=prov_key,
            help="Switch provider if one API is down, rate-limited, or missing a key.",
        )
    with col_m:
        if provider == "Groq (LLaMA)":
            groq_opts = _model_options_with_env_default(GROQ_MODEL_OPTIONS, get_groq_model())
            if groq_key not in st.session_state:
                _, model, _ = get_ai_provider_settings()
                st.session_state[groq_key] = model if model in groq_opts else groq_opts[0]
            model = st.selectbox("Model", groq_opts, key=groq_key)
        else:
            gem_opts = _model_options_with_env_default(GEMINI_MODEL_OPTIONS, get_gemini_model())
            if gem_key not in st.session_state:
                _, model, _ = get_ai_provider_settings()
                st.session_state[gem_key] = model if model in gem_opts else gem_opts[0]
            model = st.selectbox("Model", gem_opts, key=gem_key)
    api_key = get_api_key_for_provider(provider)
    with col_s:
        if api_key:
            short = "Groq" if provider == "Groq (LLaMA)" else "Gemini"
            st.caption(f"✅ `{short}` key from `.env`")
        else:
            st.warning(api_key_env_hint(provider), icon="⚠️")
    return provider, model, api_key


def render_ai_view_report(
    session_prefix, result_key, symbol, timeframe_label,
    build_prompt_fn, system_prompt, provider=None, model=None, api_key=None,
    *, inline_ai_picker: bool = True,
):
    """Generate (if needed) and render AI report at full width."""
    safe = safe_ai_key(result_key)
    show_key = f"{session_prefix}_ai_show_{safe}"
    refresh_key = f"{session_prefix}_ai_refresh_{safe}"
    cache_key = f"{session_prefix}_ai_report_{safe}"

    if not st.session_state.get(show_key, False):
        return

    if inline_ai_picker:
        provider, model, api_key = render_block_ai_settings(session_prefix, result_key)
    else:
        provider = provider or get_ai_provider_settings()[0]
        model = model or get_ai_provider_settings()[1]
        api_key = api_key if api_key is not None else get_api_key_for_provider(provider)

    force = st.session_state.pop(refresh_key, False)
    picker_sig = f"{provider}|{model}"
    sig_key = f"{session_prefix}_ai_sig_{safe}"
    if force or cache_key not in st.session_state or st.session_state.get(sig_key) != picker_sig:
        with nullcontext():
            prompt = build_prompt_fn()
            report = call_ai_report(prompt, system_prompt, provider, model, api_key)
            st.session_state[cache_key] = report
            st.session_state[sig_key] = picker_sig
    render_ai_report(symbol, timeframe_label, st.session_state[cache_key], provider, model)


def show_ai_view_block(
    session_prefix, result_key, symbol, timeframe_label,
    build_prompt_fn, system_prompt, provider=None, model=None, api_key=None,
    button_in_column=True,
    inline_ai_picker: bool = True,
):
    """Render AI View button and report together (for full-width layouts)."""
    ai_view_button(session_prefix, result_key, button_in_column)
    render_ai_view_report(
        session_prefix, result_key, symbol, timeframe_label,
        build_prompt_fn, system_prompt, provider, model, api_key,
        inline_ai_picker=inline_ai_picker,
    )


def mtf_ticker_button(session_prefix, ticker, button_in_column=True):
    """Render 'AI View for Ticker' button (aggregates all timeframes for one ticker)."""
    safe = safe_ai_key(f"mtf_{ticker}")
    show_key = f"{session_prefix}_mtf_show_{safe}"
    refresh_key = f"{session_prefix}_mtf_refresh_{safe}"
    if st.button(
        "🤖 AI View for Ticker",
        key=f"{session_prefix}_mtf_btn_{safe}",
        width='stretch' if button_in_column else 'content',
        help="Multi-timeframe expert analysis across all durations for this ticker",
    ):
        st.session_state[show_key] = True
        st.session_state[refresh_key] = True
    return st.session_state.get(show_key, False)


def render_mtf_ai_report(symbol, report_text, provider, model, timeframe_count):
    """Render aggregated multi-timeframe AI report."""
    if report_text.startswith("❌"):
        st.error(report_text)
        return

    verdict = _parse_ai_verdict(report_text)
    body = _strip_verdict_header(report_text)

    with st.container(border=True):
        st.caption(
            f"🤖 AI View for Ticker · {symbol} · {timeframe_count} timeframe(s) · "
            f"{provider} · {model}"
        )

        if verdict == "BUY":
            st.success(f"🟢 **MTF FINAL VERDICT: {verdict}**")
        elif verdict == "SELL":
            st.error(f"🔴 **MTF FINAL VERDICT: {verdict}**")
        elif verdict == "AVOID":
            st.warning(f"🟡 **MTF FINAL VERDICT: {verdict}**")
        else:
            st.info("⚪ MTF verdict could not be parsed from the response.")

        st.markdown(_escape_streamlit_markdown(body))


def render_mtf_ai_view_report(
    session_prefix, ticker, build_prompt_fn, system_prompt,
    provider=None, model=None, api_key=None, timeframe_count=0,
    *, inline_ai_picker: bool = True,
):
    """Generate (if needed) and render multi-timeframe AI report for a ticker."""
    safe = safe_ai_key(f"mtf_{ticker}")
    show_key = f"{session_prefix}_mtf_show_{safe}"
    refresh_key = f"{session_prefix}_mtf_refresh_{safe}"
    cache_key = f"{session_prefix}_mtf_report_{safe}"

    if not st.session_state.get(show_key, False):
        return

    if inline_ai_picker:
        provider, model, api_key = render_block_ai_settings(session_prefix, f"mtf_{ticker}")
    else:
        provider = provider or get_ai_provider_settings()[0]
        model = model or get_ai_provider_settings()[1]
        api_key = api_key if api_key is not None else get_api_key_for_provider(provider)

    force = st.session_state.pop(refresh_key, False)
    picker_sig = f"{provider}|{model}"
    sig_key = f"{session_prefix}_mtf_sig_{safe}"
    if force or cache_key not in st.session_state or st.session_state.get(sig_key) != picker_sig:
        with st.spinner(f"🤖 Generating multi-timeframe AI report for {ticker} ({timeframe_count} TFs)..."):
            prompt = build_prompt_fn()
            report = call_ai_report(
                prompt,
                system_prompt,
                provider,
                model,
                api_key,
                user_intro=(
                    "Synthesize ALL timeframe analyses below into one expert multi-timeframe "
                    "trade plan with entry, stop loss, take profit, and expected holding time:"
                ),
                max_tokens=4000,
            )
            st.session_state[cache_key] = report
            st.session_state[sig_key] = picker_sig
    render_mtf_ai_report(ticker, st.session_state[cache_key], provider, model, timeframe_count)


def show_mtf_ai_view_block(
    session_prefix, ticker, build_prompt_fn, system_prompt,
    provider, model, api_key, timeframe_count, button_in_column=True,
):
    """Render MTF AI button and report together."""
    mtf_ticker_button(session_prefix, ticker, button_in_column)
    render_mtf_ai_view_report(
        session_prefix, ticker, build_prompt_fn, system_prompt,
        provider, model, api_key, timeframe_count,
    )


# ─── Tab-specific prompt builders ───────────────────────────────────────────

def build_sentiment_ai_prompt(row, market):
    lines = [
        "=== TREND & SENTIMENT ANALYSIS ===",
        f"Ticker: {row['Ticker']}",
        f"Timeframe: {row['Timeframe']}",
        f"Market: {market}",
        f"Composite Score: {row['Score']} (-100 bearish to +100 bullish)",
        f"Rating: {row['Rating']}",
        f"Trade Signal: {row.get('Trade Signal', 'N/A')}",
        f"RSI: {row.get('RSI', 0)}",
        f"ADX: {row.get('ADX', 0)}",
        f"Trend: {row.get('Trend', 'N/A')}",
        f"Volume Ratio: {row.get('Vol Ratio', 0)}",
        f"MACD Histogram: {row.get('MACD Hist', 0)}",
        f"ATR %: {row.get('ATR %', 0)}",
        f"Suggested SL %: {row.get('SL %', 0)}",
        f"Suggested TP %: {row.get('TP %', 0)}",
        "",
        "=== TECHNICAL INSIGHTS ===",
    ]
    for insight in row.get("Insights", []):
        lines.append(f"  - {insight}")
    return "\n".join(lines)


SENTIMENT_AI_SYSTEM = """You are an expert multi-timeframe technical sentiment analyst for Indian equities and crypto futures.
Analyze the composite sentiment score, indicators, and insights. Be data-driven.
If the score is near neutral or signals conflict, verdict must be AVOID.
For every BUY or SELL verdict, specify how long to hold, green signs to stay in, and red flags to exit.
""" + STANDARD_REPORT_FORMAT


def build_gap_ai_prompt(setup, market, currency):
    lines = [
        "=== GAP TRADING SCANNER OUTPUT ===",
        f"Symbol: {setup.get('symbol', 'N/A')}",
        f"Timeframe: {setup.get('timeframe', 'N/A')}",
        f"Market: {market}",
        f"Gap Type: {setup.get('gap_type', 'N/A')}",
        f"Gap %: {setup.get('gap_pct', 0):+.2f}%",
        f"Strategy: {setup.get('strategy', 'N/A')}",
        f"Signal Quality: {setup.get('signal_quality', 'N/A')}",
        f"Current Price: {currency}{setup.get('current_price', 0)}",
        "",
        "=== TRADE SETUP ===",
        f"Entry: {currency}{setup.get('entry', 0)}",
        f"Stop Loss: {currency}{setup.get('stop_loss', 0)} ({setup.get('sl_pct', 0):.2f}%)",
        f"Target: {currency}{setup.get('target', 0)} ({setup.get('tp_pct', 0):.2f}%)",
        f"R:R Ratio: {setup.get('rr_ratio', 0):.2f}",
        f"Fill Probability: {setup.get('fill_probability', 0):.0%}" if setup.get('fill_probability') is not None else "",
        f"S1: {currency}{setup.get('s1', 'N/A')} | S2: {currency}{setup.get('s2', 'N/A')}",
        f"R1: {currency}{setup.get('r1', 'N/A')} | R2: {currency}{setup.get('r2', 'N/A')}",
        f"Notes: {setup.get('notes', '')}",
    ]
    return "\n".join(l for l in lines if l)


GAP_AI_SYSTEM = """You are an expert gap trading analyst for Indian equities and crypto futures.
Analyze gap direction, fade vs continuation strategy, fill probability, and S/R levels.
Gap trades are high risk if gap is small or R:R is poor — use AVOID when appropriate.
Gap trades are usually short-duration — state expected holding time and intraday red/green flags clearly.
""" + STANDARD_REPORT_FORMAT


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def build_seasonality_ai_prompt(ticker, stats_df, signals_df, bt_metrics, lookback_years, asset_type):
    lines = [
        "=== SEASONALITY SCAN OUTPUT ===",
        f"Ticker: {ticker}",
        f"Asset Class: {asset_type}",
        f"Lookback: {lookback_years} years",
        "",
        "=== BACKTEST METRICS (Seasonal Strategy) ===",
        f"CAGR: {bt_metrics['CAGR']:.2%}",
        f"Sharpe Ratio: {bt_metrics['Sharpe']:.2f}",
        f"Max Drawdown: {bt_metrics['Max Drawdown']:.2%}",
        f"Total Return: {bt_metrics['Total Return']:.2%}",
        "",
        "=== MONTHLY STATISTICS ===",
    ]
    for _, row in stats_df.iterrows():
        m = int(row["Month"])
        lines.append(
            f"  {MONTH_NAMES[m-1]}: Avg Return {row['Avg Return']*100:.2f}%, "
            f"Win Rate {row['Win Rate']:.0%}, P-Value {row['P-Value']:.4f}, N={int(row['Count'])}"
        )

    lines.append("\n=== SEASONAL SIGNALS ===")
    for _, row in signals_df.iterrows():
        m = int(row["Month"])
        lines.append(
            f"  {MONTH_NAMES[m-1]}: {row['Action']} (strength {row['Strength']}, WR {row['Win Rate']:.0%})"
        )

    import datetime
    current_month = datetime.datetime.now().month
    curr_sig = signals_df[signals_df["Month"] == current_month]
    if not curr_sig.empty:
        lines.append(f"\n=== CURRENT MONTH ({MONTH_NAMES[current_month-1]}) ===")
        r = curr_sig.iloc[0]
        lines.append(f"Signal: {r['Action']} | Win Rate: {r['Win Rate']:.0%} | P-Value: {r['P-Value']:.4f}")

    return "\n".join(lines)


SEASONALITY_AI_SYSTEM = """You are an expert seasonal pattern analyst for equities and crypto.
Analyze monthly win rates, statistical significance (p-values), and backtest metrics.
Seasonality is probabilistic — use AVOID when current month has no edge or signals are weak.
For trade setup, base entry on current price context and seasonal bias for the active month.
Holding time should reflect the seasonal window (days to weeks). Include monthly/statistical red and green flags.
""" + STANDARD_REPORT_FORMAT


# ─── Strategy Builder & Tester AI prompt builders ───────────────────────────

def build_strategy_backtest_ai_prompt(ticker, backtest_metrics, recent_trades=None, run_config=None):
    """Build AI prompt for strategy backtest performance analysis."""
    lines = [
        "=== STRATEGY BACKTEST PERFORMANCE ANALYSIS ===",
        f"Ticker: {ticker}",
        "",
        "=== BACKTEST METRICS ===",
    ]

    if run_config:
        lines.extend([
            f"Market: {run_config.get('market', 'N/A')}",
            f"Timeframe: {run_config.get('timeframe', 'N/A')}",
            f"Strategy: {run_config.get('strategy_name', 'Custom')}",
            f"Date Range: {run_config.get('start_date', 'N/A')} → {run_config.get('end_date', 'N/A')}",
            f"Initial Capital: {run_config.get('initial_capital', 'N/A')}",
            f"Commission: {run_config.get('commission', 'N/A')}",
            f"Slippage: {run_config.get('slippage', 'N/A')}",
            f"Stop Loss %: {run_config.get('sl_pct', 0)}",
            f"Take Profit %: {run_config.get('tp_pct', 0)}",
            "",
        ])
        indicators = run_config.get("indicators") or []
        entry_rules = run_config.get("entry_rules") or []
        exit_rules = run_config.get("exit_rules") or []
        if indicators:
            lines.append("=== CONFIGURED INDICATORS ===")
            for ind in indicators[:12]:
                lines.append(f"  - {ind}")
        if entry_rules:
            lines.append("=== ENTRY RULES ===")
            for r in entry_rules[:8]:
                lines.append(f"  - {r.get('left', '?')} {r.get('op', '?')} {r.get('right_val', '?')}")
        if exit_rules:
            lines.append("=== EXIT RULES ===")
            for r in exit_rules[:8]:
                lines.append(f"  - {r.get('left', '?')} {r.get('op', '?')} {r.get('right_val', '?')}")
        lines.append("")

    if isinstance(backtest_metrics, dict):
        for key, value in backtest_metrics.items():
            if key in ("trades",) or isinstance(value, (list, dict)):
                continue
            if isinstance(value, float):
                if 'return' in key.lower() or 'cagr' in key.lower() or 'sharpe' in key.lower():
                    lines.append(f"  {key}: {value:.2%}" if abs(value) < 1 else f"  {key}: {value:.2f}")
                elif 'drawdown' in key.lower():
                    lines.append(f"  {key}: {value:.2%}")
                else:
                    lines.append(f"  {key}: {value:.2f}")
            else:
                lines.append(f"  {key}: {value}")
    
    if recent_trades:
        lines.extend(["", "=== RECENT TRADES (Last 10) ==="])
        for i, trade in enumerate(recent_trades[:10], 1):
            entry_price = trade.get('entry_price', 'N/A')
            exit_price = trade.get('exit_price', 'N/A')
            pnl = trade.get('pnl', 'N/A')
            result = "✓ WIN" if isinstance(pnl, (int, float)) and pnl > 0 else "✗ LOSS"
            lines.append(f"  {i}. Entry: {entry_price} → Exit: {exit_price} | P&L: {pnl} {result}")
    
    lines.extend([
        "",
        "=== ANALYSIS CONTEXT ===",
        "Evaluate strategy viability based on backtest performance.",
        "Consider win rate, risk/reward ratio, and consistency.",
        "Current market conditions may differ from backtest period.",
    ])
    
    return "\n".join(lines)


STRATEGY_BACKTEST_AI_SYSTEM = """You are an expert algorithmic trader evaluating strategy backtest performance.
Analyze metrics holistically: CAGR, Sharpe, drawdown, win rate, profit factor, and trade count.

Verdict mapping:
- BUY = Deploy this strategy live on this ticker/timeframe — strong risk-adjusted edge
- AVOID = Revise parameters before live use — weak or inconclusive metrics
- SELL = Abandon this configuration — destructive or overfitted

For BUY or SELL, translate backtest edge into a live trade plan:
holding time (based on timeframe), entry zone, stop loss, take profit, green signs to stay in,
and red flags to exit. Reference the configured indicators and rules when relevant.
""" + STANDARD_REPORT_FORMAT


# ─── Multi-Combo Scanner AI prompt builders ───────────────────────────────

def build_multi_combo_scan_row_prompt(row, market):
    """Build AI prompt for one multi-combo scanner backtest result row."""
    def _fmt(val):
        if val is None:
            return "N/A"
        try:
            if val != val:  # NaN
                return "N/A"
        except TypeError:
            pass
        if isinstance(val, float):
            return f"{val:.2f}"
        return str(val)

    lines = [
        "=== MULTI-COMBO SCANNER BACKTEST RESULT ===",
        f"Ticker: {row.get('Ticker', 'N/A')}",
        f"Timeframe: {row.get('Timeframe', 'N/A')}",
        f"Strategy: {row.get('Strategy', 'N/A')}",
        f"Market: {market}",
        f"Status: {row.get('Status', 'N/A')}",
        "",
        "=== BACKTEST METRICS ===",
        f"Total Return %: {_fmt(row.get('Return %'))}",
        f"CAGR %: {_fmt(row.get('CAGR %'))}",
        f"Sharpe Ratio: {_fmt(row.get('Sharpe'))}",
        f"Max Drawdown %: {_fmt(row.get('Max DD %'))}",
        f"Win Rate %: {_fmt(row.get('Win Rate %'))}",
        f"Trades Executed: {row.get('Trades', 0)}",
        f"Profit Factor: {_fmt(row.get('Profit Factor'))}",
        f"Final Capital: {_fmt(row.get('Final Capital'))}",
        "",
        "=== ANALYSIS NOTE ===",
        "Low trade count (<10) reduces statistical confidence.",
        "Extreme return with few trades may indicate overfitting.",
    ]
    return "\n".join(lines)


MULTI_COMBO_SCAN_AI_SYSTEM = """You are an expert quantitative trader evaluating multi-combo scanner backtest results.
Each input is ONE ticker × timeframe × strategy combination from a batch scan.

Verdict BUY = deploy this specific combo live with concrete trade management.
Verdict AVOID = do not trade — metrics weak, too few trades, or unreliable.
Verdict SELL = actively avoid — likely overfitted or capital-destructive.

Weight Sharpe, drawdown, win rate, profit factor, and trade count equally.
For BUY, recommend holding time based on timeframe, plus green signs and red flags for live monitoring.
""" + STANDARD_REPORT_FORMAT


# ─── Multi-Combo Scanner (screener-style) AI prompt builders ──────────────

def build_multi_combo_ai_prompt(ticker, timeframe, combo_results, market="NSE"):
    """Build AI prompt for multi-strategy combo analysis."""
    lines = [
        "=== MULTI-STRATEGY COMBO SCAN ===",
        f"Ticker: {ticker}",
        f"Timeframe: {timeframe}",
        f"Market: {market}",
        f"Total Strategies Analyzed: {len(combo_results)}",
        "",
        "=== STRATEGY RESULTS ===",
    ]
    
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    
    for result in combo_results:
        strategy_name = result.get('Strategy', 'Unknown')
        score = result.get('Score', 0)
        signal = result.get('Signal', 'NEUTRAL')
        confidence = result.get('Confidence', 50)
        
        lines.append(f"\n**{strategy_name}**")
        lines.append(f"  Score: {score}/100 | Signal: {signal} | Confidence: {confidence}%")
        
        if 'Details' in result and result['Details']:
            for detail in result['Details'][:3]:  # Show top 3 details
                lines.append(f"    • {detail}")
        
        if signal == "BUY":
            bullish_count += 1
        elif signal == "SELL":
            bearish_count += 1
        else:
            neutral_count += 1
    
    lines.extend([
        "",
        "=== CONFLUENCE SUMMARY ===",
        f"Bullish Strategies: {bullish_count}/{len(combo_results)}",
        f"Bearish Strategies: {bearish_count}/{len(combo_results)}",
        f"Neutral/Conflicting: {neutral_count}/{len(combo_results)}",
        "",
        "=== ANALYSIS INSTRUCTION ===",
        "Synthesize these multi-strategy signals into a unified expert market verdict.",
        "High confluence (3+ strategies aligned) = High confidence BUY/SELL.",
        "Split signals = Risk; consider AVOID or reduced position sizing.",
        "Identify key support/resistance and optimal entry points.",
    ])
    
    return "\n".join(lines)


ASK_AI_TRADER_SYSTEM = """You are an elite Indian markets mentor combining three lenses:
- **Scalper** — intraday momentum, tight stops, order flow, quick exits
- **Swing trader** — structure, S/R, multi-day setups, sector rotation
- **Investor** — macro context, breadth, positional bias, risk budgeting

You will receive:
1) SECTION ANALYSIS DATA from the app's current screen (may be partial if lazy-loaded)
2) The user's custom question or prompt

Answer using BOTH the supplied data and your market knowledge (NSE/BSE, options, breadth, seasonality).

Rules:
- Be specific and actionable when the data supports it (levels, timeframes, instruments)
- NEVER claim SECTION ANALYSIS DATA is empty when the user message includes scores, verdicts, flows, or quotes — use that data directly
- Only say data is missing if SECTION ANALYSIS DATA explicitly states nothing was loaded
- For India use ₹ and NSE context; mention index vs stock where relevant
- Structure with markdown headers and bullets
- Educational analysis only — not financial advice
"""


MULTI_COMBO_AI_SYSTEM = """You are a master market technician synthesizing signals from multiple technical strategies.
Role: Identify confluence patterns (when multiple strategies align) and resolve conflicts.

Key principles:
1. Confluence Scoring:
   - 4+ strategies bullish = Strong BUY (high confidence)
   - 3 strategies bullish = BUY (moderate confidence)
   - 2 strategies bullish = WATCH (lower confidence)
   - Split signals = AVOID (conflicting = risky)

2. Risk Management:
   - Conflicting signals indicate choppy market conditions
   - Use AVOID when less than 3 strategies agree
   - Higher confluence = larger position sizing justified

3. Entry/Exit Logic:
   - Entry: Use strongest confluent signal + wait for confirmation
   - Exit: At first loss of confluence or technical break
   - SL: Place below recent swing low (for bullish) or above swing high (for bearish)

Provide clear entry zone, stop loss level, take profit targets from strongest setup.
Include holding time and specific green signs / red flags for the combined signal.
""" + STANDARD_REPORT_FORMAT


def render_ask_ai_panel(section_id: str, section_title: str) -> None:
    """Custom Ask AI prompt box — Groq or Gemini + section analysis context."""
    # Sections load data inside @st.fragment — refresh context here every time.
    sync_ask_ai_context(section_id)

    st.markdown("---")
    st.markdown("##### 💬 Ask AI")
    provider, model, api_key = render_ai_provider_compact(key_prefix=f"ask_{section_id}")
    st.caption(
        f"Ask anything about **{section_title}**. Uses **{provider}** (`{model}`) plus "
        "whatever analysis data is loaded in this section. "
        "Switch provider above if one API fails."
    )

    prompt_key = f"ask_ai_prompt_{section_id}"
    answer_key = f"ask_ai_answer_{section_id}"
    pending_key = f"ask_ai_pending_{section_id}"

    user_prompt = st.text_area(
        "Your question or custom prompt",
        height=100,
        key=prompt_key,
        placeholder=(
            "e.g. Which setups look best for a scalping long tomorrow? "
            "What does breadth tell us about risk today?"
        ),
    )

    btn_col, clear_col = st.columns([1, 1])
    with btn_col:
        ask_clicked = st.button(
            "🤖 Ask AI",
            key=f"ask_ai_btn_{section_id}",
            type="primary",
            width='stretch',
        )
    with clear_col:
        if st.button("Clear", key=f"ask_ai_clear_{section_id}", width='stretch'):
            st.session_state.pop(answer_key, None)
            st.session_state.pop(pending_key, None)
            st.rerun()

    if ask_clicked:
        provider, model, api_key = get_ai_provider_settings()
        if not api_key:
            st.session_state[answer_key] = f"❌ {api_key_env_hint(provider)}"
        elif not (user_prompt or "").strip():
            st.warning("Enter a question or prompt first.")
        else:
            st.session_state[pending_key] = True

    if st.session_state.pop(pending_key, False):
        sync_ask_ai_context(section_id)
        ctx = get_ask_ai_context(section_id)
        parts = [
            f"SECTION: {section_title}",
            f"USER QUESTION:\n{user_prompt.strip()}",
        ]
        if ctx and len(ctx.strip()) > 40:
            parts.insert(1, f"SECTION ANALYSIS DATA:\n{ctx[:14000]}")
            st.caption(f"📎 Attached **{min(len(ctx), 14000):,}** chars of section analysis data.")
        else:
            parts.insert(
                1,
                "SECTION ANALYSIS DATA: (Nothing loaded yet — run the section's scan/load "
                "button first, or answer from general market knowledge.)",
            )
            st.warning(
                "No analysis data found for this section. Load/refresh the section first, "
                "then ask again."
            )
        with nullcontext():
            st.session_state[answer_key] = call_ai_report(
                "\n\n".join(parts),
                ASK_AI_TRADER_SYSTEM,
                provider,
                model,
                api_key,
                user_intro="Answer the user's question thoroughly:",
                max_tokens=4000,
            )

    answer = st.session_state.get(answer_key)
    if answer:
        disp_provider, disp_model, _ = get_ai_provider_settings()
        if answer.startswith("❌"):
            st.error(answer)
        else:
            with st.container(border=True):
                st.caption(f"🤖 {disp_provider} · {disp_model} · {section_title}")
                st.markdown(_escape_streamlit_markdown(answer))
