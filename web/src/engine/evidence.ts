/**
 * The 2025 backtest evidence, a port of resilience/evidence.py: who went overdrawn in 2025, and what each
 * score said at the 2024-12 snapshot.
 *
 * Population and outcome are the early-warning light's backtest. Every score reads the rows the light reads
 * (each account's full months up to the snapshot):
 *     light          points 0-4
 *     EI runway      the judges' EI 55% runway on the judges' I, S, B over those months; it passes when the
 *                    published (rounded) runway is PASS_MONTHS or more
 *     buffer months  B / S (no spending -> never runs out)
 *
 * Watch-lists of p% hold round(p% x accounts) accounts (halves up), highest risk first: the light by points,
 * then by the lowest min balance / spending (score = points - LIGHT_TIE_BREAK x min_bal_over_S); the runway
 * shortest first before rounding; buffer months fewest first; remaining ties by lowest account_id.
 *
 * The browser reads the tables from portfolio.json (written by the Python module); web/test/parity.test.ts
 * rebuilds every table here from per-account inputs and checks it, and every line, against Python.
 */
import { LAID_OFF_EI, RUNWAY_CAP_MONTHS, runway } from './core';
import type { EvidenceFile, IrregularRow, LiftRow, S6Row } from './data';
import { pyFixed } from './pyformat';

export const PASS_MONTHS = 6;
export const WATCH_POINTS = 2;
export const LIGHT_TIE_BREAK = 1e-6;
export const LIST_PCTS: readonly number[] = Array.from({ length: 30 }, (_, i) => i + 1);
export const HEADLINE_LIST_PCT = 10;
export const WILSON_Z = 1.96;
export const S6_ORIGINS = ['2023-12', '2024-06', '2024-12', '2025-06'] as const;
export const S6_HISTORY = 12;
export const S6_HORIZON = 6;
export const RANKINGS = ['light', 'ei55_runway', 'buffer_months'] as const;
export type Ranking = (typeof RANKINGS)[number];

/** One backtest account at the snapshot (resilience.evidence.score_frame). Infinity = no shortfall / no spending. */
export interface EvidenceScore {
  id: number;
  points: number;
  minBalOverS: number;
  irregular: boolean;
  runwayEi55: number;
  runwayEi55Exact: number;
  bufferMonths: number;
  passesEi55: boolean;
  wentOverdrawn: boolean;
}

export interface EvidenceSummary {
  snapshot: string;
  label_year: string;
  accounts: number;
  went_overdrawn: number;
  passed_ei55: number;
  passed_and_flagged: number;
  watch_points: number;
}

/** score_frame for one account: the light's points and rule-1 value, the judges' I, S, B, and the outcome. */
export function evidenceScore(
  id: number,
  light: { points: number; minBalOverS: number; irregular: boolean },
  I: number,
  S: number,
  B: number,
  wentOverdrawn: boolean,
): EvidenceScore {
  const income = LAID_OFF_EI.incomeMultiplier * I;
  const published = runway(B, 0, S, income);
  const gap = S - income;
  const exact = B <= 0 ? 0 : gap <= 0 ? Infinity : Math.min(B / gap, RUNWAY_CAP_MONTHS);
  const runwayEi55 = published.noShortfall ? Infinity : (published.months as number);
  return {
    id,
    points: light.points,
    minBalOverS: light.minBalOverS,
    irregular: light.irregular,
    runwayEi55,
    runwayEi55Exact: exact,
    bufferMonths: S === 0 ? Infinity : B / S,
    passesEi55: runwayEi55 >= PASS_MONTHS,
    wentOverdrawn,
  };
}

/** round(pct% x accounts), halves up, in integers. */
export function listSize(pct: number, accounts: number): number {
  return Math.floor((2 * pct * accounts + 100) / 200);
}

function riskKey(s: EvidenceScore, ranking: Ranking): number {
  switch (ranking) {
    case 'light':
      return -(s.points - LIGHT_TIE_BREAK * s.minBalOverS);
    case 'ei55_runway':
      return s.runwayEi55Exact;
    case 'buffer_months':
      return s.bufferMonths;
  }
}

/** account_ids, highest risk first; remaining ties by lowest account_id. */
export function riskOrder(scores: readonly EvidenceScore[], ranking: Ranking): number[] {
  return scores
    .map((s) => ({ id: s.id, key: riskKey(s, ranking) }))
    .sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : a.id - b.id))
    .map((x) => x.id);
}

export function liftTable(scores: readonly EvidenceScore[], pcts: readonly number[] = LIST_PCTS): LiftRow[] {
  const went = new Map(scores.map((s) => [s.id, s.wentOverdrawn]));
  const events = scores.filter((s) => s.wentOverdrawn).length;
  const caught = Object.fromEntries(
    RANKINGS.map((r) => {
      const cum = [0];
      for (const id of riskOrder(scores, r)) cum.push(cum[cum.length - 1] + (went.get(id) ? 1 : 0));
      return [r, cum];
    }),
  ) as Record<Ranking, number[]>;
  return pcts.map((p) => {
    const k = listSize(p, scores.length);
    return {
      list_pct: p,
      list_accounts: k,
      light: caught.light[k],
      ei55_runway: caught.ei55_runway[k],
      buffer_months: caught.buffer_months[k],
      events,
    };
  });
}

export function evidenceSummary(scores: readonly EvidenceScore[], snapshot: string, labelYear: string): EvidenceSummary {
  const ev = scores.filter((s) => s.wentOverdrawn);
  const passed = ev.filter((s) => s.passesEi55);
  return {
    snapshot,
    label_year: labelYear,
    accounts: scores.length,
    went_overdrawn: ev.length,
    passed_ei55: passed.length,
    passed_and_flagged: passed.filter((s) => s.points >= WATCH_POINTS).length,
    watch_points: WATCH_POINTS,
  };
}

/** Wilson score interval for k of n (same operation order as Python, so the same doubles). */
export function wilson(k: number, n: number, z: number = WILSON_Z): [number, number] {
  if (n === 0) return [NaN, NaN];
  const p = k / n;
  const den = 1 + (z * z) / n;
  const c = (p + (z * z) / (2 * n)) / den;
  const h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / den;
  return [c - h, c + h];
}

/** The 2x2: irregular money in (yes / no) x the judges' EI test (passes / fails). null = an empty cell. */
export function irregularTable(scores: readonly EvidenceScore[]): IrregularRow[] {
  const rows: IrregularRow[] = [];
  for (const irr of [true, false]) {
    for (const passes of [true, false]) {
      const cell = scores.filter((s) => s.irregular === irr && s.passesEi55 === passes);
      const k = cell.filter((s) => s.wentOverdrawn).length;
      const n = cell.length;
      const [lo, hi] = wilson(k, n);
      rows.push({
        irregular_money_in: irr ? 'yes' : 'no',
        judges_ei55: passes ? 'passes' : 'fails',
        accounts: n,
        went_overdrawn: k,
        rate: n ? k / n : null,
        ci_low: n ? lo : null,
        ci_high: n ? hi : null,
      });
    }
  }
  return rows;
}

export function irregularCell(table: readonly IrregularRow[], irregular: 'yes' | 'no', judges: 'passes' | 'fails') {
  const r = table.find((x) => x.irregular_money_in === irregular && x.judges_ei55 === judges);
  if (!r) throw new Error(`no ${irregular}/${judges} cell`);
  return r;
}

/** One (as-of month, account) pair for the half-year check. */
export interface HalfYear {
  B: number;
  I: number;
  S: number;
  /** null when undefined: then it never flags */
  S6: number | null;
  /** money out over the 6 months that followed */
  nextSpending: number;
}

export function s6Check(rows: readonly HalfYear[]): S6Row[] {
  const ei = (h: HalfYear) => S6_HORIZON * LAID_OFF_EI.incomeMultiplier * h.I;
  const real = rows.map((h) => h.B - (h.nextSpending - ei(h)) < 0);
  const realFails = real.filter(Boolean).length;
  return (['S', 'S6'] as const).map((basis) => {
    const flag = rows.map((h) => {
      const base = basis === 'S' ? h.S : h.S6;
      return base !== null && h.B - (S6_HORIZON * base - ei(h)) < 0;
    });
    return {
      spending_basis: basis,
      account_halfyears: rows.length,
      real_fails: realFails,
      flagged: flag.filter(Boolean).length,
      missed_real_fails: flag.filter((f, i) => !f && real[i]).length,
      false_alarms: flag.filter((f, i) => f && !real[i]).length,
    };
  });
}

// ---------------------------------------------------------------- the lines both apps show

const n0 = (x: number) => pyFixed(x, 0, true);
const pct = (x: number) => `${pyFixed(x * 100, 1)}%`;
const interval = (lo: number, hi: number) => `${pyFixed(lo * 100, 1)}–${pyFixed(hi * 100, 1)}%`;

export function passedLine(s: EvidenceSummary): string {
  return (
    `${n0(s.passed_ei55)} of the ${n0(s.went_overdrawn)} accounts that first went overdrawn in ${s.label_year} had ` +
    `passed the judges' EI 55% test at the ${s.snapshot} snapshot; the light had flagged ${n0(s.passed_and_flagged)} ` +
    `of them (${s.watch_points}+ points).`
  );
}

export function liftLine(lift: readonly LiftRow[], s: EvidenceSummary, at: number = HEADLINE_LIST_PCT): string {
  const r = lift.find((x) => x.list_pct === at);
  if (!r) throw new Error(`no ${at}% row in the lift table`);
  return (
    `On a ${at}% watch-list (${n0(r.list_accounts)} accounts), the light catches ${n0(r.light)} of the ` +
    `${n0(r.events)} accounts that went overdrawn in ${s.label_year}; the judges' EI 55% runway catches ` +
    `${n0(r.ei55_runway)} and buffer months ${n0(r.buffer_months)}.`
  );
}

export function irregularLine(table: readonly IrregularRow[], s: EvidenceSummary): string {
  const a = irregularCell(table, 'yes', 'passes');
  const b = irregularCell(table, 'no', 'fails');
  return (
    `Accounts with irregular money in that pass the judges' EI 55% test: ${n0(a.went_overdrawn)} of ` +
    `${n0(a.accounts)} went overdrawn in ${s.label_year} (${pct(a.rate ?? NaN)}, 95% interval ` +
    `${interval(a.ci_low ?? NaN, a.ci_high ?? NaN)}). Accounts with steady money in that fail it: ` +
    `${n0(b.went_overdrawn)} of ${n0(b.accounts)} (${pct(b.rate ?? NaN)}, ${interval(b.ci_low ?? NaN, b.ci_high ?? NaN)}).`
  );
}

export function irregularCaveat(table: readonly IrregularRow[]): string {
  const a = irregularCell(table, 'yes', 'passes');
  const b = irregularCell(table, 'no', 'fails');
  return (
    `A second finding with small numbers: it rests on ${n0(a.went_overdrawn)} and ${n0(b.went_overdrawn)} ` +
    'overdrafts. It shows who to watch, not why they went overdrawn.'
  );
}

export function s6Line(check: readonly S6Row[], origins: readonly string[] = S6_ORIGINS): string {
  const S = check.find((r) => r.spending_basis === 'S');
  const S6 = check.find((r) => r.spending_basis === 'S6');
  if (!S || !S6) throw new Error('the half-year check needs an S and an S6 row');
  return (
    `Checked forward at ${origins.length} as-of months from ${origins[0]} to ${origins[origins.length - 1]} ` +
    `(${n0(S.account_halfyears)} account half-years, each using only the data up to its month): of the ` +
    `${n0(S.real_fails)} half-years that fail the 6-month EI test on the money out that actually followed, the ` +
    `judges' median month S misses ${n0(S.missed_real_fails)} and half-year spending S6 misses ` +
    `${n0(S6.missed_real_fails)}; S6 raises ${n0(S6.false_alarms)} false alarms against ${n0(S.false_alarms)} for S.`
  );
}

/** Every line, from portfolio.json["evidence"] (resilience.evidence.lines). */
export function evidenceLines(e: EvidenceFile): Record<'passed' | 'lift' | 'irregular' | 'irregular_caveat' | 's6', string> {
  return {
    passed: passedLine(e),
    lift: liftLine(e.lift, e, e.headline_list_pct),
    irregular: irregularLine(e.irregular, e),
    irregular_caveat: irregularCaveat(e.irregular),
    s6: s6Line(e.s6.rows, e.s6.origins),
  };
}
