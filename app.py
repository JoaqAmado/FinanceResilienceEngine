"""Twin Runway: Tangerine "Resilience Rewired" engine (Streamlit).

    .venv/bin/streamlit run app.py

The judges' number always comes first and is computed exactly as the track brief
defines it. Reality checks are labelled options shown next to it, never instead of it.
Everything works offline: no API keys, no network.
"""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from resilience import (
    EI_2026_MAX_MONTHLY,
    Shock,
    account_flags,
    apply_shock,
    credit_advice,
    backup_ladder,
    build_metrics,
    calendar_path,
    goal_plan,
    goal_shock_for,
    grey_zone_note,
    load_monthly,
)
from resilience import evidence as EV
from resilience import llm, warehouse
from resilience.narrative import facts, template_story
from resilience.portfolio import build_all
from resilience.warning import RULES, WINDOW_ROWS, account_light, backtest

st.set_page_config(page_title="Twin Runway · Tangerine Resilience Engine", page_icon="🍊", layout="wide")

ORANGE, SLATE, GREY = "#F47920", "#334155", "#94A3B8"
AQUA = "#1BAF7A"  # a third series beside orange and slate (the web app's backup-plan aqua)
st.markdown("<style>[data-testid='stMetricValue']{font-size:1.65rem}</style>", unsafe_allow_html=True)
REHEARSAL = {20331: "lender red flag", 20143: "high earner", 88269: "looks safe, isn't",
             98952: "retiree", 77743: "furnace wipes buffer"}
_X = "× typical spending"
PRESETS = {
    "Laid off: EI 55%": dict(income_pct=55, bills_pct=0, extra=0.0, oneoff_mode=_X, oneoff_x=0.0, oneoff_amt=0.0, job_loss=True),
    "Furnace dies: 1× spending": dict(income_pct=100, bills_pct=0, extra=0.0, oneoff_mode=_X, oneoff_x=1.0, oneoff_amt=0.0, job_loss=False),
    "Job loss + bills +15%": dict(income_pct=55, bills_pct=15, extra=0.0, oneoff_mode=_X, oneoff_x=0.0, oneoff_amt=0.0, job_loss=True),
    # Custom starts from no shock at all, like the CLI: only the levers you set change anything
    "Custom": dict(income_pct=100, bills_pct=0, extra=0.0, oneoff_mode=_X, oneoff_x=0.0, oneoff_amt=0.0, job_loss=False),
}
LEVERS = tuple(PRESETS["Custom"])


# ------------------------------------------------------------------ data

@st.cache_data(show_spinner="Loading 4,500 accounts…")
def metrics() -> pd.DataFrame:
    return build_metrics()


@st.cache_data(show_spinner=False)
def monthly() -> pd.DataFrame:
    return load_monthly()


@st.cache_data(show_spinner="Computing portfolio findings…")
def portfolio() -> dict[str, pd.DataFrame]:
    return build_all(metrics())


@st.cache_data(show_spinner=False)
def warning_backtest():
    """The early-warning light's 2025 backtest tiers, computed once."""
    return backtest(monthly())


@st.cache_data(show_spinner="Computing the 2025 backtest…")
def backtest_evidence() -> dict:
    """The 2025 backtest evidence (resilience.evidence): chart tables and the lines both apps show."""
    ev = EV.build_evidence(monthly())
    return {k: ev[k] for k in ("lift", "irregular", "summary", "s6")} | {"lines": EV.lines(ev)}


@st.cache_data(ttl=3600, show_spinner="Checking the judges' numbers in Snowflake…")
def snowflake_check(settings_fingerprint: str) -> dict:
    """Snowflake vs the engine, counts only. Only called when credentials exist; a failure is cached
    too, so a dead network costs one wait, not one per rerun. The key changes with the credentials."""
    try:
        return warehouse.verify(metrics())
    except Exception as e:
        return {"error": f"{type(e).__name__}: {warehouse.scrub(str(e))}"}


def money(x: float) -> str:
    x = 0.0 if abs(x) < 0.5 else x
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def rw_text(res) -> str:
    if res.no_shortfall:
        return "No shortfall (120+)"
    return "120.0 mo (cap)" if res.months >= 120 else f"{res.months:.1f} mo"


def path_text(x: float) -> str:
    return "No shortfall (120+)" if math.isinf(x) else f"{x:.1f} mo"


# ------------------------------------------------------------- state

ss = st.session_state
ss.setdefault("acct", 20331)
ss.setdefault("preset", "Laid off: EI 55%")
for k, v in PRESETS["Laid off: EI 55%"].items():
    ss.setdefault(k, v)
ss.setdefault("target", 6)


def apply_preset() -> None:
    for k, v in PRESETS[ss.preset].items():
        ss[k] = v


def pick(acct: int) -> None:
    ss.acct = acct
    apply_preset()  # a new customer starts from the selected card's own values


def shock_from(v) -> Shock:
    """The Shock a set of lever values means (inactive one-off inputs don't count)."""
    by_x = v["oneoff_mode"] == _X
    return Shock(income_multiplier=v["income_pct"] / 100, bills_increase_pct=v["bills_pct"] / 100,
                 extra_monthly_cost=float(v["extra"]), one_off_cost=0.0 if by_x else float(v["oneoff_amt"]),
                 one_off_multiple_of_S=float(v["oneoff_x"]) if by_x else 0.0,
                 job_loss=bool(v["job_loss"]) and v["income_pct"] < 100)


def twist_label() -> str:
    """The card's name only while the applied shock still equals the card; otherwise say what is applied."""
    if ss.preset != "Custom" and shock_from(ss) == shock_from(PRESETS[ss.preset]):
        return ss.preset
    parts = []
    if ss.income_pct != 100:
        parts.append(f"{'job loss, EI' if ss.job_loss else 'income kept'} {ss.income_pct}%")
    if ss.bills_pct:
        parts.append(f"bills +{ss.bills_pct}%")
    if ss.extra:
        parts.append(f"+${ss.extra:,.0f}/mo")
    if ss.oneoff_mode == _X and ss.oneoff_x:
        parts.append(f"one-off {ss.oneoff_x:g}× spending")
    if ss.oneoff_mode != _X and ss.oneoff_amt:
        parts.append(f"one-off ${ss.oneoff_amt:,.0f}")
    return "Custom: " + (", ".join(parts) if parts else "no shock")


m = metrics()

# ------------------------------------------------------------------ header

st.markdown(f"<h2 style='margin-bottom:0'>🍊 Twin Runway <span style='color:{GREY};font-weight:400'>"
            "· the judges' number, then the real world</span></h2>", unsafe_allow_html=True)
st.caption("Tangerine · Resilience Rewired · Sheridan Datathon 2026. Runway uses the judges' published formula; "
           "reality checks are labelled assumptions shown beside it.")

tab_live, tab_port, tab_method = st.tabs(["Live twist", "Portfolio discoveries", "Method & limits"])

# =============================================================== LIVE TWIST
with tab_live:
    c_id, c_pick = st.columns([1, 3])
    with c_id:
        acct = st.number_input("account_id", min_value=1, max_value=999_999, step=1, key="acct",
                               on_change=apply_preset)
    with c_pick:
        st.write("Rehearsal accounts")
        cols = st.columns(len(REHEARSAL))
        for c, (a, why) in zip(cols, REHEARSAL.items()):
            c.button(f"{a} · {why}", on_click=pick, args=(a,), width="stretch")

    if acct not in m.index:
        st.error(f"account_id {acct} is not in the data. IDs run {m.index.min()} to {m.index.max()} with gaps.")
        st.stop()
    r = m.loc[acct]

    # ---------------------------------------------------------- 1. know the customer
    st.subheader("1 · Know the customer")
    base = apply_shock(r, Shock())
    k = st.columns(4)
    k[0].metric("Money in (I) / mo", money(r.I))
    k[1].metric("Spending (S) / mo", money(r.S))
    k[2].metric("Buffer (B)", money(r.B), f"{r.B / r.S:.1f} months of spending" if r.S > 0 else None,
                delta_color="off")
    k[3].metric("Runway today (months)", "120+" if base.no_shortfall else base.label,
                "no shortfall" if base.no_shortfall else None, delta_color="off")
    k2 = st.columns(4)
    k2[0].metric("Fixed costs (F) / mo", money(r.F))
    k2[1].metric("Household bills (H) / mo", money(r.H))
    k2[2].metric("Loan payment (P) / mo", money(r.P))
    k2[3].metric("Pension (median) / mo", money(r.Pn))
    owner = f"owner {r.owner_age:.0f}, {r.owner_gender}" if pd.notna(r.get("owner_age")) else "owner unknown"
    st.caption(f"{int(r.months_of_data)} months of history ({r.first_month} to {r.last_month}) · {owner} · "
               f"loan: {r.loan_status if pd.notna(r.loan_status) else 'none'}")
    for _, note in account_flags(r):
        st.warning(note, icon="⚠️")
    ew_bt = warning_backtest()
    ew = account_light(monthly(), int(acct), ew_bt)
    (st.warning if ew.points is not None and ew.points >= 2 else st.info)(ew.line, icon="🚦")
    with st.expander("Early-warning light · the 4 rules (a watch flag beside the runway, not a credit score)"):
        if ew.rules:
            st.dataframe(pd.DataFrame({
                "rule": [x.rule.label for x in ew.rules],
                "this account": [x.value_text for x in ew.rules],
                "fires when": [x.rule.fires_when for x in ew.rules],
                "fired": ["⚠️ fired" if x.fired else "not fired" for x in ew.rules],
            }), hide_index=True)
            st.caption(ew.spending_note)
        st.dataframe(pd.DataFrame({
            "points": [t.points for t in ew_bt.tiers],
            "accounts": [f"{t.accounts:,}" for t in ew_bt.tiers],
            f"went overdrawn in {ew_bt.label_year}": [f"{t.went_overdrawn:,}" for t in ew_bt.tiers],
            "share": [t.rate_text for t in ew_bt.tiers],
        }), hide_index=True)
        st.caption(f"Points = how many rules fire on the account's last {WINDOW_ROWS} months of data (the opening month is left out). "
                   f"Backtest: rules taken at the end of {ew_bt.snapshot} on the {ew_bt.population:,} accounts with "
                   f"{WINDOW_ROWS}+ months after the opening month that had never gone below zero and were still active in "
                   f"{ew_bt.label_year}; {ew_bt.events} of them went overdrawn in {ew_bt.label_year}. "
                   "The light never changes the judges' runway.")

    hist = monthly()
    h = hist[hist.account_id == acct]
    fig = go.Figure()
    fig.add_bar(x=h.month, y=h.money_in, name="Money in", marker_color=GREY, opacity=0.6)
    fig.add_bar(x=h.month, y=-h.money_out, name="Money out", marker_color=SLATE, opacity=0.6)
    fig.add_scatter(x=h.month, y=h.month_end_balance, name="Month-end balance", line=dict(color=ORANGE, width=3))
    fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0), barmode="relative",
                      legend=dict(orientation="h", y=1.15), yaxis_title="CAD")
    st.plotly_chart(fig)

    # ---------------------------------------------------------- 2. take a shock
    st.subheader("2 · Take a shock")
    c_card, c_reset = st.columns([5, 1])
    c_card.radio("Twist card", list(PRESETS), key="preset", horizontal=True, on_change=apply_preset)
    c_reset.button("↺ Reset card", on_click=apply_preset, help="Put every lever back to the selected card's values",
                   width="stretch")
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.slider("Income kept (%)", 0, 100, key="income_pct", help="EI pays 55% of usual income")
        st.checkbox("This is a job loss on EI", key="job_loss", disabled=ss.income_pct >= 100,
                    help="Off = a pay cut or reduced hours: no EI cap, waiting week or pension checks")
    s2.slider("Household bills up (%)", 0, 50, key="bills_pct")
    s3.number_input("Extra monthly cost ($)", min_value=0.0, step=100.0, key="extra",
                    help="Rent up $X/mo goes here; H is $0 on 1,225 accounts")
    with s4:
        st.radio("One-off cost", [_X, "$ amount"], key="oneoff_mode", horizontal=True)
        by_x = ss.oneoff_mode == _X
        st.slider("× S (typical spending)", 0.0, 3.0, step=0.25, key="oneoff_x", disabled=not by_x)
        st.number_input("One-off ($)", min_value=0.0, step=500.0, key="oneoff_amt", disabled=by_x)
    N = st.slider("Must survive (months)", 1, 12, key="target")

    judge_shock = Shock(income_multiplier=ss.income_pct / 100, bills_increase_pct=ss.bills_pct / 100,
                        extra_monthly_cost=ss.extra, one_off_cost=0.0 if by_x else ss.oneoff_amt,
                        one_off_multiple_of_S=ss.oneoff_x if by_x else 0.0,
                        job_loss=bool(ss.job_loss) and ss.income_pct < 100, name=twist_label())

    st.markdown("**Reality checks** (our assumptions; the judges' number never changes)")
    t = st.columns(5)
    job_loss = judge_shock.is_job_loss
    can_pension = job_loss and r.Pn > 0
    can_bills = r.H == 0 and r.H_SO > 0
    cap = t[0].toggle(f"2026 EI cap (${EI_2026_MAX_MONTHLY:,.0f}/mo)", key="t_cap",
                      help="$729/week max, canada.ca, 2026", disabled=not job_loss)
    ww = t[1].toggle("EI waiting week", key="t_ww", help="No EI for the first week", disabled=not job_loss)
    pens = t[2].toggle("Keep pension on job loss", key="t_pens", disabled=not can_pension)
    s6 = t[3].toggle("Typical half-year spending", key="t_s6",
                     help="Median 6-month spend ÷ 6, instead of the median month")
    bfb = t[4].toggle("Bills paid by standing order", key="t_bfb", disabled=not can_bills)
    # a disabled toggle keeps its old value, so only apply each check where it makes sense
    cap, ww, pens, bfb = cap and job_loss, ww and job_loss, pens and can_pension, bfb and can_bills
    real_shock = judge_shock.with_(income_cap_monthly=EI_2026_MAX_MONTHLY if cap else None, waiting_week=ww,
                                   pension_aware=pens, spending_basis="S6" if s6 else "S", bills_fallback=bfb)

    judge = apply_shock(r, judge_shock)
    real = apply_shock(r, real_shock)
    jan = calendar_path(r, judge_shock)  # "each check alone": January path on the judges' twist
    active = [name for name, on in (("2026 EI cap", cap), ("waiting week", ww), ("pension kept", pens),
                                    ("half-year spending", s6), ("bills by standing order", bfb)) if on]

    L, R = st.columns(2)
    with L:
        st.markdown("##### Judges' formula")
        st.metric("Runway", rw_text(judge))
        if judge.survives(N):
            st.success(f"SURVIVES {N} MONTHS", icon="✅")
        elif r.B <= 0:
            st.error(f"ALREADY OVERDRAWN: the buffer was {money(r.B)} before any shock, so runway is 0", icon="🛑")
        elif judge.buffer_left <= 0:
            st.error(f"BUFFER GONE: the one-off ({money(judge.one_off)}) is more than the buffer", icon="🛑")
        else:
            st.error(f"RUNS OUT IN {judge.months:.1f} MONTHS (needs {N})", icon="🛑")
        flow = f"gap {money(judge.gap)}/mo" if judge.gap > 0 else f"surplus {money(abs(judge.gap))}/mo"
        st.caption(f"twist: {judge_shock.name} · income after {money(judge.income_after)}/mo · "
                   f"spending after {money(judge.spending_after)}/mo · {flow} · buffer left {money(judge.buffer_left)}")
        note = grey_zone_note(judge, judge_shock)
        if note:
            st.info(note, icon="🌫️")
    with R:
        st.markdown("##### Reality check")
        delta = None
        if any((cap, ww, pens, s6, bfb)) and not (judge.no_shortfall or real.no_shortfall):
            delta = f"{real.months - judge.months:+.1f} mo vs judges"
        st.metric("Runway with selected checks", rw_text(real), delta)
        rows = [("Half-year spending", apply_shock(r, judge_shock.with_(spending_basis="S6"))),
                ("Starting in January (month by month)", jan)]
        if judge_shock.is_job_loss:
            rows += [("2026 EI cap", apply_shock(r, judge_shock.with_(income_cap_monthly=EI_2026_MAX_MONTHLY))),
                     ("2026 cap + waiting week",
                      apply_shock(r, judge_shock.with_(income_cap_monthly=EI_2026_MAX_MONTHLY, waiting_week=True)))]
            if r.Pn > 0:
                rows.append(("Pension kept", apply_shock(r, judge_shock.with_(pension_aware=True))))
        st.dataframe(pd.DataFrame({"each check alone": [n for n, _ in rows],
                                   "runway": [path_text(v) if isinstance(v, float) else rw_text(v) for _, v in rows]}),
                     hide_index=True)

    # ---------------------------------------------------------- 3. make a plan
    st.subheader("3 · Make a plan")
    st.caption("Plans use the judges' numbers" + (f" plus your reality checks: {', '.join(active)}." if active else "."))
    plan_shock = real_shock
    goal_shock = goal_shock_for(plan_shock)
    g = goal_plan(r, target_months=N, target_kind="ei_proof", shock=goal_shock)
    conv = goal_plan(r, target_months=3)
    lad = backup_ladder(r, plan_shock, target_months=N)

    P1, P2 = st.columns(2)
    with P1:
        st.markdown("##### Goal plan · normal times")
        st.metric(f"Job-loss-proof fund ({N} months)", money(g.target_buffer),
                  f"{money(g.shortfall)} to go" if g.shortfall else "already in place", delta_color="off")
        if g.shortfall == 0:
            st.write("Keep it ring-fenced in a separate **Tangerine Savings Account** named *Emergency Fund*.")
            if g.current_buffer < g.target_buffer:
                st.caption(f"Within rounding: {money(g.target_buffer - g.current_buffer)} under the exact target; "
                           f"the judges' runway rounds up to {N} months.")
        elif g.months_to_target:
            st.write(f"Move the normal surplus of **{money(g.monthly_surplus)}/mo** with the **Automatic Savings "
                     f"Program** into a **Savings Goal**: about **{g.months_to_target:g} months**.")
        else:
            st.write("The normal-month surplus can't close the gap. Make the backup steps a permanent budget change "
                     "and save the difference.")
        st.caption(f"Conventional benchmark: 3 months of spending = {money(conv.target_buffer)}. "
                   "The job-loss-proof target is exactly the buffer that passes this shock under the judges' formula.")
    with P2:
        st.markdown("##### Backup plan · if the shock hits")
        st.write(f"**{lad.verdict}**")
        if lad.rungs:
            stop = lad.first_sufficient if lad.first_sufficient is not None else len(lad.rungs) - 1
            st.dataframe(pd.DataFrame({
                "step": [x.step for x in lad.rungs[: stop + 1]],
                "saves / mo": [money(x.monthly_saving) for x in lad.rungs[: stop + 1]],
                "runway": [rw_text(x.result) for x in lad.rungs[: stop + 1]],
                f"≥ {N} mo": ["✅" if x.reaches_target else "" for x in lad.rungs[: stop + 1]],
            }), hide_index=True)
        if lad.cash_or_credit_needed:
            st.write(credit_advice(r, lad.cash_or_credit_needed, job_loss=plan_shock.is_job_loss))

    f = facts(int(acct), r, judge_shock, judge,
              {"half-year spending": apply_shock(r, judge_shock.with_(spending_basis="S6")),
               "starting in January": jan}, lad, g.target_buffer, g.shortfall, g.months_to_target, N,
              plan_basis=", ".join(active))
    use_ai = st.toggle("Write this summary with Gemini", key="t_ai", disabled=not llm.available(),
                       help="Rewords the computed numbers only; falls back to the template if a number doesn't match"
                       if llm.available() else "Set GEMINI_API_KEY to enable. The template works offline.")
    story, source = None, "template (offline)"
    if use_ai and llm.available():
        with st.spinner("Asking Gemini to reword the numbers…"):
            story, source = llm.gemini_story(f)
    story = story or template_story(f)
    with st.container(border=True):
        st.markdown(f"**{story['headline']}**")
        st.write(story["what_changed"])
        for step in story["plan_steps"]:
            st.write("• " + step)
        st.caption(f"Reality check: {story['reality_check']}. {story['caveat']} · Summary: {source}")

# =========================================================== PORTFOLIO
with tab_port:
    P = portfolio()
    hl = P["headlines"].iloc[0]
    n = int(hl.accounts)
    a, b, c, d = st.columns(4)
    a.metric(f"Fail 6 months on EI 55%, judges' formula ({int(hl.fail_6mo_ei55):,} of {n:,})", f"{hl.fail_6mo_ei55 / n:.1%}")
    b.metric(f"… with the real 2026 EI cap ({int(hl.fail_6mo_ei55_cap2026):,})", f"{hl.fail_6mo_ei55_cap2026 / n:.1%}")
    c.metric(f"… on half-year spending ({int(hl.fail_6mo_ei55_S6):,})", f"{hl.fail_6mo_ei55_S6 / n:.1%}")
    d.metric("Median cut that rescues a failing customer", money(hl.median_min_cut_failing) + "/mo")

    EVD = backtest_evidence()
    es, lift, lines = EVD["summary"], EVD["lift"], EVD["lines"]
    st.markdown(f"#### 1 · The judges' test misses people: who went overdrawn in {es['label_year']}")
    fig = go.Figure()
    head = lift[lift.list_pct == EV.HEADLINE_LIST_PCT].iloc[0]
    for col, name, color, dash, place in (("light", "Early-warning light", ORANGE, "solid", "middle left"),
                                          ("ei55_runway", "Judges' EI 55% runway, shortest first", SLATE, "dash",
                                           "bottom left"),
                                          ("buffer_months", "Buffer months, fewest first", AQUA, "dot", "top left")):
        fig.add_scatter(x=lift.list_pct, y=lift[col], name=name, mode="lines", line=dict(color=color, width=2.5, dash=dash),
                        customdata=lift.list_accounts, hovertemplate=f"{name}<br>%{{x}}% list (%{{customdata:,}} accounts): "
                        "%{y} caught<extra></extra>")
        fig.add_scatter(x=[head.list_pct], y=[head[col]], mode="markers+text", text=[f"{int(head[col])}"],
                        textposition=place, marker=dict(color=color, size=9, line=dict(color="white", width=2)),
                        textfont=dict(color=SLATE), showlegend=False, hoverinfo="skip")
    fig.add_vline(x=EV.HEADLINE_LIST_PCT, line=dict(color=GREY, dash="dot", width=1))
    fig.add_annotation(x=EV.HEADLINE_LIST_PCT, y=int(head.events), yanchor="top", showarrow=False, xshift=4,
                       xanchor="left", text=f"{EV.HEADLINE_LIST_PCT}% list ({int(head.list_accounts):,} accounts)",
                       font=dict(color=SLATE))
    fig.update_layout(height=360, margin=dict(l=0, r=24, t=10, b=0), legend=dict(orientation="h", y=1.12),
                      xaxis=dict(title="Watch-list size, % of the backtest accounts", ticksuffix="%"),
                      yaxis=dict(title=f"on the list, of {int(head.events)} overdrafts", range=[0, int(head.events)]),
                      hovermode="x unified")
    st.plotly_chart(fig)
    st.caption(f"{lines['passed']} {lines['lift']} Every score is taken at the {es['snapshot']} snapshot on the same "
               f"full months the light reads ({es['accounts']:,} accounts rated then and still active in "
               f"{es['label_year']}). The light is a watch flag beside the runway, not a credit score.")
    with st.expander("Show the numbers"):
        st.dataframe(lift.rename(columns={"list_pct": "list %", "list_accounts": "accounts on the list",
                                          "light": "light", "ei55_runway": "judges' EI 55% runway",
                                          "buffer_months": "buffer months", "events": "went overdrawn"}),
                     hide_index=True)

    st.markdown("#### 2 · A second finding: irregular money in")
    irr = EVD["irregular"]
    labels = [f"{'Irregular' if r.irregular_money_in == 'yes' else 'Steady'} money in, {r.judges_ei55} EI 55%"
              f"<br>{r.went_overdrawn:,} of {r.accounts:,}" for r in irr.itertuples()]
    fig = go.Figure(go.Bar(
        x=labels, y=irr.rate * 100, marker_color=[ORANGE if (r.irregular_money_in, r.judges_ei55) in
                                                  (("yes", "passes"), ("no", "fails")) else GREY for r in irr.itertuples()],
        error_y=dict(type="data", symmetric=False, array=(irr.ci_high - irr.rate) * 100,
                     arrayminus=(irr.rate - irr.ci_low) * 100, color=SLATE, thickness=1.5),
        hovertemplate="%{x}<br>%{y:.1f}% went overdrawn<extra></extra>"))
    fig.update_layout(height=320, yaxis_title=f"% overdrawn in {es['label_year']} (95% interval)",
                      margin=dict(l=0, r=0, t=10, b=0))
    fig.update_xaxes(type="category")
    st.plotly_chart(fig)
    irr_rule = next(r for r in RULES if r.code == "inc_cv")
    st.caption(f"{lines['irregular']} {lines['irregular_caveat']} Irregular = the light's rule "
               f"({irr_rule.fires_when}, over its {WINDOW_ROWS} months).")

    st.markdown("#### 3 · The more money comes in, the thinner the cushion")
    ib = P["income_bands"]
    fig = go.Figure()
    fig.add_bar(x=ib.income_band, y=ib.fail_6mo_ei55_pct, name="Judges' EI 55%", marker_color=SLATE,
                text=ib.fail_6mo_ei55_pct.map("{:.1f}%".format), textposition="outside")
    fig.add_bar(x=ib.income_band, y=ib.fail_6mo_ei55_cap2026_pct, name="Real 2026 EI cap", marker_color=ORANGE,
                text=ib.fail_6mo_ei55_cap2026_pct.map("{:.1f}%".format), textposition="outside")
    fig.update_layout(barmode="group", height=360, yaxis_title="% failing 6 months", yaxis_range=[0, 112],
                      margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1),
                      xaxis=dict(tickmode="array", tickvals=list(ib.income_band),
                                 ticktext=[f"{x}<br><span style='color:{GREY}'>buffer {mth:.1f} mo</span>"
                                           for x, mth in zip(ib.income_band, ib.median_buffer_months)]))
    st.plotly_chart(fig)
    st.caption("Monthly money in (I) bands. Under the judges' own EI twist the top band fails 16× as often as the "
               "bottom; under the real 2026 cap almost all of it fails. Spending scales with income; the buffer doesn't.")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 4 · A typical month isn't a typical half-year")
        cal = P["s6_calibration"]
        fig = go.Figure(go.Bar(x=cal.judge_runway_months, y=cal.fail_6mo_on_S6_pct, marker_color=ORANGE,
                               text=cal.fail_6mo_on_S6_pct.map("{:.1f}%".format), textposition="outside"))
        fig.update_layout(height=320, yaxis_title="% that still fail 6 months", yaxis_range=[0, 100],
                          xaxis_title="Judges' EI runway (months)", margin=dict(l=0, r=0, t=10, b=0))
        fig.update_xaxes(type="category")  # "6-8" etc. are bands, not dates
        st.plotly_chart(fig)
        st.caption("Accounts the judges' formula calls safe, re-run on each account's own typical half-year spending. "
                   "Spending peaks in January and June, which a median month never sees.")
        st.caption(lines["s6"])
    with col2:
        st.markdown("#### 5 · Most failing customers are one moderate change away")
        ch = P["cut_histogram"]
        fig = go.Figure(go.Bar(x=ch.cut_as_share_of_spending, y=ch.accounts, marker_color=SLATE,
                               text=ch.accounts, textposition="outside"))
        fig.update_layout(height=320, yaxis_title="EI-failing accounts", margin=dict(l=0, r=0, t=10, b=0),
                          xaxis_title="Monthly cut needed to get back to 6 months, as % of spending")
        fig.update_xaxes(type="category")
        st.plotly_chart(fig)

    st.markdown("#### 6 · Overdrawn before the loan → default, every time (in this data)")
    st.dataframe(P["preloan_overdraft"], hide_index=True)
    st.caption("27 of 27 borrowers who were overdrawn before their loan defaulted; none of the 606 who repaid or are "
               "on track ever went below zero. Small sample, and loan status looks tied to overdraft by construction: "
               "a red flag, not a rule.")

# ============================================================ METHOD
with tab_method:
    st.markdown("""
**Judges' numbers** (from `monthly_summary.csv`): I = median money in · F = median(bills + insurance + loan payments) ·
S = median money out · B = mean average daily balance over the last 6 months · H = median household bills ·
P = loan payment if the loan is still running at the end of 2025.
Runway = (B − one-off) ÷ (spending after − income after), 0 if the buffer is gone, "no shortfall (120+)" if there is
no gap, capped at 120 and rounded to 1 decimal. EI 55% → income = 0.55 × I; bills +15% → spending = S + 0.15 × H.

**Reality checks** (labelled, never replacing the judges' number): 2026 EI maximum $729/week ≈ $3,159/month
(canada.ca) · one-week waiting period · pensions kept on job loss · typical half-year spending (median 6-month
spend ÷ 6) · a month-by-month path from January using each account's own calendar-month spending ·
household bills paid by standing order.

**Limits.** The data is the PKDD'99 Czech bank dataset re-dated to 2020–2025 and expressed in CAD; money in counts all
inflows (74.9% cash deposits), so the EI cap view is a stress test, not a forecast. 76.4% of spending is cash of
unknown purpose, so we call it *non-fixed*, not *discretionary*. Edge cases (negative buffer, zero income or
spending, missing bills, stale accounts) are flagged on the customer card rather than hidden.

**Sources.** PKDD'99 Financial dataset (CTU Prague, relational.fel.cvut.cz/dataset/Financial), provided by Tangerine ·
Government of Canada, EI benefit amount (canada.ca/en/services/benefits/ei/ei-regular-benefit/benefit-amount.html).
""")
    with st.expander("Computed in Snowflake"):
        if warehouse.available():
            sf = snowflake_check(warehouse.fingerprint())
            if "error" in sf:
                st.warning(f"Snowflake check unavailable ({sf['error']}). Every number above comes from the engine "
                           "and is unaffected.")
            else:
                line = (f"Snowflake judges' numbers match the engine on {sf['metrics_matched']:,}/{sf['accounts']:,} "
                        "accounts")
                if warehouse.all_match(sf):
                    st.success(line)
                else:
                    st.warning(line)
                st.caption(f"EI 55% runway in SQL: {sf['runway_matched']:,}/{sf['accounts']:,} match · "
                           f"PORTFOLIO_SUMMARY: {sf['under_6_months_sql']:,} under 6 months (engine "
                           f"{sf['under_6_months_engine']:,}). Same SQL as sql/, which also runs offline "
                           "in DuckDB.")
        else:
            st.caption("No Snowflake credentials here: the same SQL (sql/) runs locally in DuckDB with "
                       "parity to the engine on all 4,500 accounts (`python -m resilience.warehouse local-parity`).")
