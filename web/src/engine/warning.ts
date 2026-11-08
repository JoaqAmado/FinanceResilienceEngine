/**
 * Early-warning light, a port of resilience/warning.py: four transparent rules, 0-4 points, shown
 * beside the judges' runway. It is a watch flag, not a credit score, and it never changes the judges'
 * runway number.
 *
 * The Python engine computes each account's rule inputs over its last 6 monthly rows (the opening month
 * is left out) and exports them at full precision in accounts.json: rows used, days below zero in those
 * rows, the 4 raw values, the window's median money out (the rules' month of spending, not the card's S)
 * and the window's last month. This module does the rest exactly as resilience/warning.py does: clip and
 * fill the raw values, fire the rules, count the points, pick the status and write the card text.
 *
 *     Rule 1  lowest balance under half a month of spending   min balance / S6, clip [-5, 24], missing 24   < 0.5
 *     Rule 2  almost all spending is cash                     cash / money out, missing 0                  > 0.95
 *     Rule 3  irregular money in                              std / mean of money in, missing 0            > 0.5
 *     Rule 4  balance sliding more than 10% of a month's      slope of daily balance / S6, clip [-3, 3],   < -0.1
 *             spending per month                              missing 0
 *
 * Status ("today" = the last month in the data):
 *     rated               6+ rows used, never below zero in them, window ends at T: points, rules and the
 *                         backtest line
 *     already_overdrawn   6+ rows used, below zero in at least one: points and rules, no backtest rate
 *                         (the backtest only followed accounts that had never gone below zero)
 *     stale               6+ rows used, never below zero, but activity stops before T: points and rules,
 *                         no backtest rate (the backtest only followed accounts that were still active)
 *     not_enough_history  fewer than 6 rows used: no points, no rules, no backtest rate (checked first,
 *                         then already_overdrawn, then stale)
 *
 * web/test/parity.test.ts checks every output here against the Python module for every account, both
 * today and at the backtest snapshot, and rebuilds the backtest tier table from per-account rules.
 */
import type { EarlyWarningFile } from './data';
import { pyFixed } from './pyformat';
import type { Account } from './types';

// Source for every constant below: the team's out-of-time backtest, as resilience/warning.py holds it
// (parity.test.ts checks each one against that module).
export const WINDOW_ROWS = 6; // w = the last 6 rows up to the snapshot
export const MIN_BAL_CUT = 0.5; // Rule 1: min balance / S6 below this
export const MIN_BAL_CLIP = [-5, 24] as const;
export const MIN_BAL_MISSING = 24;
export const CASH_SHARE_CUT = 0.95; // Rule 2: cash share of spending above this
export const INCOME_CV_CUT = 0.5; // Rule 3: income CV above this
export const BAL_TREND_CUT = -0.1; // Rule 4: balance slope / S6 below this
export const BAL_TREND_CLIP = [-3, 3] as const;
export const BACKTEST_SNAPSHOT = '2024-12'; // features use rows up to this month only
export const BACKTEST_LABEL_YEAR = '2025'; // outcome: any days below zero in this year
export const MAX_POINTS = 4;

export const RATED = 'rated';
export const ALREADY_OVERDRAWN = 'already_overdrawn';
export const STALE = 'stale';
export const NOT_ENOUGH_HISTORY = 'not_enough_history';
export type LightStatus = typeof RATED | typeof ALREADY_OVERDRAWN | typeof STALE | typeof NOT_ENOUGH_HISTORY;

export type RuleCode = 'min_bal_over_S' | 'cash_share' | 'inc_cv' | 'bal_trend';

export interface Rule {
  code: RuleCode;
  /** plain English, shown on the card */
  label: string;
  /** plain English cut, shown in the rule list */
  firesWhen: string;
  op: '<' | '>';
  cut: number;
}

export const RULES: readonly Rule[] = [
  {
    code: 'min_bal_over_S',
    label: 'lowest balance under half a month of spending',
    firesWhen: 'lowest balance < 0.5 months of spending',
    op: '<',
    cut: MIN_BAL_CUT,
  },
  { code: 'cash_share', label: 'almost all spending is cash', firesWhen: 'cash > 95% of spending', op: '>', cut: CASH_SHARE_CUT },
  { code: 'inc_cv', label: 'irregular money in', firesWhen: 'money in: std ÷ mean > 0.5', op: '>', cut: INCOME_CV_CUT },
  {
    code: 'bal_trend',
    label: "balance sliding more than 10% of a month's spending per month",
    firesWhen: 'balance trend < -0.10 months of spending per month',
    op: '<',
    cut: BAL_TREND_CUT,
  },
];

/** light_table: the clip range (pandas Series.clip) and the value a missing raw value becomes (fillna). */
const FILL: Record<RuleCode, { clip: readonly [number, number] | null; missing: number }> = {
  min_bal_over_S: { clip: MIN_BAL_CLIP, missing: MIN_BAL_MISSING },
  cash_share: { clip: null, missing: 0 },
  inc_cv: { clip: null, missing: 0 },
  bal_trend: { clip: BAL_TREND_CLIP, missing: 0 },
};

const isMissing = (x: number | null): x is null => x === null || Number.isNaN(x);

/** The value a rule tests: the raw value clipped, or the missing-value fill when it is undefined. */
export function ruleValue(rule: Rule, raw: number | null): number {
  const f = FILL[rule.code];
  if (isMissing(raw)) return f.missing;
  if (!f.clip) return raw;
  const [lo, hi] = f.clip;
  return raw < lo ? lo : raw > hi ? hi : raw;
}

export function ruleFires(rule: Rule, value: number): boolean {
  return rule.op === '<' ? value < rule.cut : value > rule.cut;
}

const NA_TEXT: Record<RuleCode, string> = {
  min_bal_over_S: 'n/a (typical spending in the window is $0)',
  cash_share: 'n/a (no spending in the window)',
  inc_cv: 'n/a (no money in during the window)',
  bal_trend: 'n/a (typical spending in the window is $0)',
};

const UNIT: Record<RuleCode, string> = {
  min_bal_over_S: ' months of spending',
  cash_share: ' of spending',
  inc_cv: '',
  bal_trend: ' months of spending per month',
};

/** Python f"{x:.{d}%}" (Python multiplies by 100 as a float first). */
function pyPercent(x: number, digits: number): string {
  return `${pyFixed(x * 100, digits)}%`;
}

/** Python f"{x:+.{d}f}". */
function pySigned(x: number, digits: number): string {
  const s = pyFixed(x, digits);
  return s.startsWith('-') ? s : `+${s}`;
}

/**
 * Rule.value_text: the account's own (unclipped) value in words, with 2 decimals, or more when 2 would
 * round onto the cut (0.5025 -> "0.503", not "0.50").
 */
export function ruleValueText(rule: Rule, raw: number | null): string {
  if (isMissing(raw)) return NA_TEXT[rule.code];
  const fmt =
    rule.code === 'cash_share'
      ? (x: number, d: number) => pyPercent(x, d - 1)
      : rule.code === 'bal_trend'
        ? pySigned
        : (x: number, d: number) => pyFixed(x, d);
  let d = 2;
  for (const k of [2, 3, 4, 5, 6]) {
    d = k;
    if (fmt(raw, k) !== fmt(rule.cut, k)) break;
  }
  return fmt(raw, d) + UNIT[rule.code];
}

// ---------------------------------------------------------------- backtest

export interface Tier {
  points: number;
  accounts: number;
  wentOverdrawn: number;
}

export function tierRate(t: Tier): number {
  return t.accounts ? t.wentOverdrawn / t.accounts : NaN;
}

export function tierRateText(t: Tier): string {
  if (!t.accounts) return 'n/a';
  const r = tierRate(t);
  return r < 0.01 ? pyPercent(r, 2) : pyPercent(r, 1);
}

export function tierLine(t: Tier, labelYear: string = BACKTEST_LABEL_YEAR): string {
  const pts = t.points === 1 ? 'point' : 'points';
  return (
    `In the ${labelYear} backtest, ${pyFixed(t.wentOverdrawn, 0, true)} of ${pyFixed(t.accounts, 0, true)} ` +
    `accounts with ${t.points} ${pts} went overdrawn (${tierRateText(t)}).`
  );
}

export interface Backtest {
  snapshot: string;
  labelYear: string;
  /** the month accounts.json's light inputs were taken at (T today): a window ending earlier is stale */
  today: string;
  /** points 0..4 */
  tiers: Tier[];
}

export function backtestPopulation(bt: Backtest): number {
  return bt.tiers.reduce((n, t) => n + t.accounts, 0);
}

export function backtestEvents(bt: Backtest): number {
  return bt.tiers.reduce((n, t) => n + t.wentOverdrawn, 0);
}

/** portfolio.json["early_warning"] as a Backtest; refuses a table that isn't points 0..4 in order. */
export function decodeBacktest(file: EarlyWarningFile): Backtest {
  const tiers = file.tiers.map((t) => ({ points: t.points, accounts: t.accounts, wentOverdrawn: t.went_overdrawn }));
  if (tiers.length !== MAX_POINTS + 1 || tiers.some((t, i) => t.points !== i)) {
    throw new Error('portfolio.json early_warning: the tier table must list points 0 to 4 in order');
  }
  return { snapshot: file.snapshot, labelYear: file.label_year, today: file.today, tiers };
}

/** The note under the tier table (app.py's expander caption). */
export function backtestCaption(bt: Backtest): string {
  return (
    `Points = how many rules fire on the account's last ${WINDOW_ROWS} months of data (the opening month is left out). ` +
    `Backtest: rules taken at the end of ${bt.snapshot} on the ${pyFixed(backtestPopulation(bt), 0, true)} accounts with ` +
    `${WINDOW_ROWS}+ months after the opening month that had never gone below zero and were still active in ` +
    `${bt.labelYear}; ${backtestEvents(bt)} of them went overdrawn in ${bt.labelYear}. ` +
    "The light never changes the judges' runway."
  );
}

// ---------------------------------------------------------------- one account

/** One account's rule inputs (resilience.warning.light_table, the "_raw" columns; null = undefined). */
export interface LightInputs {
  rowsUsed: number;
  daysBelowZero: number;
  /** median money out over the window: the rules' month of spending (null with no rows) */
  recentSpending: number | null;
  /** the last month used, the end of the window (null with no rows) */
  lastMonth: string | null;
  raw: Record<RuleCode, number | null>;
}

export function lightInputs(acct: Account): LightInputs {
  return {
    rowsUsed: acct.light_rows_used,
    daysBelowZero: acct.light_days_below_zero,
    recentSpending: acct.light_recent_spending,
    lastMonth: acct.light_last_month,
    raw: {
      min_bal_over_S: acct.light_min_bal_over_S_raw,
      cash_share: acct.light_cash_share_raw,
      inc_cv: acct.light_inc_cv_raw,
      bal_trend: acct.light_bal_trend_raw,
    },
  };
}

export interface RuleResult {
  rule: Rule;
  /** clipped / filled value the rule tests */
  value: number;
  /** the account's own value (null when undefined) */
  raw: number | null;
  fired: boolean;
  valueText: string;
}

export interface Light {
  accountId: number;
  status: LightStatus;
  rowsUsed: number;
  points: number | null;
  /** empty when there is not enough history */
  rules: RuleResult[];
  /** only when status is "rated" */
  tier: Tier | null;
  /** labels of the rules that fired */
  fired: string[];
  /** "Early-warning light 3/4", or "... not enough history" */
  badge: string;
  /** the fired labels joined with "; ", or "no rule fired" (null without points) */
  why: string | null;
  backtestLine: string;
  /** the one line on the customer card */
  line: string;
  /** what "a month of spending" means in rules 1 and 4 (null without rules) */
  spendingNote: string | null;
}

/** Light.spending_note: the rules' month of spending is the window's median money out, not the card's S. */
function spendingNote(recentSpending: number): string {
  const head =
    "In the lowest-balance and balance-trend rules, a month of spending is this account's median " +
    `money out over the same ${WINDOW_ROWS} months: $${pyFixed(recentSpending, 2, true)}`;
  if (recentSpending === 0) return `${head}, so those two rules can't be measured and don't fire.`;
  return `${head}. That is not the card's S (the median over all history), so these months can differ from the Buffer's.`;
}

/**
 * light_from_row: the light from one account's rule inputs and the backtest tiers. `snapshot` = T, the
 * month the inputs were taken at (default: today, bt.today).
 */
export function computeLight(accountId: number, inp: LightInputs, bt: Backtest, snapshot: string = bt.today): Light {
  const rowsUsed = inp.rowsUsed;
  const status: LightStatus =
    rowsUsed < WINDOW_ROWS
      ? NOT_ENOUGH_HISTORY
      : inp.daysBelowZero > 0
        ? ALREADY_OVERDRAWN
        : inp.lastMonth !== snapshot
          ? STALE
          : RATED;
  if (status === NOT_ENOUGH_HISTORY) {
    const backtestLine =
      `Not enough history: the light needs ${WINDOW_ROWS} months after the opening month and this ` +
      `account has ${rowsUsed}, so no points or backtest rate.`;
    return {
      accountId,
      status,
      rowsUsed,
      points: null,
      rules: [],
      tier: null,
      fired: [],
      badge: 'Early-warning light: not enough history',
      why: null,
      backtestLine,
      line: `Early-warning light: ${backtestLine}`,
      spendingNote: null,
    };
  }
  const rules = RULES.map((rule): RuleResult => {
    const raw = isMissing(inp.raw[rule.code]) ? null : inp.raw[rule.code];
    const value = ruleValue(rule, raw);
    return { rule, value, raw, fired: ruleFires(rule, value), valueText: ruleValueText(rule, raw) };
  });
  const points = rules.filter((r) => r.fired).length;
  const tier = status === RATED ? bt.tiers[points] : null;
  const fired = rules.filter((r) => r.fired).map((r) => r.rule.label);
  const badge = `Early-warning light ${points}/${MAX_POINTS}`;
  const backtestLine = tier
    ? tierLine(tier, bt.labelYear)
    : status === STALE
      ? `Activity stops in ${inp.lastMonth}: the points are from the account's last ${WINDOW_ROWS} ` +
        'months up to then, so no backtest rate is shown (the backtest only followed accounts that ' +
        'were still active).'
      : 'Already overdrawn before: this account has gone below zero in its history, so no backtest ' +
        'rate is shown (the backtest only followed accounts that had never gone below zero).';
  const why = fired.length ? fired.join('; ') : 'no rule fired';
  return {
    accountId,
    status,
    rowsUsed,
    points,
    rules,
    tier,
    fired,
    badge,
    why,
    backtestLine,
    line: `${badge}: ${why}. ${backtestLine}`,
    spendingNote: spendingNote(inp.recentSpending ?? NaN),
  };
}

/** The light for one account today (account_light: snapshot = the last month in the data). */
export function accountLight(acct: Account, bt: Backtest): Light {
  return computeLight(acct.id, lightInputs(acct), bt);
}
