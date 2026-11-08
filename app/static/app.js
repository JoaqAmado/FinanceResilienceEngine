// Resilience plan page: talks to the FastAPI backend, renders with plain DOM (textContent only).
"use strict";

const $ = (id) => document.getElementById(id);
const money = (x) => (x == null ? "–" : (x < 0 ? "-$" : "$") + Math.abs(x).toLocaleString("en-CA", { maximumFractionDigits: 0 }));
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const PRESET_LABELS = { no_shock: "No shock", job_loss_ei55: "Job loss (EI 55%)" };

let activePreset = "job_loss_ei55";
let timer = null;
let accountIds = [];
let lastProfile = null;

// ── Errors ──────────────────────────────────────────────────────────────────
function showError(message, suggestions = []) {
  $("error-msg").textContent = message;
  $("error-suggest").replaceChildren(...suggestions.map((id) => {
    const b = el("button", "chip", String(id));
    b.type = "button";
    b.addEventListener("click", () => { $("account").value = id; load(); });
    return b;
  }));
  if (suggestions.length) $("error-suggest").prepend(el("span", null, "Try a nearby account:"));
  $("error").hidden = false;
}

// ── Controls ────────────────────────────────────────────────────────────────
function syncOutputs() {
  $("income-out").textContent = `${$("income").value}%`;
  updateHints();
}

// Live help under the two number boxes, using the current customer's own numbers.
function updateHints() {
  const p = lastProfile;
  if (!p) return;
  const v = Math.max(0, Number($("bills").value) || 0);
  const H = p.typical_household_bills;
  if ($("bills-unit").value === "pct") {
    $("bills-hint").textContent = H > 0
      ? `= ${money((v / 100) * H)}/month on this customer's ${money(H)} of bills (judges' card: 15%)`
      : "This customer has $0 household bills, so a % does nothing: switch to $ per month.";
  } else {
    $("bills-hint").textContent = `For reference, +15% of this customer's bills = ${money(0.15 * H)}/month`;
  }
  $("oneoff-hint").textContent = `Judges' furnace example = one month of spending: ${money(p.typical_spending)}`;
}

// After a quick-pick card runs, show its numbers in the boxes so the user can tweak from there.
function fillAdjusters(d) {
  $("income").value = Math.round(d.shock.income_factor * 100);
  $("duration").value = d.shock.duration_months == null ? "" : String(d.shock.duration_months);
  $("bills").value = 0;
  $("oneoff").value = 0;
  syncOutputs();
}

function markPreset(name) {
  activePreset = name;
  for (const b of $("presets").children) b.setAttribute("aria-pressed", String(b.dataset.preset === name));
}

function query() {
  if (activePreset) return `preset=${encodeURIComponent(activePreset)}`;
  const bills = Math.max(0, Number($("bills").value) || 0);
  const p = new URLSearchParams({
    income_factor: Number($("income").value) / 100,
    one_off_cost: Math.max(0, Number($("oneoff").value) || 0),
  });
  // % of bills uses the judges' own rule (S + pct x H); $ per month adds a fixed amount.
  if ($("bills-unit").value === "pct") p.set("bills_increase_pct", bills / 100);
  else p.set("bills_increase_amount", bills);
  if ($("duration").value) p.set("duration_months", $("duration").value);
  return p.toString();
}

async function load() {
  const id = $("account").value.trim();
  if (!id) return;
  $("error").hidden = true;
  try {
    const r = await fetch(`/api/plan/${encodeURIComponent(id)}?${query()}`);
    const data = await r.json();
    if (!r.ok) {
      const d = data.detail;
      if (d && d.suggestions) return showError(`Account ${id} doesn't exist. Account IDs have gaps, so most numbers aren't real accounts.`, d.suggestions);
      if (r.status === 422) return showError("Check the inputs: account ID must be a whole number and amounts can't be negative.");
      return showError(typeof d === "string" ? d : "Could not run that shock.");
    }
    if (activePreset) fillAdjusters(data);
    render(data);
  } catch (e) {
    showError(`Could not reach the server: ${e.message}`);
  }
}

function loadSoon() {
  clearTimeout(timer);
  timer = setTimeout(load, 300);
}

// ── Render ──────────────────────────────────────────────────────────────────
function tile(label, value, note) {
  const t = el("div", "tile");
  t.append(el("span", "label", label), el("strong", null, value));
  if (note) t.append(el("small", null, note));
  return t;
}

function render(d) {
  const p = d.profile;
  $("results").hidden = false;
  $("shock-desc").textContent = `Account ${d.account_id} · shock: ${d.shock.description}`;
  lastProfile = p;
  updateHints();

  $("profile").replaceChildren(
    tile("Typical income (I)", money(p.typical_income), "/month"),
    tile("Fixed costs (F)", money(p.typical_fixed_costs), "/month"),
    tile("Typical spending (S)", money(p.typical_spending), "/month"),
    tile("Household bills (H)", money(p.typical_household_bills), "/month"),
    tile("Buffer (B)", money(p.buffer), "avg balance, last 6 months"),
    tile("Loan payment (P)", money(p.running_loan_payment), "/month"),
  );

  $("rw-none").textContent = d.judge_runway_no_shock.label;
  $("rw-judge").textContent = d.judge_runway.label;
  $("rw-stress").textContent = d.stress_runway.label;
  $("rw-stress-note").textContent = `Lean month: ${money(p.lean_month_income_p25)} in`;

  $("notes").replaceChildren(...d.notes.map((n) => el("li", null, n)));
  $("warn-card").hidden = d.notes.length === 0;

  renderLookBack(d.resilience_plan.look_back);
  renderNext(d.resilience_plan.next_12_months);
  renderSavings(d.simulation);
  drawChart(d.simulation);
}

function renderLookBack(lb) {
  const s = lb.stats;
  $("lb-period").textContent = s.period ? `${s.period} · ${s.months} months of this account's own data` : "";
  $("lb-stats").replaceChildren(...(s.months ? [
    tile("Avg money in", money(s.avg_money_in), "/month"),
    tile("Avg money out", money(s.avg_money_out), "/month"),
    tile(s.total_net >= 0 ? "Saved over the period" : "Drawn from savings", money(Math.abs(s.total_net))),
    tile("Months in the red", `${s.deficit_months} of ${s.months}`, "spent more than came in"),
  ] : []));

  $("lb-rows").replaceChildren(...lb.months.map((m) => {
    const tr = el("tr");
    const flags = [];
    if (m.is_lean_month) flags.push("lean month");
    if (m.days_below_zero) flags.push(`${m.days_below_zero} days overdrawn`);
    tr.append(
      el("th", null, m.month),
      el("td", "num", money(m.money_in)),
      el("td", "num", money(m.money_out)),
      el("td", "num " + (m.net < 0 ? "neg" : "pos"), money(m.net)),
      el("td", "num", money(m.avg_balance)),
      el("td", "flags", flags.join(" · ")),
    );
    tr.firstChild.scope = "row";
    return tr;
  }));

  $("lb-lessons").replaceChildren(...lb.lessons.map((l) => {
    const li = el("li", `lesson ${l.tag}`);
    li.append(el("strong", null, l.title), el("span", null, l.detail));
    return li;
  }));
}

function renderNext(nx) {
  $("nx-before").textContent = nx.runway_without_cuts;
  $("nx-after").textContent = nx.runway_with_plan;
  $("phases").replaceChildren(...nx.phases.map((ph) => {
    const box = el("article", "phase");
    const head = el("header");
    head.append(el("span", "when", ph.when), el("h3", null, ph.title));
    const list = el("ul", "steps");
    list.append(...ph.steps.map((s) => {
      const li = el("li", s.tag);
      li.append(el("span", "what", s.title), el("span", "why", s.detail));
      return li;
    }));
    box.append(head, list);
    if (ph.checkpoint) {
      const c = ph.checkpoint;
      const cp = el("div", "checkpoint");
      cp.append(el("span", "label", `Balance at month ${c.month}`));
      const row = el("div", "cp-row");
      const a = el("div", c.without_cuts < 0 ? "neg" : "");
      a.append(el("small", null, "no cuts"), el("strong", null, money(c.without_cuts)));
      const b = el("div", c.with_plan < 0 ? "neg" : "");
      b.append(el("small", null, "with the plan"), el("strong", null, money(c.with_plan)));
      row.append(a, b);
      cp.append(row);
      box.append(cp);
    }
    return box;
  }));
}

// ── "What the plan saves": headline numbers ─────────────────────────────────
function renderSavings(sim) {
  const at = (s, m) => (sim.rows.find((r) => r.scenario === s && r.month === m) || {}).balance;
  const last = Math.max(...sim.rows.map((r) => r.month));
  const plan12 = at("with_plan", last), shock12 = at("shocked", last);
  const saved = plan12 - shock12;
  const s0 = sim.months_until_zero_shocked, p0 = sim.months_until_zero_with_plan;
  const startsNegative = at("shocked", 0) < 0;

  $("kpi-saved").textContent = money(saved);
  $("kpi-saved-note").textContent = saved > 0.5
    ? `That's ${money(saved / last)} a month that stays in the account instead of being spent.`
    : "Nothing discretionary to cut here: the levers are fixed costs and income.";

  let lasts, note;
  if (startsNegative) { lasts = "Already overdrawn"; note = "Step 1 is getting back above zero."; }
  else if (s0 == null) { lasts = `${last}+ months`; note = "The balance stays above zero all year, with or without cuts."; }
  else if (p0 == null) { lasts = `Month ${s0} → ${last}+`; note = `Without cuts the money runs out in month ${s0}. With the plan it lasts the whole year.`; }
  else if (p0 > s0) { lasts = `Month ${s0} → ${p0}`; note = `The plan buys ${p0 - s0} more month${p0 - s0 > 1 ? "s" : ""} before the money runs out.`; }
  else { lasts = `Month ${s0}`; note = "The cuts aren't enough to move the date: lower fixed costs or add income."; }
  $("kpi-lasts").textContent = lasts;
  $("kpi-lasts-note").textContent = note;

  $("kpi-m12").textContent = money(plan12);
  $("kpi-m12-note").textContent = `vs ${money(shock12)} without cuts · ${money(at("baseline", last))} with no shock`;
}

// ── Chart (inline SVG): three lines, shaded savings gap, run-out markers, hover ──
const SERIES = [
  { key: "baseline", cls: "base", name: "No shock" },
  { key: "shocked", cls: "shock", name: "Shock, no cuts" },
  { key: "with_plan", cls: "plan", name: "Shock, with the plan" },
];

function drawChart(sim) {
  const rows = sim.rows;
  const W = 760, H = 300, L = 70, R = 128, T = 16, B = 30;
  const by = Object.fromEntries(SERIES.map((s) => [s.key, rows.filter((r) => r.scenario === s.key)]));
  const vals = rows.map((r) => r.balance).concat([0]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) hi = lo + 1;
  const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
  const maxM = Math.max(...rows.map((r) => r.month));
  const x = (m) => L + (m / maxM) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const add = (tag, attrs, text, parent = svg) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text != null) n.textContent = text;
    parent.appendChild(n);
    return n;
  };

  // Overdrawn zone (below zero), labelled so the tint never carries meaning alone
  if (lo < 0) {
    add("rect", { x: L, y: y(0), width: W - L - R, height: y(lo) - y(0), class: "debt" });
    add("text", { x: L + 6, y: y(lo) - 6, class: "debt-label" }, "Below zero: overdrawn");
  }
  for (let i = 0; i <= 4; i++) {
    const v = lo + ((hi - lo) * i) / 4;
    add("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" });
    add("text", { x: L - 8, y: y(v) + 4, "text-anchor": "end" }, money(v));
  }
  for (let m = 0; m <= maxM; m += 3) add("text", { x: x(m), y: H - 8, "text-anchor": "middle" }, m === 0 ? "now" : `month ${m}`);
  add("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), class: "zero" });

  // Money kept by the plan: the area between "no cuts" and "with the plan"
  const shock = by.shocked, plan = by.with_plan;
  const saved = plan.length ? plan[plan.length - 1].balance - shock[shock.length - 1].balance : 0;
  if (saved > 0.5) {
    const top = plan.map((r) => `${x(r.month).toFixed(1)},${y(r.balance).toFixed(1)}`);
    const bottom = shock.slice().reverse().map((r) => `${x(r.month).toFixed(1)},${y(r.balance).toFixed(1)}`);
    add("polygon", { points: top.concat(bottom).join(" "), class: "saved" });
    const mid = Math.round(maxM * 0.7);
    const pm = plan.find((r) => r.month === mid), sm = shock.find((r) => r.month === mid);
    if (pm && sm && y(sm.balance) - y(pm.balance) > 18) {
      add("text", { x: x(mid), y: (y(pm.balance) + y(sm.balance)) / 2 + 4, "text-anchor": "middle", class: "saved-label" },
        `${money(saved)} kept by the plan`);
    }
  }

  // Lines
  for (const s of SERIES) {
    const pts = by[s.key];
    if (!pts.length) continue;
    add("path", { d: pts.map((r, i) => `${i ? "L" : "M"}${x(r.month).toFixed(1)},${y(r.balance).toFixed(1)}`).join(""), class: s.cls });
  }

  // Where the money runs out (first month below zero), on the two shock lines
  const runouts = [["shocked", "shock", sim.months_until_zero_shocked], ["with_plan", "plan", sim.months_until_zero_with_plan]];
  const usedSlots = [];
  for (const [key, cls, m] of runouts) {
    if (m == null || !by[key].length || by[key][0].balance < 0) continue;
    const r = by[key].find((p) => p.month === m);
    if (!r) continue;
    add("circle", { cx: x(m), cy: y(r.balance), r: 5, class: `runout ${cls}` });
    let ly = y(0) - 10;
    while (usedSlots.some((u) => Math.abs(u - ly) < 14)) ly -= 14;
    usedSlots.push(ly);
    add("text", { x: x(m), y: ly, "text-anchor": "middle", class: "runout-label" }, `Out of money · month ${m}`);
  }

  // Direct end labels (pushed apart so they never overlap)
  const ends = SERIES.filter((s) => by[s.key].length).map((s) => {
    const r = by[s.key][by[s.key].length - 1];
    return { s, v: r.balance, y: y(r.balance) };
  }).sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 28) ends[i].y = ends[i - 1].y + 28;
  for (const e of ends) {
    add("text", { x: W - R + 8, y: e.y, class: "end-label" }, e.s.name);
    add("text", { x: W - R + 8, y: e.y + 13, class: "end-label sub" }, money(e.v));
  }

  // Hover / keyboard: crosshair + one tooltip listing every series at that month
  const hover = add("g", { visibility: "hidden" });
  const cross = add("line", { y1: T, y2: H - B, class: "cross" }, null, hover);
  const dots = SERIES.map((s) => add("circle", { r: 4, class: `hover-dot runout ${s.cls}` }, null, hover));
  const tip = $("chart-tip");
  let current = maxM;
  const show = (m) => {
    m = Math.max(0, Math.min(maxM, m));
    current = m;
    hover.setAttribute("visibility", "visible");
    cross.setAttribute("x1", x(m)); cross.setAttribute("x2", x(m));
    tip.replaceChildren(el("div", "tip-h", m === 0 ? "Now" : `Month ${m}`));
    SERIES.forEach((s, i) => {
      const r = by[s.key].find((p) => p.month === m);
      if (!r) return;
      dots[i].setAttribute("cx", x(m)); dots[i].setAttribute("cy", y(r.balance));
      const row = el("div", "tip-r");
      const key = el("i", "key");
      key.style.background = `var(--line-${s.cls})`;
      row.append(key, el("strong", null, money(r.balance)), el("span", null, s.name));
      tip.append(row);
    });
    tip.hidden = false;
    const box = $("chart").getBoundingClientRect();
    const px = (x(m) / W) * box.width;
    tip.style.left = `${Math.min(Math.max(px + 12, 0), Math.max(0, box.width - tip.offsetWidth))}px`;
  };
  const hide = () => { hover.setAttribute("visibility", "hidden"); tip.hidden = true; };
  svg.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const vx = ((e.clientX - box.left) / box.width) * W;
    show(Math.round(((vx - L) / (W - L - R)) * maxM));
  });
  svg.addEventListener("pointerleave", hide);
  const c = $("chart");
  c.onkeydown = (e) => {
    if (e.key === "ArrowRight") { show(current + 1); e.preventDefault(); }
    if (e.key === "ArrowLeft") { show(current - 1); e.preventDefault(); }
  };
  c.onfocus = () => show(current);
  c.onblur = hide;
  c.replaceChildren(svg);
}

// ── Boot ────────────────────────────────────────────────────────────────────
async function init() {
  const meta = await (await fetch("/api/meta")).json();
  $("presets").replaceChildren(...Object.entries(meta.presets).map(([name, desc]) => {
    const b = el("button", "chip", PRESET_LABELS[name] || name);
    b.type = "button"; b.dataset.preset = name; b.title = desc;
    b.addEventListener("click", () => { markPreset(name); load(); });
    return b;
  }));
  $("showcase").replaceChildren(...Object.entries(meta.showcase).map(([name, id]) => {
    const b = el("button", "chip", name);
    b.type = "button"; b.title = `Account ${id}`;
    b.addEventListener("click", () => { $("account").value = id; load(); });
    return b;
  }));
  for (const id of ["income", "bills", "bills-unit", "oneoff", "duration"]) {
    $(id).addEventListener("input", () => { syncOutputs(); markPreset(null); loadSoon(); });
  }
  $("random").addEventListener("click", () => {
    if (!accountIds.length) return;
    $("account").value = accountIds[Math.floor(Math.random() * accountIds.length)];
    load();
  });
  fetch("/api/accounts").then((r) => r.json()).then((ids) => {
    accountIds = ids;
    $("id-hint").textContent = `${ids.length.toLocaleString()} accounts, IDs from ${ids[0]} to ${ids[ids.length - 1]} (with gaps). Use 🎲 or type and pick from the list.`;
    $("account-list").replaceChildren(...ids.map((id) => { const o = document.createElement("option"); o.value = id; return o; }));
  }).catch(() => { $("id-hint").textContent = ""; });
  $("account").addEventListener("change", load);
  $("account").addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });
  $("print").addEventListener("click", () => window.print());
  markPreset(activePreset);
  syncOutputs();
  load();
}

init().catch((e) => showError(`Could not reach the server: ${e.message}`));
