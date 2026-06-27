"""
ta_mtf_hub_ui.py
----------------
Hub-level LTF · MTF · HTF timeframe configuration for the Technical Analysis tab.
All TA sections read from session state when hub mode is enabled.
"""

from __future__ import annotations

TA_ROLES: tuple[str, ...] = ("LTF", "MTF", "HTF")

TA_TF_MINUTES: tuple[str, ...] = ("1m", "5m", "15m", "30m")
TA_TF_HOURS: tuple[str, ...] = ("1h", "4h")
TA_TF_DAYS: tuple[str, ...] = ("1d", "1w", "1wk")

TA_TF_GROUP_LABELS: dict[str, str] = {
    **{tf: "Minutes" for tf in TA_TF_MINUTES},
    **{tf: "Hours" for tf in TA_TF_HOURS},
    **{tf: "Days" for tf in TA_TF_DAYS},
}

ALL_TA_HUB_TFS: tuple[str, ...] = TA_TF_MINUTES + TA_TF_HOURS + TA_TF_DAYS

TF_SORT_ORDER: tuple[str, ...] = ALL_TA_HUB_TFS

TA_MARKET_PRESETS: dict[str, str] = {
    "India (Groww)": "groww",
    "US": "us",
    "Crypto": "crypto",
}

DEFAULT_TA_HUB_TFS: dict[str, dict[str, str]] = {
    "groww": {"LTF": "15m", "MTF": "1h", "HTF": "1d"},
    "us": {"LTF": "1h", "MTF": "1d", "HTF": "1w"},
    "crypto": {"LTF": "5m", "MTF": "15m", "HTF": "1h"},
}

ROLE_LABELS: dict[str, str] = {
    "LTF": "LTF — Low timeframe (entry / scalp)",
    "MTF": "MTF — Medium timeframe (setup / swing)",
    "HTF": "HTF — High timeframe (bias / trend)",
}


def normalize_tf(tf: str) -> str:
    t = (tf or "").strip().lower()
    if t == "1wk":
        return "1w"
    return t


def tf_display_label(tf: str) -> str:
    group = TA_TF_GROUP_LABELS.get(tf, "")
    return f"{tf} ({group})" if group else tf


def _tf_sort_key(tf: str) -> int:
    n = normalize_tf(tf)
    for i, t in enumerate(TF_SORT_ORDER):
        if normalize_tf(t) == n:
            return i
    return len(TF_SORT_ORDER)


def sort_timeframes(tfs: list[str]) -> list[str]:
    return sorted(dict.fromkeys(tfs), key=_tf_sort_key)


def _match_tf_to_options(tf: str, options: list[str]) -> str | None:
    """Map hub TF to closest option in a section's allowed list."""
    if not options:
        return tf
    norm_opts = {normalize_tf(o): o for o in options}
    n = normalize_tf(tf)
    if n in norm_opts:
        return norm_opts[n]
    if n == "1w" and "1wk" in norm_opts:
        return norm_opts["1wk"]
    if n == "1wk" and "1w" in norm_opts:
        return norm_opts["1w"]
    return None


def filter_hub_tfs_to_options(hub_tfs: list[str], options: list[str]) -> list[str]:
    out: list[str] = []
    for tf in hub_tfs:
        matched = _match_tf_to_options(tf, options)
        if matched and matched not in out:
            out.append(matched)
    if out:
        return sort_timeframes(out)
    if options:
        return sort_timeframes(options[:3])
    return sort_timeframes(hub_tfs)


def get_ta_hub_market_bucket() -> str:
    return st.session_state.get("ta_hub_mtf_market", "groww")


def ta_hub_mtf_applies() -> bool:
    return bool(st.session_state.get("ta_hub_mtf_apply", True))


def get_ta_hub_mtf() -> dict[str, str]:
    stored = st.session_state.get("ta_hub_mtf")
    if isinstance(stored, dict) and all(r in stored for r in TA_ROLES):
        return {r: stored[r] for r in TA_ROLES}
    bucket = get_ta_hub_market_bucket()
    return dict(DEFAULT_TA_HUB_TFS.get(bucket, DEFAULT_TA_HUB_TFS["groww"]))


def hub_timeframe_list() -> list[str]:
    m = get_ta_hub_mtf()
    return sort_timeframes([m["LTF"], m["MTF"], m["HTF"]])


def get_ta_hub_role(role: str, fallback: str = "15m") -> str:
    return get_ta_hub_mtf().get(role, fallback)


def _init_role_defaults(bucket: str) -> None:
    defaults = DEFAULT_TA_HUB_TFS.get(bucket, DEFAULT_TA_HUB_TFS["groww"])
    for role in TA_ROLES:
        key = f"ta_hub_tf_{role}"
        if key not in st.session_state:
            st.session_state[key] = defaults[role]


def render_ta_hub_mtf_panel() -> None:
    """Render hub-level LTF · MTF · HTF selectors at the top of Technical Analysis."""
    if "ta_hub_mtf_apply" not in st.session_state:
        st.session_state["ta_hub_mtf_apply"] = True

    preset_labels = list(TA_MARKET_PRESETS.keys())
    if "ta_hub_mtf_preset" not in st.session_state:
        st.session_state["ta_hub_mtf_preset"] = preset_labels[0]

    st.markdown("### ⏱️ Hub Multi-Timeframe — LTF · MTF · HTF")
    st.caption(
        "Choose **low / medium / high** chart timeframes once — all Technical Analysis sections "
        "below use these defaults (minutes · hours · days). Override per section when needed."
    )

    top1, top2 = st.columns([2, 1])
    with top1:
        preset = st.selectbox(
            "Default preset",
            preset_labels,
            key="ta_hub_mtf_preset",
            help="Sets suggested LTF/MTF/HTF for India, US, or Crypto. You can still change each role.",
        )
    with top2:
        st.checkbox(
            "Apply hub timeframes to all TA sections",
            key="ta_hub_mtf_apply",
            help="When on, screeners use LTF + MTF + HTF from this panel unless a section overrides.",
        )

    bucket = TA_MARKET_PRESETS[preset]
    prev_bucket = st.session_state.get("ta_hub_mtf_market")
    if prev_bucket != bucket:
        st.session_state["ta_hub_mtf_market"] = bucket
        defaults = DEFAULT_TA_HUB_TFS[bucket]
        for role in TA_ROLES:
            st.session_state[f"ta_hub_tf_{role}"] = defaults[role]
    else:
        st.session_state["ta_hub_mtf_market"] = bucket

    _init_role_defaults(bucket)
    tf_opts = list(ALL_TA_HUB_TFS)

    c1, c2, c3 = st.columns(3)
    role_cols = (c1, c2, c3)
    tf_map: dict[str, str] = {}
    for col, role in zip(role_cols, TA_ROLES):
        with col:
            idx = tf_opts.index(st.session_state[f"ta_hub_tf_{role}"]) if st.session_state[f"ta_hub_tf_{role}"] in tf_opts else 0
            tf_map[role] = st.selectbox(
                ROLE_LABELS[role],
                tf_opts,
                index=idx,
                key=f"ta_hub_tf_{role}",
                format_func=tf_display_label,
            )

    st.session_state["ta_hub_mtf"] = tf_map
    ltf, mtf, htf = tf_map["LTF"], tf_map["MTF"], tf_map["HTF"]
    st.info(
        f"**Active hub stack:** LTF `{ltf}` · MTF `{mtf}` · HTF `{htf}` "
        f"({'applied to all sections' if ta_hub_mtf_applies() else 'sections use their own selectors'})"
    )
    st.markdown("---")


def render_ta_hub_badge(section_key: str = "") -> None:
    """Compact banner showing hub TFs when hub mode is on."""
    if not ta_hub_mtf_applies():
        return
    m = get_ta_hub_mtf()
    st.caption(
        f"Hub LTF·MTF·HTF: **{m['LTF']}** · **{m['MTF']}** · **{m['HTF']}**"
        + (f" (`{section_key}`)" if section_key else "")
    )


def render_ta_multiselect_timeframes(
    section_key: str,
    options: list[str],
    *,
    legacy_default: list[str] | None = None,
    label: str = "Timeframes",
    help_text: str = "",
    show_hub_note: bool = True,
) -> list[str]:
    """
    Multiselect that uses hub LTF+MTF+HTF when hub mode is on.
    Optional per-section override via expander.
    """
    hub_list = filter_hub_tfs_to_options(hub_timeframe_list(), options)
    default = legacy_default or hub_list

    if ta_hub_mtf_applies():
        if show_hub_note:
            render_ta_hub_badge(section_key)
            st.markdown(f"**{' · '.join(hub_list)}**")
        with st.expander("Override timeframes for this section", expanded=False):
            override = st.checkbox(
                "Use custom timeframes (ignore hub)",
                value=bool(st.session_state.get(f"{section_key}_tf_override", False)),
                key=f"{section_key}_tf_override",
            )
            if override:
                return st.multiselect(
                    label,
                    options,
                    default=default,
                    key=f"{section_key}_tfs_custom",
                    help=help_text,
                )
        return hub_list

    return st.multiselect(
        label,
        options,
        default=default,
        key=f"{section_key}_tfs",
        help=help_text or "Select one or more timeframes to scan.",
    )


def render_ta_role_selectboxes(
    section_key: str,
    options: list[str],
    *,
    role_order: tuple[str, ...] = ("HTF", "MTF", "LTF"),
    labels: dict[str, str] | None = None,
    format_func=None,
) -> dict[str, str]:
    """
    Three role selectboxes (HTF/MTF/LTF) synced to hub when hub mode is on.
    """
    hub = get_ta_hub_mtf()
    lbl = labels or ROLE_LABELS
    fmt = format_func or (lambda tf: tf)

    if ta_hub_mtf_applies():
        mapped = {
            role: _match_tf_to_options(hub[role], options) or hub[role]
            for role in TA_ROLES
        }
        render_ta_hub_badge(section_key)
        with st.expander("Override LTF · MTF · HTF for this section", expanded=False):
            override = st.checkbox(
                "Use custom role timeframes",
                value=bool(st.session_state.get(f"{section_key}_role_override", False)),
                key=f"{section_key}_role_override",
            )
            if override:
                out: dict[str, str] = {}
                cols = st.columns(len(role_order))
                for col, role in zip(cols, role_order):
                    with col:
                        idx = 0
                        val = mapped.get(role, options[0] if options else "15m")
                        if val in options:
                            idx = options.index(val)
                        out[role] = st.selectbox(
                            lbl.get(role, role),
                            options,
                            index=idx,
                            key=f"{section_key}_role_{role}",
                            format_func=fmt,
                        )
                return out
        return mapped

    out = {}
    cols = st.columns(len(role_order))
    for col, role in zip(cols, role_order):
        with col:
            val = hub.get(role, options[0] if options else "15m")
            idx = options.index(val) if val in options else 0
            out[role] = st.selectbox(
                lbl.get(role, role),
                options,
                index=idx,
                key=f"{section_key}_role_{role}",
                format_func=fmt,
            )
    return out


def render_ta_single_timeframe(
    section_key: str,
    options: list[str],
    *,
    role: str = "MTF",
    legacy_default: str | None = None,
    label: str = "Chart TF",
    help_text: str = "",
    widget_key: str | None = None,
    show_hub_note: bool = True,
) -> str:
    """Single selectbox mapped to a hub role (default MTF)."""
    hub_val = get_ta_hub_role(role, legacy_default or (options[0] if options else "15m"))
    matched = _match_tf_to_options(hub_val, options) or hub_val
    wkey = widget_key or f"{section_key}_{role.lower()}_tf"

    if ta_hub_mtf_applies():
        if show_hub_note:
            render_ta_hub_badge(section_key)
            st.markdown(f"**{matched}** ({role})")
        with st.expander("Override chart timeframe", expanded=False):
            override = st.checkbox(
                f"Use custom {label}",
                value=bool(st.session_state.get(f"{section_key}_single_tf_override", False)),
                key=f"{section_key}_single_tf_override",
            )
            if override:
                idx = options.index(matched) if matched in options else 0
                return st.selectbox(
                    label,
                    options,
                    index=idx,
                    key=f"{wkey}_custom",
                    help=help_text,
                )
        return matched if matched in options else (options[0] if options else hub_val)

    idx = options.index(matched) if matched in options else 0
    return st.selectbox(
        label,
        options,
        index=idx,
        key=wkey,
        help=help_text,
    )


def render_ta_entry_htf_pair(
    section_key: str,
    entry_options: list[str],
    htf_options: list[str],
    *,
    entry_default: str = "5m",
    htf_default: str = "15m",
    entry_label: str = "Entry TF",
    htf_label: str = "HTF bias",
    entry_help: str = "",
    htf_help: str = "",
) -> tuple[str, str]:
    """Entry + HTF pair mapped to hub LTF and HTF."""
    hub = get_ta_hub_mtf()
    entry_hub = _match_tf_to_options(hub["LTF"], entry_options) or entry_default
    htf_hub = _match_tf_to_options(hub["HTF"], htf_options) or htf_default

    if ta_hub_mtf_applies():
        render_ta_hub_badge(section_key)
        with st.expander("Override entry / HTF", expanded=False):
            override = st.checkbox(
                "Use custom entry & HTF",
                value=bool(st.session_state.get(f"{section_key}_entry_htf_override", False)),
                key=f"{section_key}_entry_htf_override",
            )
            if override:
                e_idx = entry_options.index(entry_hub) if entry_hub in entry_options else 0
                h_idx = htf_options.index(htf_hub) if htf_hub in htf_options else 0
                entry = st.selectbox(
                    entry_label, entry_options, index=e_idx,
                    key=f"{section_key}_entry_custom", help=entry_help,
                )
                htf = st.selectbox(
                    htf_label, htf_options, index=h_idx,
                    key=f"{section_key}_htf_custom", help=htf_help,
                )
                return entry, htf
        return (
            entry_hub if entry_hub in entry_options else entry_default,
            htf_hub if htf_hub in htf_options else htf_default,
        )

    e_idx = entry_options.index(entry_hub) if entry_hub in entry_options else (
        entry_options.index(entry_default) if entry_default in entry_options else 0
    )
    h_idx = htf_options.index(htf_hub) if htf_hub in htf_options else (
        htf_options.index(htf_default) if htf_default in htf_options else 0
    )
    entry = st.selectbox(entry_label, entry_options, index=e_idx, key=f"{section_key}_entry", help=entry_help)
    htf = st.selectbox(htf_label, htf_options, index=h_idx, key=f"{section_key}_htf", help=htf_help)
    return entry, htf


def resolve_entry_htf_from_hub(
    section_key: str,
    entry_options: list[str],
    htf_options: list[str],
    *,
    entry_default: str = "5m",
    htf_default: str = "15m",
) -> tuple[str | None, str | None, bool]:
    """Return (entry_tf, htf, from_hub) when hub mode applies without override."""
    if not ta_hub_mtf_applies() or st.session_state.get(f"{section_key}_entry_htf_override"):
        return None, None, False
    hub = get_ta_hub_mtf()
    entry = _match_tf_to_options(hub["LTF"], entry_options) or entry_default
    htf = _match_tf_to_options(hub["HTF"], htf_options) or htf_default
    return entry, htf, True


def render_ta_fixed_scan_note(fixed_tf: str, *, engine_label: str = "") -> None:
    """Note for sections with a fixed scan TF but hub context elsewhere."""
    if not ta_hub_mtf_applies():
        return
    m = get_ta_hub_mtf()
    extra = f" ({engine_label})" if engine_label else ""
    st.caption(
        f"Scan engine uses fixed **{fixed_tf}** bars{extra}. "
        f"Hub context: LTF `{m['LTF']}` · MTF `{m['MTF']}` · HTF `{m['HTF']}`."
    )
