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

const PRESET_LABELS = {
  no_shock: "No shock", job_loss_ei55: "Job loss (EI 55%)", bills_up_15: "Bills +15%", furnace_1_month: "Furnace repair",
};

let activePreset = "job_loss_ei55";
let timer = null;
let accountIds = [];

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
}

// After a twist card runs, show its numbers in the adjusters so the user can tweak from there.
function fillAdjusters(d) {
  $("income").value = Math.round(d.shock.income_factor * 100);
  $("duration").value = d.shock.duration_months == null ? "" : String(d.shock.duration_months);
  $("bills").value = Math.round(d.judge_runway.spending_after - d.profile.typical_spending);
  $("oneoff").value = Math.round(d.judge_runway.one_off_cost);
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
    bills_increase_amount: Math.max(0, Number($("bills").value) || 0),
    one_off_cost: Math.max(0, Number($("oneoff").value) || 0),
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
  $("bills-hint").textContent = `+15% of this account's bills = ${money(0.15 * p.typical_household_bills)}`;
  $("oneoff-hint").textContent = `Furnace card = one month of spending, ${money(p.typical_spending)}`;

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
  drawChart(d.simulation.rows);
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

// ── Chart (inline SVG) ──────────────────────────────────────────────────────
function drawChart(rows) {
  const W = 720, H = 260, L = 64, R = 12, T = 12, B = 28;
  const series = ["baseline", "shocked", "with_plan"].map((s) => [s, rows.filter((r) => r.scenario === s)]);
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
  for (let m = 0; m <= maxM; m += 3) add("text", { x: x(m), y: H - 8, "text-anchor": "middle" }, m === 0 ? "now" : `${m} mo`);
  add("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), class: "zero" });
  const cls = { baseline: "base", shocked: "shock", with_plan: "plan" };
  for (const [name, pts] of series) {
    if (!pts.length) continue;
    const d = pts.map((r, i) => `${i ? "L" : "M"}${x(r.month).toFixed(1)},${y(r.balance).toFixed(1)}`).join("");
    add("path", { d, class: cls[name] });
  }
  $("chart").replaceChildren(svg);
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
