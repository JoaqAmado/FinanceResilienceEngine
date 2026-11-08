"""Twin Runway: Tangerine "Resilience Rewired" engine (Streamlit).

    .venv/bin/streamlit run app.py

The judges' number always comes first and is computed exactly as the track brief
defines it. Reality checks are labelled options shown next to it, never instead of it.
Everything works offline: no API keys, no network.

The twist is typed in a chat (resilience.shock_parser): golden phrases, then cached LLM answers, then an LLM when one
is configured, then offline rules. The chat only sets the levers; the engine computes every number, and
resilience.consistency checks on every rerun that every number on screen agrees.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from resilience import (
    EI_2026_MAX_MONTHLY,
    LAID_OFF_EI,
    WAITING_WEEK_LABEL,
    Shock,
    account_flags,
    apply_shock,
    build_metrics,
    credit_advice,
    grey_zone_note,
    load_monthly,
    loan_in_trouble,
)
from resilience import evidence as EV
from resilience import shock_llm, warehouse
from resilience.consistency import check_view, money, rw_text
from resilience.shock_parser import (
    DEFAULT_TARGET,
    HINT_CHIPS,
    ONEOFF_AMT,
    ONEOFF_X,
    STATE_KEYS,
    follow_up_hints,
    judges_shock_from_state,
    parse_shock,
    shock_from_state,
    shock_to_state,
)
from resilience.view import build_view
from resilience.portfolio import build_all
from resilience.portfolio import lines as portfolio_lines
from resilience.warning import RULES, WINDOW_ROWS, account_light, backtest

st.set_page_config(page_title="Twin Runway · Tangerine Resilience Engine", page_icon="🍊", layout="wide")

ORANGE, SLATE, GREY = "#F47920", "#334155", "#94A3B8"
AQUA = "#12946A"  # a third series beside orange and slate (the web app's backup-plan aqua)
# summer-bank look, matching the web app: cream page with an apricot glow, white metric cards, navy numbers
st.markdown("""<style>
[data-testid='stApp']{background:radial-gradient(1200px 380px at 85% -120px,rgba(255,178,122,.35),transparent 70%),#FBF6EE}
[data-testid='stHeader']{background:transparent}
[data-testid='stMetric']{background:#FFFFFF;border:1px solid #EFE4D6;border-radius:16px;padding:.75rem 1rem;
  box-shadow:0 1px 2px rgba(19,35,63,.05),0 6px 18px -6px rgba(180,80,10,.12)}
[data-testid='stMetricValue']{font-size:1.65rem;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
[data-testid='stMetricLabel']{color:#46536B}
[data-testid='stColumn'] [data-testid='stElementContainer']:only-child:has(> [data-testid='stMetric']){flex:1 1 auto}
[data-testid='stColumn'] [data-testid='stElementContainer']:only-child > [data-testid='stMetric']{height:100%;box-sizing:border-box}
[data-testid='stBaseButton-secondary']{background:#FFFFFF}
[data-testid='stBaseButton-secondary']:hover{box-shadow:0 6px 16px -8px rgba(180,80,10,.35)}
</style>""", unsafe_allow_html=True)
REHEARSAL = {20331: "lender red flag", 20143: "spends more than comes in", 88269: "looks safe, isn't",
             98952: "retiree", 77743: "furnace wipes buffer"}


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


# ------------------------------------------------------------- state
# One source of truth: the lever keys below. The chat writes them, the Fine-tune sliders are bound to them, and the
# engine's Shock is built from them (shock_parser.shock_from_state) on every rerun.

ss = st.session_state
ss.setdefault("acct", 20331)
for k, v in shock_to_state(LAID_OFF_EI, DEFAULT_TARGET).items():
    ss.setdefault(k, v)
ss.setdefault("chat", [])
ss.setdefault("pct_lever", "income_ei")
ss.setdefault("chat_last", None)
for k in ("income_pct", "bills_pct", "extra", "oneoff_x", "oneoff_amt", "cut_pct"):
    ss[k] = float(ss[k])  # the sliders are float sliders; a test or an old session may hold an int
ss["target"] = int(ss["target"])

SOURCE_BADGE = {"golden": "golden phrase", "cache": "cached LLM answer", "rules": "offline rules", "none": "not parsed"}
EXAMPLES = [
    ("Job loss on EI", "Laid off, EI pays 55%"), ("Pay cut / reduced hours", "Pay cut 20%"),
    ("Income in dollars", "Income drops to $2,000 a month"), ("Partner's job", "Partner loses their job"),
    ("Household bills", "Bills up 15%"), ("Rent / new monthly cost", "Rent up $300 a month · baby, $900 a month more"),
    ("Rent to an amount", "Rent goes to $1,800 a month"), ("One-off in dollars", "A $2,500 car repair"),
    ("One-off in months of spending", "Furnace dies, repair = a month of spending"),
    ("Spending cut", "Cut spending 25%"), ("Target", "Must last 9 months"), ("Another customer", "Account 20143"),
    ("Reality checks", "With the 2026 EI cap · waiting week · keep pension · half-year spending · "
                       "bills by standing order"),
    ("Change the last percent", "Make it 20% instead"), ("Add to the one-off", "Add a $2,000 repair"),
    ("Undo one lever", "Remove the bills increase · no job loss"), ("Start again", "Reset"),
]


def lever_state() -> dict:
    return {k: ss[k] for k in STATE_KEYS}


def pick(acct: int) -> None:
    ss.acct = acct  # a new customer keeps the current shock


def _shown_row():
    m_ = metrics()
    a = ss.acct if ss.acct in m_.index else ss.get("last_acct", next(iter(REHEARSAL)))
    return int(a), m_.loc[a]


def source_badge(source: str) -> str:
    if source == "llm":
        return shock_llm.provider_name().capitalize()
    return SOURCE_BADGE.get(source, source)


def send(text: str | None = None) -> None:
    """Parse one chat message and write the result into the lever keys (a callback, so it runs before the widgets)."""
    text = ss.get("chat_box") if text is None else text
    if not text or not str(text).strip():
        return
    acct, row = _shown_row()
    res = parse_shock(str(text), row, shock_from_state(lever_state(), row), int(ss.target), metrics=metrics(),
                      last_pct_lever=ss.get("pct_lever"))
    ss.chat.append({"role": "user", "text": str(text)})
    reply = {"role": "assistant", "source": res.source, "warnings": list(res.warnings), "resolved": list(res.resolved),
             "hints": []}
    if res.clarify:
        reply["text"], reply["clarify"] = res.clarify, True
    else:
        if res.account_id is not None:
            ss.acct, acct, row = res.account_id, res.account_id, metrics().loc[res.account_id]
        state = shock_to_state(res.shock, res.target)
        for k, v in state.items():
            ss[k] = v
        ss.pct_lever = res.pct_lever
        ss.chat_last = {"shock": res.shock, "state": state, "account_id": acct, "understood_as": res.understood_as}
        reply["text"] = res.understood_as
        reply["hints"] = follow_up_hints(res, row)
    ss.chat.append(reply)


m = metrics()

# ------------------------------------------------------------------ header

st.markdown("<h2 style='margin-bottom:0'>🍊 Twin Runway <span style='color:#5B6474;font-weight:400'>"
            "· the judges' number, then the real world</span></h2>", unsafe_allow_html=True)
st.caption("Tangerine · Resilience Rewired · Sheridan Datathon 2026. Runway uses the judges' published formula; "
           "reality checks are labelled assumptions shown beside it.")

tab_live, tab_port, tab_method = st.tabs(["Live twist", "Portfolio discoveries", "Method & limits"])

# =============================================================== LIVE TWIST
with tab_live:
    c_id, _ = st.columns([1, 3])
    with c_id:
        acct = st.number_input("account_id", min_value=1, max_value=999_999, step=1, key="acct")
    st.write("Rehearsal accounts")
    cols = st.columns(len(REHEARSAL))  # full width, so the labels fit at 1440
    for c, (a, why) in zip(cols, REHEARSAL.items()):
        c.button(f"{a} · {why}", on_click=pick, args=(a,), width="stretch")

    if acct not in m.index:  # keep the last account on screen: st.stop() here would blank the other tabs
        shown = ss.get("last_acct", next(iter(REHEARSAL)))
        st.error(f"account_id {acct} is not in the data. IDs run {m.index.min()} to {m.index.max()} with gaps. "
                 f"Still showing account {shown}.")
        acct = shown
    ss["last_acct"] = acct
    r = m.loc[acct]

    # ---------------------------------------------------------- 1. know the customer
    st.subheader("1 · Know the customer")
    base = apply_shock(r, Shock())
    k = st.columns(4)
    k[0].metric("Money in (I) / mo", money(r.I))
    k[1].metric("Spending (S) / mo", money(r.S))
    k[2].metric("Buffer (B)", money(r.B), f"{r.B / r.S:.1f} months of spending" if r.S > 0 else None,
                delta_color="off", delta_arrow="off")
    k[3].metric("Runway today (months)", "120+" if base.no_shortfall else base.label,
                "no shortfall" if base.no_shortfall else None, delta_color="off", delta_arrow="off")
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

    # ---------------------------------------------------------- chat: the main input
    st.markdown("##### Describe the twist")
    c_now, c_reset = st.columns([5, 1])
    now_line = c_now.empty()
    c_reset.button("↺ Reset", on_click=send, args=("reset",), help="Back to no shock and a 6-month target",
                   width="stretch")
    chips = st.columns(len(HINT_CHIPS))
    for c, chip in zip(chips, HINT_CHIPS):
        c.button(chip, on_click=send, args=(chip,), width="stretch", key=f"chip_{chip}")
    with st.expander("What can I type?", expanded=False):
        st.dataframe(pd.DataFrame({"to set": [a for a, _ in EXAMPLES], "type": [b for _, b in EXAMPLES]}),
                     hide_index=True)
        st.caption("Each message changes only what it mentions; everything else keeps its current value. "
                   "Golden phrases and cached answers are instant and identical every time; anything else is read "
                   "by an LLM when one is configured, or by the offline rules.")
    for msg in ss.chat[-10:]:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.write(msg["text"])
                continue
            st.markdown(("❓ " if msg.get("clarify") else "**Understood as:** ") + msg["text"])
            for line in msg.get("resolved", []):
                st.caption("↳ " + line)
            for w in msg.get("warnings", []):
                st.caption("⚠️ " + w)
            st.caption(" · ".join([f"source: {source_badge(msg['source'])}", *msg.get("hints", [])]))
    st.chat_input("Type a twist, e.g. “rent up $300 a month”", key="chat_box", on_submit=send)

    # ---------------------------------------------------------- 2. take a shock
    st.subheader("2 · Take a shock")
    badge = st.empty()
    with st.expander("Fine-tune (the same levers as the chat)", expanded=False):
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            st.slider("Income kept (%)", 0.0, 100.0, step=1.0, key="income_pct", help="EI pays 55% of usual income")
            st.checkbox("This is a job loss on EI", key="job_loss", disabled=ss.income_pct >= 100,
                        help="Off = a pay cut or reduced hours: no EI cap, waiting week or pension checks")
        with s2:
            st.slider("Household bills up (%)", 0.0, 100.0, step=1.0, key="bills_pct")
            st.slider("Cut non-fixed spending (%)", 0.0, 100.0, step=1.0, key="cut_pct",
                      help="Card and cash spending the customer cuts")
        s3.number_input("Extra monthly cost ($)", min_value=0.0, step=100.0, key="extra",
                        help="Rent up $X/mo goes here; H is $0 on 1,225 accounts")
        with s4:
            st.radio("One-off cost", [ONEOFF_X, ONEOFF_AMT], key="oneoff_mode", horizontal=True)
            by_x = ss.oneoff_mode == ONEOFF_X
            st.slider("× S (typical spending)", 0.0, 12.0, step=0.25, key="oneoff_x", disabled=not by_x)
            st.number_input("One-off ($)", min_value=0.0, step=500.0, key="oneoff_amt", disabled=by_x)
        st.slider("Must survive (months)", 1, 24, key="target")
    N = int(ss.target)

    judge_part = judges_shock_from_state(lever_state())
    st.markdown("**Reality checks** (our assumptions; the judges' number never changes)")
    t = list(st.columns([1, 2.6, 1.2])) + list(st.columns(2))  # room for the waiting-week label at 1440
    job_loss = judge_part.is_job_loss
    t[0].toggle(f"2026 EI cap (${EI_2026_MAX_MONTHLY:,.0f}/mo)", key="t_cap",
                help="$729/week max, canada.ca, 2026", disabled=not job_loss)
    t[1].toggle(WAITING_WEEK_LABEL, key="t_ww", help="No EI for the first week", disabled=not job_loss)
    t[2].toggle("Keep pension on job loss", key="t_pens", disabled=not (job_loss and r.Pn > 0))
    t[3].toggle("Typical half-year spending", key="t_s6", help="Median 6-month spend ÷ 6, instead of the median month")
    t[4].toggle("Bills paid by standing order", key="t_bfb", disabled=not (r.H == 0 and r.H_SO > 0))

    # every number below comes from this one view; resilience.consistency re-derives it independently
    V = build_view(int(acct), r, lever_state(), chat=ss.chat_last)
    judge_shock, real_shock, judge, real, jan = V["judge_shock"], V["engine_shock"], V["judge"], V["real"], V["jan"]
    active = V["active"]
    now_line.markdown(f"**Current shock:** {V['understood_as']}")

    L, R = st.columns(2)
    with L:
        st.markdown("##### Judges' formula")
        st.metric("Runway", V["judge_text"])
        if V["verdict"] == "survives":
            st.success(f"SURVIVES {N} MONTH{'' if N == 1 else 'S'}", icon="✅")
        elif V["verdict"] == "overdrawn":
            st.error(f"ALREADY OVERDRAWN: the buffer was {money(r.B)} before any shock, so runway is 0", icon="🛑")
        elif V["verdict"] == "buffer_gone":
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
        if active and not (judge.no_shortfall or real.no_shortfall) and real.months != judge.months:
            delta = f"{real.months - judge.months:+.1f} mo vs judges"
        st.metric("Runway with selected checks", rw_text(real), delta)
        st.dataframe(pd.DataFrame({"each check alone": [n for n, _ in V["checks_alone"]],
                                   "runway": [v for _, v in V["checks_alone"]]}), hide_index=True)

    # ---------------------------------------------------------- 3. make a plan
    st.subheader("3 · Make a plan")
    st.caption("Plans use the judges' numbers" + (f" plus your reality checks: {', '.join(active)}." if active else "."))
    plan_shock, goal_shock, g, conv, lad = real_shock, V["goal_shock"], V["goal"], V["conv"], V["ladder"]

    P1, P2 = st.columns(2)
    with P1:
        st.markdown("##### Goal plan · normal times")
        st.metric(f"Job-loss-proof fund ({N} months)", money(g.target_buffer),
                  f"{money(g.shortfall)} to go" if g.shortfall else "already in place", delta_color="off",
                  delta_arrow="off")
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
        # name the shock the fund is actually sized on (goal_shock_for) and whether reality checks are in it
        kept = round(goal_shock.income_multiplier * 100)
        sized_on = ("passes this shock" if plan_shock.is_job_loss else
                    f"lasts {N} months of a job loss on EI 55%" if kept == 55 else
                    f"lasts {N} months of a job loss keeping {kept}% of money in")
        basis = "with your reality checks" if active else "under the judges' formula"
        st.caption(f"Conventional benchmark: 3 months of spending = {money(conv.target_buffer)}. "
                   f"The job-loss-proof target is exactly the buffer that {sized_on} {basis}.")
    with P2:
        st.markdown("##### Backup plan · if the shock hits")
        verdict = lad.verdict
        if loan_in_trouble(r):  # no new credit for a loan in arrears or default (same swap as the web app)
            verdict = (verdict.replace("income or credit", "income or a hardship deferral")
                       .replace("cash or credit", "cash or a hardship deferral"))
        st.write(f"**{verdict}**")
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

    story = V["story"]
    with st.container(border=True):
        st.markdown(f"**{story['headline']}**")
        st.write(story["what_changed"])
        for step in story["plan_steps"]:
            st.write("• " + step)
        reality = str(story["reality_check"]).rstrip(". ")
        st.caption(f"Reality check: {reality}. {story['caveat']} · Summary: template (offline)")

    issues = check_view(r, real_shock, N, V)
    if issues:
        badge.warning("**Numbers disagree** (shown, never hidden):\n\n" + "\n".join(f"- {i}" for i in issues),
                      icon="⚠️")
    else:
        badge.success("All numbers consistent", icon="✅")

# =========================================================== PORTFOLIO
with tab_port:
    P = portfolio()
    hl = P["headlines"].iloc[0]
    n = int(hl.accounts)
    a, b, c, d = st.columns(4)
    a.metric(f"Fail 6 mo on EI 55% ({int(hl.fail_6mo_ei55):,} of {n:,})", f"{hl.fail_6mo_ei55 / n:.1%}",
             help="Judges' formula")
    b.metric(f"… with the real 2026 EI cap ({int(hl.fail_6mo_ei55_cap2026):,})", f"{hl.fail_6mo_ei55_cap2026 / n:.1%}")
    c.metric(f"… on half-year spending ({int(hl.fail_6mo_ei55_S6):,})", f"{hl.fail_6mo_ei55_S6 / n:.1%}")
    d.metric("Median cut that rescues a failing customer", money(hl.median_min_cut_failing) + "/mo")

    EVD = backtest_evidence()
    es, lift, lines = EVD["summary"], EVD["lift"], EVD["lines"]
    st.markdown(f"#### 1 · The judges' test misses people: who went overdrawn in {es['label_year']}")
    fig = go.Figure()
    head = lift[lift.list_pct == EV.HEADLINE_LIST_PCT].iloc[0]
    for col, name, color, dash, place in (("light", "Early-warning light: most points, then lowest balance", ORANGE,
                                           "solid", "middle left"),
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
                                 ticktext=[f"{x}<br><span style='color:{GREY}'>buffer {mth:.1f} mo · ${b / 1000:.1f}k"
                                           "</span>"
                                           for x, mth, b in zip(ib.income_band, ib.median_buffer_months, ib.median_B)]))
    st.plotly_chart(fig)
    PL = portfolio_lines(P)
    st.caption(f"Monthly money in (I) bands. Under the judges' own EI twist the top band fails "
               f"{ib.fail_6mo_ei55_pct.iloc[-1] / ib.fail_6mo_ei55_pct.iloc[0]:.0f}× as often as the bottom; under the "
               f"real 2026 cap almost all of it fails. {PL['cushion']}")
    with st.expander("Show the numbers"):
        st.dataframe(ib[["income_band", "accounts", "fail_6mo_ei55_pct", "fail_6mo_ei55_cap2026_pct", "median_B",
                         "median_S", "median_buffer_months"]].rename(columns={
                             "income_band": "money in / mo", "fail_6mo_ei55_pct": "% fail, judges' EI 55%",
                             "fail_6mo_ei55_cap2026_pct": "% fail, 2026 EI cap", "median_B": "median buffer ($)",
                             "median_S": "median spending ($/mo)", "median_buffer_months": "median buffer (months)"}),
                     hide_index=True)

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
                   "Spending is lumpy: a few costly months a year that a median month never sees.")
        st.caption("Calendar caveat: here spending peaks in January and June, a pattern already in the original "
                   "PKDD'99 Czech data before it was re-dated, so it says nothing about Canadian seasons.")
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
        st.caption(f"{PL['quarter']} {PL['realistic_cuts']}")

    st.markdown("#### 6 · Overdrawn before the loan: a red flag, built into the loan labels")
    po = P["preloan_overdraft"].set_index("overdrawn_before_loan")
    st.dataframe(P["preloan_overdraft"], hide_index=True)
    st.caption(f"{int(po.loc['yes', 'defaulted (B/D)'])} of {int(po.loc['yes'].sum())} borrowers who were overdrawn "
               f"before their loan are labelled defaulted; none of the {int(po.loc['no', 'repaid or on track (A/C)'])} "
               "who repaid or are on track was overdrawn before it. That is built into how this dataset labels loans "
               "(CTU's published rule: if min(trans.balance) >= 0 then good else bad), so it is a red flag on the "
               "customer card, not evidence.")

# ============================================================ METHOD
with tab_method:
    st.markdown("""
**Judges' numbers** (from `monthly_summary.csv`): I = median money in · F = median(bills + insurance + loan payments) ·
S = median money out · B = mean average daily balance over the last 6 months · H = median household bills ·
P = loan payment if the loan is still running at the end of 2025.
Runway = (B − one-off) ÷ (spending after − income after), 0 if the buffer is gone, "no shortfall (120+)" if there is
no gap, capped at 120 and rounded to 1 decimal. EI 55% → income = 0.55 × I; bills +15% → spending = S + 0.15 × H.

**Reality checks** (labelled, never replacing the judges' number): 2026 EI maximum $729/week ≈ $3,159/month
(canada.ca) · one-week waiting period (normal rule, once the waiver ends: waived for new claims until Oct 9, 2027,
canada.ca) · pensions kept on job loss · typical half-year spending (median 6-month
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
            if "error" in sf:  # the connector's own message goes in the tooltip, not on screen
                st.warning("Snowflake isn't reachable from this laptop right now. Every number above comes from the "
                           "engine and is unaffected.")
                st.caption("The same SQL (sql/) also runs offline in DuckDB "
                           "(`python -m resilience.warehouse local-parity`).", help=f"Snowflake said: {sf['error']}")
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
