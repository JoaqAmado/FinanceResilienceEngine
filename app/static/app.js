// 90-day resilience plan: talks to the FastAPI backend, renders with plain DOM (textContent only).
"use strict";

const $ = (id) => document.getElementById(id);
const money = (x) => (x == null ? "–" : (x < 0 ? "-$" : "$") + Math.abs(x).toLocaleString("en-CA", { maximumFractionDigits: 0 }));
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

let activePreset = "job_loss_ei55";
let timer = null;
let accountIds = [];

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
  $("bills-out").textContent = `+${$("bills").value}%`;
  const o = Number($("oneoff").value);
  $("oneoff-out").textContent = o === 0 ? "none" : `${o} month${o === 1 ? "" : "s"} of spending`;
}

function setSlidersFromShock(s) {
  $("income").value = Math.round(s.income_factor * 100);
  $("bills").value = Math.round(s.bills_increase_pct * 100);
  $("oneoff").value = s.one_off_months_of_spending;
  $("duration").value = s.duration_months == null ? "" : String(s.duration_months);
  syncOutputs();
}

function markPreset(name) {
  activePreset = name;
  for (const b of $("presets").children) b.setAttribute("aria-pressed", String(b.dataset.preset === name));
}

function query() {
  if (activePreset) return `preset=${encodeURIComponent(activePreset)}`;
  const p = new URLSearchParams({
    income_factor: Number($("income").value) / 100,
    bills_increase_pct: Number($("bills").value) / 100,
    one_off_months_of_spending: Number($("oneoff").value),
  });
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
      if (r.status === 422) return showError("Account ID must be a whole number.");
      return showError(typeof d === "string" ? d : "Could not run that shock.");
    }
    if (activePreset) setSlidersFromShock(data.shock);
    render(data);
  } catch (e) {
    showError(`Could not reach the server: ${e.message}`);
  }
}

function loadSoon() {
  clearTimeout(timer);
  timer = setTimeout(load, 200);
}

// ── Render ──────────────────────────────────────────────────────────────────
function render(d) {
  const p = d.profile;
  $("results").hidden = false;
  $("shock-desc").textContent = `Account ${d.account_id} · shock: ${d.shock.description}`;

  const tiles = [
    ["Typical income (I)", money(p.typical_income), "/month"],
    ["Fixed costs (F)", money(p.typical_fixed_costs), "/month"],
    ["Typical spending (S)", money(p.typical_spending), "/month"],
    ["Household bills (H)", money(p.typical_household_bills), "/month"],
    ["Buffer (B)", money(p.buffer), "avg balance, last 6 months"],
    ["Loan payment (P)", money(p.running_loan_payment), "/month"],
  ];
  $("profile").replaceChildren(...tiles.map(([k, v, s]) => {
    const t = el("div", "tile");
    t.append(el("span", "label", k), el("strong", null, v), el("small", null, s));
    return t;
  }));

  $("rw-none").textContent = d.judge_runway_no_shock.label;
  $("rw-judge").textContent = d.judge_runway.label;
  $("rw-stress").textContent = d.stress_runway.label;
  $("rw-stress-note").textContent = `Lean month: ${money(p.lean_month_income_p25)} in`;

  $("notes").replaceChildren(...d.notes.map((n) => el("li", null, n)));
  $("warn-card").hidden = d.notes.length === 0;

  const plan = d.ninety_day_plan;
  $("prev-summary").textContent = plan.prevent.summary;
  renderChecks($("prev-checks"), plan.prevent.checkpoints);
  renderSteps($("prev-steps"), plan.prevent.steps);

  $("surv-before").textContent = plan.survive.runway_without_cuts;
  $("surv-after").textContent = plan.survive.runway_with_cuts;
  renderChecks($("surv-checks"), plan.survive.checkpoints);
  renderSteps($("surv-steps"), plan.survive.steps);

  drawChart(d.simulation.rows);
}

function renderChecks(box, checks) {
  box.hidden = checks.length === 0;
  box.replaceChildren(...checks.map((c) => {
    const n = el("div", "check" + (c.balance != null && c.balance < 0 ? " neg" : ""));
    n.append(el("span", "label", `Day ${c.day}`), el("strong", null, money(c.balance)), el("small", null, c.label));
    return n;
  }));
}

function renderSteps(list, steps) {
  list.replaceChildren(...steps.map((s) => {
    const li = el("li", s.tag);
    li.append(el("span", "when", s.week), el("span", "what", s.title), el("span", "why", s.detail));
    return li;
  }));
}

// ── Chart (inline SVG) ──────────────────────────────────────────────────────
function drawChart(rows) {
  const W = 720, H = 260, L = 64, R = 12, T = 12, B = 28;
  const base = rows.filter((r) => r.scenario === "baseline");
  const shock = rows.filter((r) => r.scenario === "shocked");
  const vals = rows.map((r) => r.balance).concat([0]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) hi = lo + 1;
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const maxM = Math.max(...rows.map((r) => r.month));
  const x = (m) => L + (m / maxM) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const add = (tag, attrs, text) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text != null) n.textContent = text;
    svg.appendChild(n);
    return n;
  };
  for (let i = 0; i <= 4; i++) {
    const v = lo + ((hi - lo) * i) / 4;
    add("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" });
    add("text", { x: L - 8, y: y(v) + 4, "text-anchor": "end" }, money(v));
  }
  for (let m = 0; m <= maxM; m += 6) add("text", { x: x(m), y: H - 8, "text-anchor": "middle" }, m === 0 ? "now" : `${m} mo`);
  add("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), class: "zero" });
  const path = (pts) => pts.map((r, i) => `${i ? "L" : "M"}${x(r.month).toFixed(1)},${y(r.balance).toFixed(1)}`).join("");
  add("path", { d: path(base), class: "base" });
  add("path", { d: path(shock), class: "shock" });
  $("chart").replaceChildren(svg);
}

// ── Boot ────────────────────────────────────────────────────────────────────
async function init() {
  const meta = await (await fetch("/api/meta")).json();
  const labels = {
    no_shock: "No shock", job_loss_ei55: "Job loss (EI 55%)", ei55_6_months: "EI for 6 months",
    bills_up_15: "Bills +15%", furnace_1_month: "Furnace repair", job_loss_plus_bills: "Job loss + bills",
  };
  $("presets").replaceChildren(...Object.entries(meta.presets).map(([name, desc]) => {
    const b = el("button", "chip", labels[name] || name);
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
  for (const id of ["income", "bills", "oneoff", "duration"]) {
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
