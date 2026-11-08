/**
 * Free-text twists -> a Shock, deterministically: port of resilience/shock_parser.py (the offline part).
 *
 * The web app is keyless, so it has the golden table and the offline rule parser, in that order. Every backend
 * returns the same intent (what the user said); validateAndBuild turns it into a Shock for the selected account:
 * account-relative maths, clamps, reality-check guards and warnings happen there, in code. `understoodAs` and
 * `resolved` are built from the final Shock and the account, never from the message.
 *
 * test/shock.test.ts requires every output to equal the Python parser's (test/shock_vectors.json, written by
 * scripts/export_shock_vectors.py), string for string. A change to the Python file needs the same change here.
 */
import { DOUBLE_WHAMMY, EI_2026_MAX_MONTHLY, FURNACE, LAID_OFF_EI, applyShock, isJobLoss, makeShock, survives,
  withShock } from './core';
import goldenFile from './goldenTwists.json';
import { money } from './narrative';
import { pyG, pyMax, pyMin, pyRound, rint } from './pyformat';
import type { Account, Shock } from './types';

export const DEFAULT_TARGET = 6;
export const MONEY_MAX = 1_000_000;
export const ONEOFF_MULTIPLE_MAX = 12;
export const TARGET_MIN = 1;
export const TARGET_MAX = 24;

export const HINT_CHIPS = [
  'Laid off, EI pays 55%',
  'Furnace dies, repair = a month of spending',
  'Job loss on EI and bills up 15%',
  'Income drops to $2,000 a month',
  'Rent up $300 a month',
  'Must last 9 months',
] as const;
export const SUGGESTIONS = ['Laid off, EI pays 55%', 'Rent up $300 a month', 'Must last 9 months'] as const;

// ------------------------------------------------------------------ numbers

const WORD_NUMBERS: Record<string, number> = {
  zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11,
  twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18, nineteen: 19,
  twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, seventy: 70, eighty: 80, ninety: 90, hundred: 100,
};
const TENS = 'twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety';
const UNITS = 'one|two|three|four|five|six|seven|eight|nine';
const ALL_WORDS = Object.keys(WORD_NUMBERS)
  .map((w, i) => [w, i] as const)
  .sort((a, b) => b[0].length - a[0].length || a[1] - b[1])
  .map(([w]) => w)
  .join('|');
// a number word only counts when a unit follows it, so "one-off" stays a word
const WORD_NUMBER = new RegExp(
  String.raw`\b(?:(${TENS})[\s-](${UNITS})|(${ALL_WORDS}))\b(?=\s*(?:%|percent|per cent|pct|months?\b|-month|x\b|×|times\b|thousand\b|dollars\b))`,
  'g',
);

function wordsToDigits(text: string): string {
  return text.replace(WORD_NUMBER, (_m, t: string | undefined, u: string | undefined, w: string | undefined) =>
    t ? String(WORD_NUMBERS[t] + WORD_NUMBERS[u as string]) : String(WORD_NUMBERS[w as string]),
  );
}

/** THE percent conversion (resilience.shock_parser.coerce_pct): a fraction, or throws. */
export function coercePct(value: unknown): number {
  if (typeof value === 'boolean') throw new Error(`not a percent: ${String(value)}`);
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error(`not a percent: ${value}`);
    return value >= 0 && value <= 1 ? value : value / 100;
  }
  if (value === null || value === undefined) throw new Error('not a percent');
  const text = wordsToDigits(String(value).trim().toLowerCase());
  const m = /^(?:([+-]?\d+(?:\.\d+)?|[+-]?\.\d+)\s*(%|percent|per cent|pct)?)$/.exec(text);
  if (!m) throw new Error(`not a percent: ${String(value)}`);
  const x = Number.parseFloat(m[1]);
  return m[2] ? x / 100 : coercePct(x);
}

/** Dollars from "$2,500", "2.5k", "$2500/mo", "2 thousand" or a number; throws when there is none. */
export function parseMoney(value: unknown): number {
  if (typeof value === 'boolean') throw new Error(`not an amount: ${String(value)}`);
  if (typeof value === 'number') return value;
  const text = String(value).trim().toLowerCase().replaceAll(',', '');
  const m = /^(?:\$?\s*(\d+(?:\.\d+)?|\.\d+)\s*(k|thousand)?\s*(?:\/\s*mo(?:nth)?|a month|per month|monthly)?)$/.exec(text);
  if (!m) throw new Error(`not an amount: ${String(value)}`);
  return Number.parseFloat(m[1]) * (m[2] ? 1000 : 1);
}

/** The golden-table key: lowercase, punctuation stripped (numbers kept whole), spaces collapsed. */
export function normalize(message: string): string {
  let t = String(message).toLowerCase().replaceAll('×', 'x').replaceAll('’', "'");
  t = t.replace(/(?<=\d),(?=\d{3}\b)/g, '');
  t = t.replace(/(?<=\d)\.(?=\d)/g, '\x00');
  t = t.replace(/[^\p{L}\p{N}_\s%\x00]/gu, ' ');
  t = t.replaceAll('\x00', '.').replaceAll('_', ' ');
  return t.replace(/\s+/gu, ' ').trim();
}

// ------------------------------------------------------------------ the intent schema

export const INCOME_KINDS = ['none', 'job_loss_ei', 'drop_pct', 'keep_pct', 'pay_cut_pct', 'to_amount',
  'partner_job_loss', 'restore'] as const;
const BILLS_KINDS = ['none', 'increase_pct', 'reset'] as const;
const MONTHLY_KINDS = ['none', 'set', 'add', 'rent_to', 'reset'] as const;
const ONE_OFF_KINDS = ['none', 'set_amount', 'add_amount', 'months_of_spending', 'add_months_of_spending',
  'reset'] as const;
const CUT_KINDS = ['none', 'set_pct', 'reset'] as const;
const TARGET_KINDS = ['none', 'set'] as const;
const EDIT_KINDS = ['none', 'reset_all', 'set_last_percent'] as const;
const CHECK_VALUES = ['unchanged', 'on', 'off'] as const;
export const CHECKS = ['ei_cap', 'waiting_week', 'keep_pension', 'half_year_spending',
  'bills_by_standing_order'] as const;
type CheckName = (typeof CHECKS)[number];
type Unit = 'pct' | 'money' | 'months';

const SECTIONS: Record<string, [readonly string[], Record<string, Unit>]> = {
  income: [INCOME_KINDS, { pct: 'pct', amount: 'money' }],
  bills: [BILLS_KINDS, { pct: 'pct' }],
  monthly_cost: [MONTHLY_KINDS, { amount: 'money' }],
  one_off: [ONE_OFF_KINDS, { amount: 'money', months: 'months' }],
  spending_cut: [CUT_KINDS, { pct: 'pct' }],
  target: [TARGET_KINDS, { months: 'months' }],
  edit: [EDIT_KINDS, { pct: 'pct' }],
};

export interface Part {
  kind: string;
  pct?: number;
  amount?: number;
  months?: number;
}

export interface Intent {
  income: Part;
  bills: Part;
  monthly_cost: Part;
  one_off: Part;
  spending_cut: Part;
  target: Part;
  edit: Part;
  account_id: number;
  checks: Record<CheckName, string>;
  clarify: string;
}

export function blankIntent(): Intent {
  const out: Record<string, unknown> = {};
  for (const [name, [, fields]] of Object.entries(SECTIONS)) {
    const part: Record<string, unknown> = { kind: 'none' };
    for (const f of Object.keys(fields)) part[f] = 0;
    out[name] = part;
  }
  out.account_id = 0;
  out.checks = Object.fromEntries(CHECKS.map((c) => [c, 'unchanged']));
  out.clarify = '';
  return out as unknown as Intent;
}

export class IntentError extends Error {}

function num(v: unknown, unit: Unit): number {
  if (typeof v === 'boolean' || !['number', 'string'].includes(typeof v)) throw new IntentError(`not a number`);
  let x: number;
  try {
    if (unit === 'pct') return pyRound(coercePct(v), 4) + 0;
    x = typeof v === 'string' ? parseMoney(v) : (v as number);
  } catch (e) {
    throw new IntentError(String(e));
  }
  if (!Number.isFinite(x)) throw new IntentError('not a number');
  return pyRound(x, 2) + 0;
}

/** The canonical form of an intent (sorted keys aside): cents, 4-decimal fractions, lowercased enums. */
export function canonicalizeIntent(raw: unknown): Intent {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) throw new IntentError('the intent is not an object');
  const r = raw as Record<string, unknown>;
  const out = blankIntent() as unknown as Record<string, unknown>;
  for (const [name, [kinds, fields]] of Object.entries(SECTIONS)) {
    const part = r[name];
    if (part === null || part === undefined) continue;
    if (typeof part !== 'object' || Array.isArray(part)) throw new IntentError(`${name} is not an object`);
    const p = part as Record<string, unknown>;
    const kind = String(p.kind ?? 'none').trim().toLowerCase().replaceAll(' ', '_').replaceAll('-', '_');
    if (!kinds.includes(kind)) throw new IntentError(`${name}: unknown kind ${kind}`);
    const o = out[name] as Record<string, unknown>;
    o.kind = kind;
    for (const [f, unit] of Object.entries(fields)) {
      if (f in p && p[f] !== null && p[f] !== undefined) o[f] = num(p[f], unit);
    }
  }
  let acct = r.account_id ?? 0;
  if (typeof acct === 'boolean' || !['number', 'string'].includes(typeof acct)) throw new IntentError('account_id');
  const af = Number(acct);
  if (!Number.isFinite(af) || af !== Math.trunc(af)) throw new IntentError('account_id is not a whole number');
  acct = af;
  out.account_id = acct;
  const checks = (r.checks ?? {}) as Record<string, unknown>;
  if (typeof checks !== 'object' || Array.isArray(checks)) throw new IntentError('checks is not an object');
  const oc = out.checks as Record<string, string>;
  for (const c of CHECKS) {
    const v = String(checks[c] ?? 'unchanged').trim().toLowerCase();
    if (!(CHECK_VALUES as readonly string[]).includes(v)) throw new IntentError(`checks.${c}: unknown value`);
    oc[c] = v;
  }
  out.clarify = r.clarify === null || r.clarify === undefined ? '' : String(r.clarify).trim();
  return out as unknown as Intent;
}

export function intentIsEmpty(it: Intent): boolean {
  return (
    Object.keys(SECTIONS).every((n) => (it as unknown as Record<string, Part>)[n].kind === 'none') &&
    it.account_id === 0 &&
    Object.values(it.checks).every((v) => v === 'unchanged') &&
    !it.clarify
  );
}

// ------------------------------------------------------------------ Shock <-> lever state, and words for a Shock

const r = (x: number, nd: number) => pyRound(Number(x), nd) + 0;

/** The app's lever state (Python: the Streamlit session-state keys). */
export type OneOffMode = 'x' | 'amt';
export interface LeverState {
  incomePct: number;
  jobLoss: boolean;
  billsPct: number;
  extra: number;
  oneOffMode: OneOffMode;
  oneOffX: number;
  oneOffAmt: number;
  cutPct: number;
}
export interface CheckToggles {
  cap: boolean;
  ww: boolean;
  pens: boolean;
  s6: boolean;
  bfb: boolean;
}

export function sameShock(a: Shock, b: Shock): boolean {
  return (Object.keys(a) as (keyof Shock)[]).every((k) => k === 'name' || a[k] === b[k]);
}

export function canPension(shock: Shock, acct: Account): boolean {
  return isJobLoss(shock) && acct.Pn > 0;
}

export function canBillsFallback(acct: Account): boolean {
  return acct.H === 0 && acct.H_SO > 0;
}

/** The judges' levers a lever state means (inactive one-off input doesn't count). No reality checks. */
export function judgesShockFromLevers(l: LeverState): Shock {
  const byX = l.oneOffMode === 'x';
  const pct = Number(l.incomePct);
  const s = makeShock({
    incomeMultiplier: r(pct / 100, 6),
    billsIncreasePct: r(Number(l.billsPct) / 100, 6),
    extraMonthlyCost: r(l.extra, 2),
    oneOffCost: byX ? 0 : r(l.oneOffAmt, 2),
    oneOffMultipleOfS: byX ? r(l.oneOffX, 6) : 0,
    flexibleCutPct: r(Number(l.cutPct ?? 0) / 100, 6),
    jobLoss: Boolean(l.jobLoss) && pct < 100,
  });
  return withShock(s, { name: twistLabel(s) });
}

/** The full Shock the engine runs: judges' levers plus the reality checks that apply to this account. */
export function shockFromState(l: LeverState, t: CheckToggles, acct: Account): Shock {
  const j = judgesShockFromLevers(l);
  const jl = isJobLoss(j);
  return withShock(j, {
    incomeCapMonthly: t.cap && jl ? EI_2026_MAX_MONTHLY : null,
    waitingWeek: Boolean(t.ww) && jl,
    pensionAware: Boolean(t.pens) && canPension(j, acct),
    spendingBasis: t.s6 ? 'S6' : 'S',
    billsFallback: Boolean(t.bfb) && canBillsFallback(acct),
  });
}

/** The lever values that mean this Shock (inverse of shockFromState). */
export function shockToState(shock: Shock): { levers: LeverState; toggles: CheckToggles } {
  if (shock.oneOffCost > 0 && shock.oneOffMultipleOfS > 0) throw new Error('both one-off kinds set');
  const byX = !(shock.oneOffCost > 0);
  const mult = shock.incomeMultiplier;
  return {
    levers: {
      incomePct: r(mult * 100, 4),
      jobLoss: Boolean(shock.jobLoss && mult < 1),
      billsPct: r(shock.billsIncreasePct * 100, 4),
      extra: r(shock.extraMonthlyCost, 2),
      oneOffMode: byX ? 'x' : 'amt',
      oneOffX: byX ? r(shock.oneOffMultipleOfS, 6) : 0,
      oneOffAmt: byX ? 0 : r(shock.oneOffCost, 2),
      cutPct: r(shock.flexibleCutPct * 100, 4),
    },
    toggles: {
      cap: shock.incomeCapMonthly !== null,
      ww: Boolean(shock.waitingWeek),
      pens: Boolean(shock.pensionAware),
      s6: shock.spendingBasis === 'S6',
      bfb: Boolean(shock.billsFallback),
    },
  };
}

const pct = (x: number) => `${pyG(pyRound(x * 100, 1))}%`;

/** The app's twist-card names, kept for the three track twists so the story headline still names them. */
const PRESET_NAMES: readonly [Shock, string][] = [
  [LAID_OFF_EI, 'Laid off: EI 55%'],
  [FURNACE, 'Furnace dies: 1× spending'],
  [DOUBLE_WHAMMY, 'Job loss + bills +15%'],
];

export function checksFree(shock: Shock): Shock {
  return withShock(shock, { incomeCapMonthly: null, waitingWeek: false, pensionAware: false, spendingBasis: 'S',
    billsFallback: false, name: '' });
}

const cap1 = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

/** Plain English for a Shock: THE one function behind both the twist label and `understoodAs`. */
export function describeShock(shock: Shock, acct: Account | null = null, target: number | null = null): string {
  const parts: string[] = [];
  if (acct === null) {
    const free = checksFree(shock);
    const preset = PRESET_NAMES.find(([p]) => sameShock(free, p) && free.name === '' );
    if (preset) parts.push(preset[1]);
    else leverParts(shock, null, parts);
    checkParts(shock, parts);
    return parts.length ? cap1(parts.join(', ')) : 'No shock';
  }
  leverParts(shock, acct, parts);
  checkParts(shock, parts);
  if (!parts.length) parts.push('no shock');
  if (target !== null) parts.push(`must last ${pyG(target)} month${target === 1 ? '' : 's'}`);
  return cap1(parts.join(' · '));
}

function leverParts(shock: Shock, acct: Account | null, parts: string[]): void {
  const long = acct !== null;
  const mult = shock.incomeMultiplier;
  const I = long ? acct.I : 0;
  if (isJobLoss(shock)) {
    const p = `laid off, EI pays ${pct(mult)}`;
    parts.push(p + (long ? `: ${money(mult * I)}/mo of your usual ${money(I)}` : ''));
  } else if (mult !== 1) {
    parts.push(long ? `income drops to ${money(mult * I)}/mo (${pct(mult)} of your usual ${money(I)})`
      : `income kept ${pct(mult)}`);
  }
  if (shock.billsIncreasePct) {
    let H = long ? acct.H : 0;
    if (long && shock.billsFallback) H = pyMax(H, acct.H_SO);
    parts.push(`household bills +${pct(shock.billsIncreasePct)}` +
      (long ? ` (+${money(shock.billsIncreasePct * H)}/mo on ${money(H)})` : ''));
  }
  if (shock.extraMonthlyCost) parts.push(`+${money(shock.extraMonthlyCost)}/mo` + (long ? ' new monthly costs' : ''));
  if (shock.oneOffCost) parts.push(`one-off ${money(shock.oneOffCost)}`);
  if (shock.oneOffMultipleOfS) {
    const x = shock.oneOffMultipleOfS;
    parts.push(`one-off ${pyG(x)}× spending` + (long ? ` (${money(x * acct.S)})` : ''));
  }
  if (shock.flexibleCutPct) {
    parts.push(`non-fixed spending cut ${pct(shock.flexibleCutPct)}` +
      (long ? ` (-${money(shock.flexibleCutPct * acct.flexible_median)}/mo)` : ''));
  }
}

function checkParts(shock: Shock, parts: string[]): void {
  if (shock.incomeCapMonthly !== null) parts.push(`2026 EI cap (${money(shock.incomeCapMonthly)}/mo)`);
  if (shock.waitingWeek) parts.push('EI waiting week');
  if (shock.pensionAware) parts.push('pension kept');
  if (shock.spendingBasis === 'S6') parts.push('half-year spending');
  if (shock.billsFallback) parts.push('bills by standing order');
}

export function twistLabel(shock: Shock): string {
  return describeShock(shock);
}

// ------------------------------------------------------------------ validateAndBuild

export type Source = 'golden' | 'rules' | 'none';

export interface ParseResult {
  shock: Shock;
  target: number;
  accountId: number | null;
  source: Source;
  understoodAs: string;
  resolved: string[];
  warnings: string[];
  clarify: string | null;
  /** the most recently set percent lever, for "make it 20% instead" */
  pctLever: string | null;
  intent: Intent;
}

/** What validateAndBuild needs to know about the other accounts: a lookup and the id range. */
export interface AccountIndex {
  get(id: number): Account | undefined;
  minId: number;
  maxId: number;
}

function clamp(x: number, lo: number, hi: number, what: string, warnings: string[],
  fmt: (v: number) => string = (v) => pyG(v)): number {
  if (x < lo || x > hi) {
    const y = pyMin(pyMax(x, lo), hi);
    warnings.push(`${what} ${fmt(x)} is out of range; using ${fmt(y)}.`);
    return y;
  }
  return x;
}

function suggest(): string {
  return "I couldn't read a twist there. Try: " + SUGGESTIONS.map((s) => `“${s}”`).join(' · ');
}

export function validateAndBuild(rawIntent: unknown, acct: Account, current: Shock, target: number,
  index: AccountIndex, lastPctLever: string | null = null, source: Source = 'none'): ParseResult {
  const intent = canonicalizeIntent(rawIntent);
  const warnings: string[] = [];
  const resolved: string[] = [];
  let row = acct;

  const unchanged = (msg: string): ParseResult => ({
    shock: current, target: Math.trunc(target), accountId: null, source,
    understoodAs: describeShock(current, row, target), resolved: [], warnings, clarify: msg,
    pctLever: lastPctLever, intent,
  });

  if (intent.clarify) return unchanged(intent.clarify);
  if (intentIsEmpty(intent)) return unchanged(suggest());

  let accountId: number | null = null;
  if (intent.account_id) {
    const other = index.get(intent.account_id);
    if (!other) {
      return unchanged(`Account ${intent.account_id} isn't in the data (IDs run ${index.minId} to ${index.maxId} ` +
        'with gaps). Which account did you mean?');
    }
    accountId = intent.account_id;
    row = other;
  }

  const { I, H, S } = row;
  const s = current;
  let mult = s.incomeMultiplier;
  let jl = s.jobLoss;
  let bills = s.billsIncreasePct;
  let extra = s.extraMonthlyCost;
  let cost = s.oneOffCost;
  let xS = s.oneOffMultipleOfS;
  let cut = s.flexibleCutPct;
  let cap = s.incomeCapMonthly !== null;
  let ww = s.waitingWeek;
  let pens = s.pensionAware;
  let s6 = s.spendingBasis === 'S6';
  let bfb = s.billsFallback;
  let tgt = Number(target);
  let pctLever = lastPctLever;

  const edit = intent.edit;
  if (edit.kind === 'reset_all') {
    [mult, jl, bills, extra, cost, xS, cut] = [1, false, 0, 0, 0, 0, 0];
    cap = ww = pens = s6 = bfb = false;
    tgt = DEFAULT_TARGET;
    pctLever = null;
  }

  const inc = intent.income;
  const ip = inc.pct ?? 0;
  if (inc.kind === 'job_loss_ei') {
    mult = ip > 0 ? ip : LAID_OFF_EI.incomeMultiplier;
    jl = true;
    pctLever = 'income_ei';
  } else if (inc.kind === 'drop_pct') {
    [mult, jl, pctLever] = [1 - ip, false, 'income_drop'];
  } else if (inc.kind === 'keep_pct') {
    [mult, jl, pctLever] = [ip, false, 'income_keep'];
  } else if (inc.kind === 'pay_cut_pct') {
    if (ip <= 0) return unchanged('How big is the pay cut? For example: “pay cut 20%” or “hours cut in half”.');
    [mult, jl, pctLever] = [1 - ip, false, 'income_drop'];
  } else if (inc.kind === 'to_amount') {
    const n = inc.amount ?? 0;
    if (I <= 0) {
      warnings.push(`Usual money in is ${money(I)}, so an income of ${money(n)}/mo can't be expressed as a ` +
        'share of it; income left unchanged.');
    } else {
      let ratio = n / I;
      if (ratio > 1) {
        warnings.push(`${money(n)}/mo is more than the usual ${money(I)}/mo; income kept at 100%.`);
        ratio = 1;
      }
      [mult, jl, pctLever] = [ratio, false, null];
      resolved.push(`income ${money(n)}/mo ÷ usual ${money(I)}/mo = ${pct(ratio)} of money in`);
    }
  } else if (inc.kind === 'partner_job_loss') {
    [mult, jl, pctLever] = [0.5, false, null];
    warnings.push("Assumed the partner brings in half the household's money in (income kept 50%, not an EI " +
      'job loss); adjust under Fine-tune if the split is different.');
  } else if (inc.kind === 'restore') {
    [mult, jl] = [1, false];
    if (pctLever && pctLever.startsWith('income')) pctLever = null;
  }

  const b = intent.bills;
  if (b.kind === 'increase_pct') [bills, pctLever] = [b.pct ?? 0, 'bills'];
  else if (b.kind === 'reset') bills = 0;

  const mc = intent.monthly_cost;
  const amt = mc.amount ?? 0;
  if (mc.kind === 'set') extra = amt;
  else if (mc.kind === 'add') extra = extra + amt;
  else if (mc.kind === 'rent_to') {
    if (H > 0) {
      extra = pyMax(amt - H, 0);
      resolved.push(`rent ${money(amt)}/mo − household bills now ${money(H)}/mo = +${money(extra)}/mo`);
      if (amt < H) {
        warnings.push(`${money(amt)}/mo is less than the household bills already recorded (${money(H)}/mo): ` +
          "a rent cut isn't modelled, so no new monthly cost.");
      }
    } else {
      extra = amt;
      warnings.push('No household bills are recorded for this account (H = $0), so the whole ' +
        `${money(amt)}/mo rent counts as a new monthly cost.`);
    }
  } else if (mc.kind === 'reset') extra = 0;

  const oo = intent.one_off;
  const months = oo.months ?? 0;
  if (oo.kind === 'set_amount') [cost, xS] = [oo.amount ?? 0, 0];
  else if (oo.kind === 'add_amount') cost = cost + (oo.amount ?? 0);
  else if (oo.kind === 'months_of_spending') [cost, xS] = [0, months > 0 ? months : 1];
  else if (oo.kind === 'add_months_of_spending') xS = xS + (months > 0 ? months : 1);
  else if (oo.kind === 'reset') [cost, xS] = [0, 0];

  const sc = intent.spending_cut;
  if (sc.kind === 'set_pct') [cut, pctLever] = [sc.pct ?? 0, 'cut'];
  else if (sc.kind === 'reset') cut = 0;

  if (intent.target.kind === 'set') tgt = intent.target.months ?? 0;

  if (edit.kind === 'set_last_percent') {
    const p = edit.pct ?? 0;
    if (pctLever === 'income_ei') [mult, jl] = [p, true];
    else if (pctLever === 'income_drop') [mult, jl] = [1 - p, false];
    else if (pctLever === 'income_keep') [mult, jl] = [p, false];
    else if (pctLever === 'bills') bills = p;
    else if (pctLever === 'cut') cut = p;
    else {
      return unchanged(`Which lever should be ${pct(p)}? For example: “bills up ${pct(p)}” or ` +
        `“cut spending ${pct(p)}”.`);
    }
  }

  for (const name of CHECKS) {
    const v = intent.checks[name];
    if (v === 'unchanged') continue;
    const on = v === 'on';
    if (name === 'ei_cap') cap = on;
    else if (name === 'waiting_week') ww = on;
    else if (name === 'keep_pension') pens = on;
    else if (name === 'half_year_spending') s6 = on;
    else bfb = on;
  }

  mult = clamp(mult, 0, 1, 'Income kept', warnings, pct);
  bills = clamp(bills, 0, 1, 'Bills increase', warnings, pct);
  cut = clamp(cut, 0, 1, 'Spending cut', warnings, pct);
  extra = clamp(extra, 0, MONEY_MAX, 'Monthly cost', warnings, money);
  cost = clamp(cost, 0, MONEY_MAX, 'One-off cost', warnings, money);
  xS = clamp(xS, 0, ONEOFF_MULTIPLE_MAX, 'One-off of', warnings, (v) => `${pyG(v)}× spending`);
  tgt = clamp(tgt, TARGET_MIN, TARGET_MAX, 'Target of', warnings, (v) => `${pyG(v)} months`);
  if (tgt !== rint(tgt)) warnings.push(`Target of ${pyG(tgt)} months rounded to ${rint(tgt)} months.`);
  const tgtI = rint(tgt);

  // a $ one-off and a multiple-of-spending one-off together become one $ amount for this account
  if (cost > 0 && xS > 0) {
    const total = cost + xS * S;
    resolved.push(`one-off ${money(cost)} + ${pyG(xS)}× spending (${money(xS * S)}) = ${money(total)}`);
    [cost, xS] = [r(total, 2), 0];
  }

  jl = jl && mult < 1;
  if (cap && !jl) {
    cap = false;
    warnings.push('The 2026 EI cap needs a job loss on EI; turned off.');
  }
  if (ww && !jl) {
    ww = false;
    warnings.push('The EI waiting week needs a job loss on EI; turned off.');
  }
  if (pens && !jl) {
    pens = false;
    warnings.push('Keeping the pension needs a job loss on EI; turned off.');
  } else if (pens && !(row.Pn > 0)) {
    pens = false;
    warnings.push('This account has no pension income (Pn = $0); “keep pension” turned off.');
  }
  if (bfb && !canBillsFallback(row)) {
    bfb = false;
    warnings.push('“Bills by standing order” only applies when H = $0 and household bills are paid by ' +
      'standing order; turned off.');
  }

  const candidate = makeShock({
    incomeMultiplier: mult, jobLoss: jl, billsIncreasePct: bills, extraMonthlyCost: extra, oneOffCost: cost,
    oneOffMultipleOfS: xS, flexibleCutPct: cut, incomeCapMonthly: cap ? EI_2026_MAX_MONTHLY : null,
    waitingWeek: ww, pensionAware: pens, spendingBasis: s6 ? 'S6' : 'S', billsFallback: bfb,
  });
  // built through the state round trip, so the chat's Shock and the sliders' Shock are equal by construction
  const st = shockToState(candidate);
  const final = shockFromState(st.levers, st.toggles, row);
  return { shock: final, target: tgtI, accountId, source, understoodAs: describeShock(final, row, tgtI), resolved,
    warnings, clarify: null, pctLever, intent };
}

// ------------------------------------------------------------------ backends and parseShock

let GOLDEN: Map<string, Intent> | null = null;

export function goldenTable(): Map<string, Intent> {
  if (GOLDEN) return GOLDEN;
  const out = new Map<string, Intent>();
  for (const entry of (goldenFile as { twists: { phrases: string[]; intent: unknown }[] }).twists) {
    const intent = canonicalizeIntent(entry.intent);
    for (const phrase of entry.phrases) out.set(normalize(phrase), intent);
  }
  GOLDEN = out;
  return out;
}

export interface Parser {
  source: Source;
  parse(message: string, norm: string, current: Shock): unknown | null;
}

export const GoldenParser: Parser = {
  source: 'golden',
  parse: (_m, norm) => {
    const hit = goldenTable().get(norm);
    return hit ? structuredClone(hit) : null;
  },
};

export const RuleParser: Parser = { source: 'rules', parse: (message) => ruleIntent(message) };

export function parseShock(message: string, acct: Account, current: Shock, target: number, index: AccountIndex,
  lastPctLever: string | null = null, backends: readonly Parser[] = [GoldenParser, RuleParser]): ParseResult {
  const norm = normalize(message);
  if (!norm) return validateAndBuild(blankIntent(), acct, current, target, index, lastPctLever);
  for (const backend of backends) {
    const intent = backend.parse(message, norm, current);
    if (intent === null || intent === undefined) continue;
    try {
      return validateAndBuild(intent, acct, current, target, index, lastPctLever, backend.source);
    } catch (e) {
      if (e instanceof IntentError) continue; // an unreadable intent is skipped, never trusted
      throw e;
    }
  }
  return validateAndBuild(blankIntent(), acct, current, target, index, lastPctLever);
}

/** 1-2 next things to try that fit the new state. The engine decides "under the target"; no number is shown. */
export function followUpHints(res: ParseResult, acct: Account): string[] {
  const hints: string[] = [];
  if (isJobLoss(res.shock) && res.shock.incomeCapMonthly === null) hints.push('Try “with the 2026 EI cap”');
  const judge = checksFree(res.shock);
  if (!survives(applyShock(acct, judge), res.target) && !res.shock.flexibleCutPct) hints.push('Try “cut spending 25%”');
  if (!hints.length) hints.push(`Try “must last ${Math.min(res.target + 3, TARGET_MAX)} months”`);
  return hints.slice(0, 2);
}

// ------------------------------------------------------------------ rule parser

const FILL = '░';
const NUM = String.raw`(\d+(?:\.\d+)?)`;
const PCT = NUM + String.raw`\s*(%)?`;
const MO = String.raw`(?:\s*/mo)?`;
const MONEY_NOT_PCT = String.raw`(?!\s*%|\d|\.\d)`;
const ADD_WORDS = /\b(?:add|adds|adding|another|also|plus|on top|additional)\b/;

function ruleText(message: string): string {
  let t = String(message).toLowerCase().replaceAll('’', "'").replaceAll('−', '-');
  t = t.replace(/(?<=\d),(?=\d{3}\b)/g, '');
  t = t.replace(/\b(per cent|percent|pct)\b/g, '%');
  t = wordsToDigits(t);
  t = t.replace(/\b(?:in|by) half\b/g, 'by 50%');
  t = t.replace(/\bhalf (?:a|of a) month\b/g, '0.5 month');
  t = t.replace(/\bby a quarter\b/g, 'by 25%');
  t = t.replace(/\b(?:a|one) quarter of\b/g, '25% of');
  t = t.replace(/(\d+(?:\.\d+)?)\s*(?:k|thousand)\b/g, (_m, n: string) => pyG(Number.parseFloat(n) * 1000));
  t = t.replace(/\$\s+(?=\d)/g, '$');
  t = t.replace(/(\d)\s*(?:\/\s*mo(?:nth)?\b|\/\s*m\b|(?:a|per|each|every)\s+mo(?:nth)?\b|monthly\b|\/\s*month\b)/g,
    '$1/mo');
  return t.replace(/[ \t]+/g, ' ').trim();
}

type M = RegExpMatchArray;

class Text {
  constructor(public s: string) {}

  take(pattern: string): M[] {
    const ms = [...this.s.matchAll(new RegExp(pattern, 'g'))];
    for (const m of ms) {
      const i = m.index ?? 0;
      this.s = this.s.slice(0, i) + FILL.repeat(m[0].length) + this.s.slice(i + m[0].length);
    }
    return ms;
  }

  has(pattern: string): boolean {
    return new RegExp(pattern).test(this.s);
  }
}

const g = (m: M, i: number): string | undefined => m[i] ?? undefined;
const pctOf = (m: M, n = 1, p = 2) => coercePct((g(m, n) as string) + (g(m, p) ? '%' : ''));
const raw = String.raw;

const INCOME = raw`(?:income|pay|paycheque|paycheck|money in|earnings|wages?)`;
const OFF = raw`(?:no|without|remove|drop|turn off|undo|cancel|skip|forget)`;
const CHECKS_OFF: [CheckName, string][] = [
  ['ei_cap', raw`\b${OFF}\s+(?:the\s+)?(?:2026\s+)?(?:ei\s+)?(?:cap|max(?:imum)?)\b`],
  ['waiting_week', raw`\b${OFF}\s+(?:the\s+)?(?:ei\s+)?waiting (?:week|period)\b`],
  ['keep_pension', raw`\b${OFF}\s+(?:the\s+)?pension(?:\s+check)?\b|\blos(?:e|es|ing) (?:the\s+)?pension\b`],
  ['half_year_spending', raw`\b${OFF}\s+(?:the\s+)?half-?\s?year(?:\s+spending)?\b`],
  ['bills_by_standing_order', raw`\b${OFF}\s+(?:the\s+)?(?:bills\s+(?:paid\s+)?by\s+)?standing orders?\b`],
];
const CHECKS_ON: [CheckName, string][] = [
  ['ei_cap', raw`\b(?:2026\s+)?ei\s+(?:cap|max(?:imum)?)\b|\b2026\s+(?:cap|max(?:imum)?)\b` +
    raw`|\bcap(?:ped)?\s+(?:at\s+)?(?:the\s+)?(?:2026|ei|max(?:imum)?)\b|\bwith the cap\b` +
    raw`|\$?729\s*(?:/|a|per)?\s*w(?:ee)?k\b`],
  ['waiting_week', raw`\b(?:ei\s+)?waiting (?:week|period)\b`],
  ['keep_pension', raw`\b(?:keeps?|keeping|kept)\s+(?:the\s+|their\s+|my\s+|his\s+|her\s+)?pension\b` +
    raw`|\bpension\s+(?:is\s+)?(?:kept|stays|continues|keeps coming)\b|\bpension[- ]aware\b`],
  ['half_year_spending', raw`\bhalf-?\s?year(?:ly)?(?:\s+spending)?\b|\bs6\b`],
  ['bills_by_standing_order', raw`\b(?:(?:paid\s+)?by\s+)?standing orders?\b|\bbills fallback\b`],
];

function clarifyIntent(text: string): Intent {
  return { ...blankIntent(), clarify: text };
}

/** The offline parser (resilience.shock_parser.rule_intent): null when nothing in the message is a twist. */
export function ruleIntent(message: string): Intent | null {
  const t = new Text(ruleText(message));
  const it = blankIntent();
  let found = false;
  const incomes: [string, number, number][] = [];
  const adding = ADD_WORDS.test(t.s);
  const income = (kind: string, p = 0, a = 0) => incomes.push([kind, p, a]);

  if (t.take(raw`\bdouble whammy\b`).length) {
    income('job_loss_ei', LAID_OFF_EI.incomeMultiplier);
    it.bills = { kind: 'increase_pct', pct: DOUBLE_WHAMMY.billsIncreasePct };
    found = true;
  }
  if (t.take(raw`\b(?:reset|start over|start again|clear (?:it|everything|all)|from scratch|no shock|back to baseline)\b`).length) {
    it.edit.kind = 'reset_all';
    found = true;
  }
  for (const m of t.take(raw`\b(?:account|acct|customer|client)(?:\s+(?:id|number|no\.?))?\s*#?\s*(\d{4,6})\b|#(\d{4,6})\b`)) {
    it.account_id = Number.parseInt((g(m, 1) || g(m, 2)) as string, 10);
    found = true;
  }
  for (const [name, pat] of CHECKS_OFF) {
    if (t.take(pat).length) {
      it.checks[name] = 'off';
      found = true;
    }
  }
  for (const [name, pat] of CHECKS_ON) {
    if (t.take(pat).length) {
      it.checks[name] = 'on';
      found = true;
    }
  }

  if (t.take(raw`\b${OFF}\s+(?:the\s+)?(?:household\s+)?(?:bills?|utilities)(?:\s+(?:increase|rise|hike|shock|change))?\b`).length) {
    it.bills.kind = 'reset';
    found = true;
  }
  if (t.take(raw`\b${OFF}\s+(?:the\s+)?(?:one-off|one off|repair|furnace|emergency)(?:\s+(?:cost|repair|bill))?\b`).length) {
    it.one_off.kind = 'reset';
    found = true;
  }
  if (t.take(raw`\b${OFF}\s+(?:the\s+)?(?:(?:extra|new|monthly)\s+(?:monthly\s+)?(?:costs?|payments?|expenses?)` +
    raw`|rent(?:\s+(?:increase|rise|hike))?)\b`).length) {
    it.monthly_cost.kind = 'reset';
    found = true;
  }
  if (t.take(raw`\b${OFF}\s+(?:the\s+)?(?:spending\s+)?cuts?\b`).length) {
    it.spending_cut.kind = 'reset';
    found = true;
  }

  for (const m of t.take(raw`\b(?:for|survive|survives|surviving|last|lasts|lasting|through|cover|covers|make it|change it to)` +
    raw`\s+` + NUM + raw`\s*-?\s*months?\b(?!\s+(?:of|worth))` +
    raw`|\b` + NUM + raw`\s*-?\s*months?\s+(?:test|target|goal|horizon|runway)\b` +
    raw`|\b(?:target|goal|horizon|test)\s+(?:of\s+|is\s+|=\s*|to\s+)?` + NUM + raw`\s*months?\b`)) {
    it.target = { kind: 'set', months: Number.parseFloat((g(m, 1) || g(m, 2) || g(m, 3)) as string) };
    found = true;
  }

  if (t.take(raw`\b(?:partner|spouse|wife|husband|second earner|other earner)(?:'s)?\b[^.;,]{0,30}?` +
    raw`\b(?:loses?|lost|losing|laid off|out of work|job loss)\b(?:\s+(?:his|her|their|the|a))?(?:\s+jobs?)?` +
    raw`|\b(?:lose|loses|losing|lost)\s+half\s+(?:of\s+)?(?:the\s+|their\s+|our\s+|my\s+)?(?:household\s+)?` +
    raw`income\b|\bhalf\s+(?:of\s+)?(?:the\s+)?(?:household\s+)?income\s+(?:is\s+)?(?:lost|gone)\b`).length) {
    income('partner_job_loss');
  }
  if (t.take(raw`\bno (?:job loss|lay-?off)\b|\bnot (?:a )?(?:job loss|laid off)\b` +
    raw`|\b(?:undo|remove|cancel|drop)\s+(?:the\s+)?(?:job loss|lay-?off|income (?:drop|cut|change|shock))\b` +
    raw`|\b(?:keeps?|kept)\s+(?:the\s+|their\s+|my\s+|his\s+|her\s+)?job\b|\bback to work\b` +
    raw`|\bincome (?:back to normal|restored|back)\b|\bfull income\b`).length) {
    income('restore');
  }
  let eiPct: number | null = null;
  for (const m of t.take(raw`\bei\s+(?:pays|paying|at|of|is|covers|gives)?\s*` + PCT + raw`(?!\s*-?\s*months?)`)) {
    eiPct = pctOf(m);
  }
  const job = t.take(raw`\b(?:laid off|lay-?off|layoff|lost (?:\w+\s+)?jobs?|los(?:e|es|ing) (?:\w+\s+)?jobs?|job loss` +
    raw`|jobless|unemployed|on ei|ei kicks in|goes on ei|go on ei|fired|let go|out of work` +
    raw`|employment insurance)\b`);
  if (job.length || eiPct !== null) income('job_loss_ei', eiPct ?? 0);
  for (const m of t.take(raw`\b` + PCT + raw`\s+(?:pay|wage|hours?)\s+(?:cut|reduction)\b`)) {
    income('pay_cut_pct', pctOf(m));
  }
  for (const m of t.take(raw`\b(?:pay cut|wage cut|pay reduction|reduced hours|hours? (?:\w+\s+){0,2}?(?:cut|reduced|drop)` +
    raw`|cut (?:\w+\s+)?hours|fewer hours)\b(?:\s+(?:of|by|to))?(?:\s+` + PCT + raw`)?`)) {
    const to = /\bto\s+\d/.test(m[0]);
    if (g(m, 1)) income(to ? 'keep_pct' : 'pay_cut_pct', pctOf(m));
    else income('pay_cut_pct', 0);
  }
  for (const m of t.take(raw`\b` + INCOME + raw`\s+(?:\w+\s+){0,2}?(?:drops?|falls?|goes|go|cut|down|reduced|shrinks?` +
    raw`|decreases?|is|comes in)\s+(?:down\s+)?to\s+(\$)?` + NUM + raw`\s*(%)?` + MO)) {
    if (g(m, 3)) income('keep_pct', coercePct(`${g(m, 2)}%`));
    else if (!g(m, 1) && Number.parseFloat(g(m, 2) as string) <= 1) income('keep_pct', coercePct(g(m, 2)));
    else income('to_amount', 0, Number.parseFloat(g(m, 2) as string));
  }
  for (const m of t.take(raw`\b` + INCOME + raw`\s+(?:\w+\s+){0,2}?(?:drops?|falls?|cut|down|decreases?|reduced|shrinks?` +
    raw`|goes down|declines?|lower)\s+(?:by\s+)?` + PCT + raw`(?!\s*/mo)` +
    raw`|\b` + PCT + raw`\s+(?:drop|fall|cut|decrease|reduction|less|lower|loss)\s+(?:in\s+|of\s+)?` +
    raw`(?:\w+\s+)?` + INCOME +
    raw`|\b(?:lose|loses|losing|lost)\s+` + PCT + raw`\s+of\s+(?:\w+\s+)?` + INCOME)) {
    const i = [1, 3, 5].find((k) => g(m, k) !== undefined) as number;
    income('drop_pct', coercePct((g(m, i) as string) + (g(m, i + 1) ? '%' : '')));
  }
  for (const m of t.take(raw`\b` + INCOME + raw`\s+(?:is\s+)?(?:kept|keeps?|stays|at|only)\s+(?:at\s+)?` + PCT +
    raw`|\b(?:keeps?|kept|keeping|only)\s+` + NUM + raw`\s*(%)\s+of\s+(?:\w+\s+){0,2}?` + INCOME +
    raw`|\b` + NUM + raw`\s*(%)\s+of\s+(?:\w+\s+){0,2}?` + INCOME + raw`\b`)) {
    const i = [1, 3, 5].find((k) => g(m, k) !== undefined) as number;
    income('keep_pct', coercePct((g(m, i) as string) + (g(m, i + 1) ? '%' : '')));
  }

  for (const m of t.take(raw`\brent\s+(?:\w+\s+){0,2}?(?:goes|going|go|rises|rise|jumps|jump|increases|increase|up|climbs)` +
    raw`\s+to\s+\$?` + NUM + MONEY_NOT_PCT + MO)) {
    it.monthly_cost = { kind: 'rent_to', amount: Number.parseFloat(g(m, 1) as string) };
    found = true;
  }
  const BILLS = raw`(?:household\s+)?(?:bills?|utilities|utility bills?|hydro|heating|rent)`;
  const GAP = raw`(?:[\w░'-]+\s+){0,2}?`;
  const UP = raw`(?:up|rise|rises|rising|go up|goes up|increase[sd]?|jumps?|climbs?|grows?|higher)`;
  for (const m of t.take(raw`\b(` + BILLS + raw`)\s+` + GAP + UP + raw`\s*(?:by\s+)?\+?\s*` + NUM + raw`\s*(%)` +
    raw`|\b(` + BILLS + raw`)\s*\+\s*` + NUM + raw`\s*(%)` +
    raw`|\b` + NUM + raw`\s*(%)\s+(?:higher|more|increase in|rise in|jump in|hike in|up on)\s+(?:the\s+)?(` + BILLS + raw`)` +
    raw`|\b((?:household\s+)?(?:bills?|utilities))\s+` + GAP + UP + raw`\s*(?:by\s+)?` + NUM + raw`(?!\s*/mo|\d|\.\d|\s*%)`)) {
    let p: number;
    if (g(m, 1)) p = coercePct(`${g(m, 2)}%`);
    else if (g(m, 4)) p = coercePct(`${g(m, 5)}%`);
    else if (g(m, 7)) p = coercePct(`${g(m, 7)}%`);
    else p = coercePct(g(m, 11));
    it.bills = { kind: 'increase_pct', pct: p };
    found = true;
  }
  const monthly: number[] = [];
  const firstGroup = (m: M) => Number.parseFloat(m.slice(1).find((x) => x !== undefined) as string);
  for (const m of t.take(raw`\brent\s+(?:\w+\s+){0,2}?(?:up|rises?|goes up|go up|increases?|jumps?|climbs?|higher)\s*` +
    raw`(?:by\s+)?\+?\s*\$?` + NUM + MONEY_NOT_PCT + MO +
    raw`|\brent\s*\+\s*\$?` + NUM + MONEY_NOT_PCT + MO +
    raw`|\$` + NUM + raw`(?:/mo)?\s+(?:more\s+)?(?:in\s+|on\s+)?rent\b`)) {
    monthly.push(firstGroup(m));
  }
  for (const m of t.take(raw`(?:\b(?:new|extra|another|additional|plus|add(?:ed)?|more)\s+)?\$?` + NUM +
    raw`/mo(?:\s+(?:more|extra))?`)) {
    monthly.push(Number.parseFloat(g(m, 1) as string));
  }
  for (const m of t.take(raw`\b(?:payment|insurance|daycare|day care|childcare|child care|subscription|tuition)\s+` +
    raw`(?:\w+\s+){0,2}?(?:of\s+|costs?\s+|is\s+|at\s+|=\s*)?\$?` + NUM + MONEY_NOT_PCT +
    raw`|\$` + NUM + raw`\s+(?:\w+\s+)?(?:car payment|payment|insurance premium|daycare|childcare)\b`)) {
    monthly.push(firstGroup(m));
  }
  if (monthly.length) {
    it.monthly_cost = { kind: adding ? 'add' : 'set', amount: monthly.reduce((a, b) => a + b, 0) };
    found = true;
  }

  for (const m of t.take(raw`\b(?:` + NUM + raw`|an?|one|another)\s+(?:full\s+|whole\s+|entire\s+)?months?(?:'s)?\s+` +
    raw`(?:of|worth of)\s+(?:typical\s+|usual\s+|normal\s+|their\s+|my\s+)?` +
    raw`(?:spending|expenses|costs|money out|outgoings)\b` +
    raw`|\b(?:an?\s+)?(?:full\s+|whole\s+)?month's\s+(?:typical\s+)?spending\b` +
    raw`|\b` + NUM + raw`\s*(?:x|×|times)\s*(?:typical\s+|usual\s+|monthly\s+)?(?:spending|s)\b`)) {
    const n = Number.parseFloat((g(m, 1) || g(m, 2) || '1') as string);
    const another = m[0].startsWith('another');
    it.one_off = { kind: adding || another ? 'add_months_of_spending' : 'months_of_spending', amount: 0, months: n };
    found = true;
  }
  const KW = raw`(?:repairs?|one-off|one off|emergency|furnace|boiler|roof|vet|dental|dentist|medical|transmission|fix` +
    raw`|expense|bill|cost|hit|replacement)`;
  const amounts: number[] = [];
  for (const m of t.take(raw`\$?` + NUM + raw`(?!\s*/mo|\d|\.\d|\s*%|\s*-?\s*months?)\s+(?:\w+\s+){0,2}?` + KW + raw`\b` +
    raw`|\b(?:repairs?|one-off|one off|emergency|furnace|boiler|roof|vet bill|dental bill|medical bill` +
    raw`|transmission|unexpected (?:bill|cost|expense)|surprise (?:bill|cost|expense))\b` +
    raw`(?:\s+(?:\w+\s+){0,3}?)(?:of\s+|costs?\s+|for\s+|=\s*|is\s+|at\s+)?\$?` + NUM +
    raw`(?!\s*(?:%|/mo|\d|\.\d|-?\s*months?|x\b|×))`)) {
    amounts.push(Number.parseFloat((g(m, 1) || g(m, 2)) as string));
  }
  if (amounts.length) {
    if (it.one_off.kind === 'months_of_spending' || it.one_off.kind === 'add_months_of_spending') {
      return clarifyIntent('I read two one-off costs there (a dollar amount and months of spending). ' +
        'Which one did you mean?');
    }
    it.one_off = { kind: adding ? 'add_amount' : 'set_amount', amount: amounts.reduce((a, b) => a + b, 0), months: 0 };
    found = true;
  }
  if (it.one_off.kind === 'none' && t.take(raw`\b(?:furnace|boiler|water heater)\b`).length) {
    it.one_off = { kind: adding ? 'add_months_of_spending' : 'months_of_spending', amount: 0, months: 1 };
    found = true;
  }

  for (const m of t.take(raw`\bcut(?:s|ting)?\s+(?:back\s+)?(?:on\s+)?(?:[\w-]+\s+){0,2}?(?:spending|expenses|outgoings)\s+` +
    raw`(?:by\s+)?` + PCT +
    raw`|\b(?:non-fixed|discretionary|flexible|card and cash)\s+(?:spending\s+)?(?:cut|down|reduced` +
    raw`|drops?|lower)\s+(?:by\s+)?` + PCT +
    raw`|\bspend(?:s|ing)?\s+` + NUM + raw`\s*(%)\s+less\b` +
    raw`|\bcut\s+` + NUM + raw`\s*(%)\s+(?:of\s+)?(?:\w+\s+)?spending\b`)) {
    const i = [1, 3, 5, 7].find((k) => g(m, k) !== undefined) as number;
    it.spending_cut = { kind: 'set_pct', pct: coercePct((g(m, i) as string) + (g(m, i + 1) ? '%' : '')) };
    found = true;
  }

  if (t.has(raw`\b(?:instead|make it|change it to|set it to|actually|rather)\b`)) {
    for (const m of t.take(raw`\b` + NUM + raw`\s*(%)`)) {
      it.edit = { kind: 'set_last_percent', pct: coercePct(`${g(m, 1)}%`) };
      found = true;
    }
  }

  const kinds = new Set(incomes.map(([k]) => k));
  const triples = new Set(incomes.map((x) => JSON.stringify(x)));
  if (kinds.size > 1 || triples.size > 1) {
    return clarifyIntent('I read more than one income change there. Which one did you mean? ' +
      'For example: “laid off, EI pays 55%” or “income drops 30%”.');
  }
  if (incomes.length) {
    const [k, p, a] = incomes[0];
    it.income = { kind: k, pct: p, amount: a };
    found = true;
  }
  if (!found) return null;
  return canonicalizeIntent(it);
}
