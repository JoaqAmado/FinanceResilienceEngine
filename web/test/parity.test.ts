/**
 * Parity harness: the TypeScript engine must reproduce the Python engine's outputs.
 *
 *     ../.venv/bin/python ../scripts/export_web_data.py   # regenerate the vectors from Python
 *     npm test
 *
 * Exact equality for runway months, flags, verdicts, steps and every string; money values
 * within 1e-6 (the summary also counts how many are bit-for-bit identical). The early-warning
 * light (resilience/warning.py) is checked exactly too: values, rules, points, status and text. So is the
 * 2025 backtest evidence (resilience/evidence.py): every table rebuilt from per-account inputs, and every line.
 */
import { readFileSync } from 'node:fs';
import { isDeepStrictEqual } from 'node:util';
import { afterAll, describe, expect, it } from 'vitest';
import {
  ALREADY_OVERDRAWN,
  BACKTEST_LABEL_YEAR,
  BACKTEST_SNAPSHOT,
  BAL_TREND_CLIP,
  BAL_TREND_CUT,
  BASELINE,
  CASH_SHARE_CUT,
  DOUBLE_WHAMMY,
  EI_2026_MAX_MONTHLY,
  EI_2026_MAX_WEEKLY,
  EI_WAITING_WEEK_WAIVED_UNTIL,
  FURNACE,
  INCOME_CV_CUT,
  LAID_OFF_EI,
  LAID_OFF_EI_CAPPED,
  MAX_POINTS,
  MIN_BAL_CLIP,
  MIN_BAL_CUT,
  MIN_BAL_MISSING,
  NOT_ENOUGH_HISTORY,
  NO_SHORTFALL_LABEL,
  PRESETS,
  RATED,
  RULES,
  RUNWAY_CAP_MONTHS,
  STALE,
  WAITING_WEEK_LABEL,
  WEEKS_PER_MONTH,
  WINDOW_ROWS,
  accountFlags,
  accountLight,
  applyShock,
  backtestEvents,
  backtestPopulation,
  backupLadder,
  backupPlan,
  balancePath,
  calendarPath,
  computeLight,
  creditAdvice,
  evidenceLines,
  evidenceScore,
  evidenceSummary,
  HEADLINE_LIST_PCT,
  irregularCaveat,
  irregularLine,
  irregularTable,
  LIGHT_TIE_BREAK,
  liftLine,
  liftTable,
  LIST_PCTS,
  listSize,
  PASS_MONTHS,
  passedLine,
  RANKINGS,
  riskOrder,
  S6_HISTORY,
  S6_HORIZON,
  S6_ORIGINS,
  s6Check,
  s6Line,
  WATCH_POINTS,
  WILSON_Z,
  wilson,
  decodeAccounts,
  decodeBacktest,
  facts,
  goalPlan,
  goalShockFor,
  greyZoneNote,
  isJobLoss,
  loanInTrouble,
  makeShock,
  npRound,
  planPath,
  pyFixed,
  pyG,
  pyPercent0,
  pyRound,
  ruleFires,
  ruleValueText,
  templateStory,
  tierLine,
  tierRateText,
  withShock,
} from '../src/engine';
import type {
  Account,
  AccountsFile,
  EvidenceScore,
  IrregularRow,
  LiftRow,
  Light,
  PortfolioFile,
  RuleCode,
  RunwayResult,
  S6Row,
  Shock,
} from '../src/engine';

type PyResult = [number | null, boolean, number, number, number, number, number, boolean];
type PyGoal = [number, number, number, number, number | null, string];
interface PyLadder {
  targetMonths: number;
  shocked: PyResult;
  alreadySafe: boolean;
  bufferWiped: boolean;
  overdrawn: boolean;
  rungs: [string, number, PyResult, boolean][];
  firstSufficient: number | null;
  cashOrCreditNeeded: number;
  verdict: string;
}
interface PyBackup {
  targetMonths: number;
  shocked: PyResult;
  monthlyCutNeeded: number;
  flexiblePool: number;
  cutShareOfFlexible: number | null;
  feasible: boolean;
  afterCut: PyResult;
  bufferWiped: boolean;
  cashNeeded: number;
  normalSurplus: number;
}
interface Vectors {
  meta: { accounts: number; sample: number; story_accounts: number; edge_ids: number[]; counts: Record<string, number> };
  constants: Record<string, number | string | number[]>;
  named_shocks: Record<string, Shock>;
  presets: Record<string, Shock>;
  shocks: Record<string, Shock>;
  ids: number[];
  applyShock: Record<string, PyResult[]>;
  flags: [string, string][][];
  loanInTrouble: boolean[];
  greyZone: Record<string, (string | null)[]>;
  greyZoneNoShock: (string | null)[];
  calendarPath: [number, string, number, number | null][];
  plans: {
    id: number;
    shock: string;
    t: number;
    goalS: PyGoal;
    goalEI: PyGoal;
    backup: PyBackup;
    ladder: PyLadder;
    credit: string | null;
    planPath: number[];
  }[];
  goalShockFor: Record<string, Shock>;
  balancePath: [number, string, number, number[]][];
  stories: {
    id: number;
    preset: string;
    target: number;
    judgeShock: Shock;
    realShock: Shock;
    planBasis: string;
    facts: unknown;
    story: unknown;
  }[];
  format: [number, string, string, string, string, number, number, string][];
  lightConstants: Record<string, number | string | number[]> & { rules: [string, string, string, string, number][] };
  lightToday: PyLight[];
  lightBacktest: {
    snapshot: string;
    labelYear: string;
    population: number;
    events: number;
    tiers: PyTier[];
    rows: PyLightRow[];
    lights: PyLight[];
  };
  lightValueText: [RuleCode, number | null, string][];
  lightTiers: PyTier[];
  /** Rule.fires on each cut and one double either side: [code, value, fired] */
  lightCuts: [RuleCode, number, boolean][];
  evidence: {
    constants: Record<string, number | number[] | string[]>;
    /** [id, I, S, B]: the judges' numbers at the snapshot on the light's rows */
    snapshot: [number, number, number, number][];
    /** [id, points, minBalOverS, irregular, runwayEi55, runwayEi55Exact, bufferMonths, passesEi55, wentOverdrawn]; null = +inf */
    scores: [number, number, number, boolean, number | null, number | null, number | null, boolean, boolean][];
    order: Record<string, number[]>;
    lift: LiftRow[];
    summary: Record<string, string | number>;
    irregular: IrregularRow[];
    /** [B, I, S, S6, nextSpending] */
    halfyears: [number, number, number, number | null, number][];
    s6: S6Row[];
    lines: Record<string, string>;
    /** [k, n, lo, hi] */
    wilson: [number, number, number | null, number | null][];
    /** [pct, accounts, size] */
    listSize: [number, number, number][];
  };
}
/** [status, rowsUsed, points, [[value, raw, fired, valueText] per rule], badge, backtestLine, line, spendingNote] */
type PyLight = [
  string,
  number,
  number | null,
  [number, number | null, boolean, string][],
  string,
  string,
  string,
  string | null,
];
/** [id, rows_used, days_below_zero, min_bal_over_S_raw, cash_share_raw, inc_cv_raw, bal_trend_raw, recent_spending,
 * last_month, observed, went] */
type PyLightRow = [
  number,
  number,
  number,
  number | null,
  number | null,
  number | null,
  number | null,
  number | null,
  string | null,
  boolean,
  boolean,
];
/** [points, accounts, wentOverdrawn, rateText, line] */
type PyTier = [number, number, number, string, string];

const read = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const V: Vectors = read('./vectors.json');
const accounts: Account[] = decodeAccounts(read('../public/data/accounts.json') as AccountsFile);
const portfolio: PortfolioFile = read('../public/data/portfolio.json');
const byId = new Map(accounts.map((a) => [a.id, a]));
const acct = (id: number): Account => {
  const a = byId.get(id);
  if (!a) throw new Error(`account ${id} not in accounts.json`);
  return a;
};
const shocks: Record<string, Shock> = Object.fromEntries(
  Object.entries(V.shocks).map(([k, s]) => [k, makeShock(s)]),
);

const MONEY_TOL = 1e-6;

/** Collects every comparison so one test reports all mismatches, not just the first. */
class Checker {
  checks = 0;
  moneyChecks = 0;
  moneyBitExact = 0;
  failures: string[] = [];

  constructor(readonly name: string) {}

  private fail(label: string, actual: unknown, expected: unknown) {
    if (this.failures.length < 25) {
      this.failures.push(`${label}: got ${JSON.stringify(actual)} expected ${JSON.stringify(expected)}`);
    } else {
      this.failures.length === 25 && this.failures.push('... more failures');
    }
  }

  same(label: string, actual: unknown, expected: unknown) {
    this.checks++;
    if (!(actual === expected || (Number.isNaN(actual) && Number.isNaN(expected)))) this.fail(label, actual, expected);
  }

  deep(label: string, actual: unknown, expected: unknown) {
    this.checks++;
    if (!isDeepStrictEqual(actual, expected)) this.fail(label, actual, expected);
  }

  money(label: string, actual: number | null, expected: number | null) {
    this.checks++;
    this.moneyChecks++;
    if (actual === null || expected === null) {
      if (actual !== expected) this.fail(label, actual, expected);
      else this.moneyBitExact++;
      return;
    }
    if (Object.is(actual, expected) || actual === expected) this.moneyBitExact++;
    if (!(Math.abs(actual - expected) <= MONEY_TOL)) this.fail(label, actual, expected);
  }

  result(label: string, r: RunwayResult, e: PyResult) {
    this.same(`${label}.months`, r.months, e[0]);
    this.same(`${label}.noShortfall`, r.noShortfall, e[1]);
    this.money(`${label}.bufferLeft`, r.bufferLeft, e[2]);
    this.money(`${label}.gap`, r.gap, e[3]);
    this.money(`${label}.incomeAfter`, r.incomeAfter, e[4]);
    this.money(`${label}.spendingAfter`, r.spendingAfter, e[5]);
    this.money(`${label}.oneOff`, r.oneOff, e[6]);
    this.same(`${label}.capped`, r.capped, e[7]);
  }

  light(label: string, l: Light, e: PyLight) {
    const [status, rowsUsed, points, rules, badge, backtestLine, line, spendingNote] = e;
    this.same(`${label}.status`, l.status, status);
    this.same(`${label}.rowsUsed`, l.rowsUsed, rowsUsed);
    this.same(`${label}.points`, l.points, points);
    this.same(`${label}.rules`, l.rules.length, rules.length);
    l.rules.forEach((r, i) => {
      const er = rules[i];
      if (!er) return;
      const L = `${label}.${r.rule.code}`;
      this.same(`${L}.value`, r.value, er[0]); // exact: the same double, clipped and filled the same way
      this.same(`${L}.raw`, r.raw, er[1]);
      this.same(`${L}.fired`, r.fired, er[2]);
      this.same(`${L}.valueText`, r.valueText, er[3]);
    });
    this.deep(`${label}.fired`, l.fired, l.rules.filter((r) => r.fired).map((r) => r.rule.label));
    this.same(`${label}.tier`, l.tier?.points ?? null, status === RATED ? points : null);
    this.same(`${label}.badge`, l.badge, badge);
    this.same(`${label}.backtestLine`, l.backtestLine, backtestLine);
    this.same(`${label}.line`, l.line, line);
    this.same(`${label}.spendingNote`, l.spendingNote, spendingNote);
  }

  done() {
    summary.push(this);
    expect(this.failures, `${this.name}: ${this.failures.length} mismatches`).toEqual([]);
    expect(this.checks).toBeGreaterThan(0);
  }
}

const summary: Checker[] = [];

afterAll(() => {
  const total = summary.reduce((n, c) => n + c.checks, 0);
  const money = summary.reduce((n, c) => n + c.moneyChecks, 0);
  const exact = summary.reduce((n, c) => n + c.moneyBitExact, 0);
  const lines = summary.map(
    (c) =>
      `  ${c.name.padEnd(34)} ${String(c.checks).padStart(8)} checks` +
      (c.moneyChecks ? `  (money ${c.moneyBitExact}/${c.moneyChecks} bit-exact)` : '') +
      `  ${c.failures.length ? 'FAIL' : 'ok'}`,
  );
  console.log(
    `\nParity vs Python: ${total} checks, ${summary.filter((c) => c.failures.length).length} groups failing\n` +
      `${lines.join('\n')}\n  money values: ${exact}/${money} bit-exact, all within ${MONEY_TOL}\n`,
  );
});

describe('parity with the Python engine', () => {
  it('constants, named shocks and twist cards', () => {
    const c = new Checker('constants + shocks');
    c.same('RUNWAY_CAP_MONTHS', RUNWAY_CAP_MONTHS, V.constants.RUNWAY_CAP_MONTHS);
    c.same('EI_2026_MAX_MONTHLY', EI_2026_MAX_MONTHLY, V.constants.EI_2026_MAX_MONTHLY);
    c.same('EI_2026_MAX_WEEKLY', EI_2026_MAX_WEEKLY, V.constants.EI_2026_MAX_WEEKLY);
    c.same('WEEKS_PER_MONTH', WEEKS_PER_MONTH, V.constants.WEEKS_PER_MONTH);
    c.same('NO_SHORTFALL_LABEL', NO_SHORTFALL_LABEL, V.constants.NO_SHORTFALL_LABEL);
    c.same('EI_WAITING_WEEK_WAIVED_UNTIL', EI_WAITING_WEEK_WAIVED_UNTIL, V.constants.EI_WAITING_WEEK_WAIVED_UNTIL);
    c.same('WAITING_WEEK_LABEL', WAITING_WEEK_LABEL, V.constants.WAITING_WEEK_LABEL);
    const named: Record<string, Shock> = { BASELINE, LAID_OFF_EI, LAID_OFF_EI_CAPPED, FURNACE, DOUBLE_WHAMMY };
    for (const [k, s] of Object.entries(V.named_shocks)) c.deep(`named ${k}`, named[k], s);
    const presets: Record<string, Shock> = PRESETS;
    c.deep('preset names', Object.keys(presets), Object.keys(V.presets));
    for (const [k, s] of Object.entries(V.presets)) c.deep(`preset ${k}`, presets[k], s);
    for (const [k, s] of Object.entries(V.shocks)) c.deep(`makeShock round-trip ${k}`, shocks[k], s);
    c.done();
  });

  it('accounts.json decodes to every account, in the vectors order', () => {
    const c = new Checker('accounts');
    c.same('count', accounts.length, V.meta.accounts);
    c.deep('ids', accounts.map((a) => a.id), V.ids);
    for (const id of V.meta.edge_ids) c.same(`edge ${id} present`, byId.has(id), true);
    c.done();
  });

  it('applyShock: every account under every shock', () => {
    const c = new Checker('applyShock');
    for (const [k, rows] of Object.entries(V.applyShock)) {
      const s = shocks[k];
      V.ids.forEach((id, i) => c.result(`${k}/${id}`, applyShock(acct(id), s), rows[i]));
    }
    c.done();
  });

  it('accountFlags and loanInTrouble: every account', () => {
    const c = new Checker('accountFlags');
    V.ids.forEach((id, i) => {
      const got = accountFlags(acct(id));
      c.deep(`${id} codes`, got.map((f) => f[0]), V.flags[i].map((f) => f[0]));
      c.deep(`${id} texts`, got, V.flags[i]);
      c.same(`${id} loanInTrouble`, loanInTrouble(acct(id)), V.loanInTrouble[i]);
    });
    c.done();
  });

  it('greyZoneNote: only on the plain EI 55% twist', () => {
    const c = new Checker('greyZoneNote');
    for (const [k, notes] of Object.entries(V.greyZone)) {
      V.ids.forEach((id, i) => c.same(`${k}/${id}`, greyZoneNote(applyShock(acct(id), shocks[k]), shocks[k]), notes[i]));
    }
    V.ids.forEach((id, i) =>
      c.same(`no shock arg/${id}`, greyZoneNote(applyShock(acct(id), shocks.ei55_s6)), V.greyZoneNoShock[i]),
    );
    c.done();
  });

  it('calendarPath: sampled accounts', () => {
    const c = new Checker('calendarPath');
    for (const [id, k, start, expected] of V.calendarPath) {
      const got = calendarPath(acct(id), shocks[k], start);
      c.same(`${k}/${id}/start ${start}`, got === Infinity ? null : got, expected);
    }
    c.done();
  });

  it('goalShockFor: every shock', () => {
    const c = new Checker('goalShockFor');
    for (const [k, s] of Object.entries(V.goalShockFor)) c.deep(k, goalShockFor(shocks[k]), s);
    c.done();
  });

  it('goalPlan (both kinds), backupPlan, backupLadder, creditAdvice, planPath', () => {
    const c = new Checker('plans');
    for (const p of V.plans) {
      const a = acct(p.id);
      const s = shocks[p.shock];
      const L = `${p.shock}/${p.id}/t${p.t}`;

      const goals: [string, ReturnType<typeof goalPlan>, PyGoal][] = [
        ['goalS', goalPlan(a, p.t, 'months_of_S'), p.goalS],
        ['goalEI', goalPlan(a, p.t, 'ei_proof', goalShockFor(s)), p.goalEI],
      ];
      for (const [name, g, e] of goals) {
        c.money(`${L} ${name}.targetBuffer`, g.targetBuffer, e[0]);
        c.money(`${L} ${name}.currentBuffer`, g.currentBuffer, e[1]);
        c.money(`${L} ${name}.shortfall`, g.shortfall, e[2]);
        c.money(`${L} ${name}.monthlySurplus`, g.monthlySurplus, e[3]);
        c.same(`${L} ${name}.monthsToTarget`, g.monthsToTarget, e[4]);
        c.same(`${L} ${name}.targetKind`, g.targetKind, e[5]);
      }

      const b = backupPlan(a, s, p.t);
      const eb = p.backup;
      c.same(`${L} backup.targetMonths`, b.targetMonths, eb.targetMonths);
      c.result(`${L} backup.shocked`, b.shocked, eb.shocked);
      c.money(`${L} backup.monthlyCutNeeded`, b.monthlyCutNeeded, eb.monthlyCutNeeded);
      c.money(`${L} backup.flexiblePool`, b.flexiblePool, eb.flexiblePool);
      c.money(`${L} backup.cutShareOfFlexible`, b.cutShareOfFlexible, eb.cutShareOfFlexible);
      c.same(`${L} backup.feasible`, b.feasible, eb.feasible);
      c.result(`${L} backup.afterCut`, b.afterCut, eb.afterCut);
      c.same(`${L} backup.bufferWiped`, b.bufferWiped, eb.bufferWiped);
      c.money(`${L} backup.cashNeeded`, b.cashNeeded, eb.cashNeeded);
      c.money(`${L} backup.normalSurplus`, b.normalSurplus, eb.normalSurplus);

      const lad = backupLadder(a, s, p.t);
      const el = p.ladder;
      c.same(`${L} ladder.targetMonths`, lad.targetMonths, el.targetMonths);
      c.result(`${L} ladder.shocked`, lad.shocked, el.shocked);
      c.same(`${L} ladder.alreadySafe`, lad.alreadySafe, el.alreadySafe);
      c.same(`${L} ladder.bufferWiped`, lad.bufferWiped, el.bufferWiped);
      c.same(`${L} ladder.overdrawn`, lad.overdrawn, el.overdrawn);
      c.deep(`${L} ladder.steps`, lad.rungs.map((r) => r.step), el.rungs.map((r) => r[0]));
      lad.rungs.forEach((r, i) => {
        const er = el.rungs[i];
        if (!er) return;
        c.money(`${L} rung ${i} saving`, r.monthlySaving, er[1]);
        c.result(`${L} rung ${i}`, r.result, er[2]);
        c.same(`${L} rung ${i} reachesTarget`, r.reachesTarget, er[3]);
      });
      c.same(`${L} ladder.firstSufficient`, lad.firstSufficient, el.firstSufficient);
      c.money(`${L} ladder.cashOrCreditNeeded`, lad.cashOrCreditNeeded, el.cashOrCreditNeeded);
      c.same(`${L} ladder.verdict`, lad.verdict, el.verdict);

      const credit = lad.cashOrCreditNeeded ? creditAdvice(a, lad.cashOrCreditNeeded, isJobLoss(s)) : null;
      c.same(`${L} creditAdvice`, credit, p.credit);

      const path = planPath(a, s, lad, p.planPath.length - 1);
      c.same(`${L} planPath length`, path.length, p.planPath.length);
      path.forEach((v, t) => c.money(`${L} planPath[${t}]`, v, p.planPath[t]));
    }
    c.done();
  });

  it('balancePath: sampled accounts', () => {
    const c = new Checker('balancePath');
    for (const [id, k, months, expected] of V.balancePath) {
      const path = balancePath(acct(id), shocks[k], months);
      c.same(`${k}/${id} length`, path.length, expected.length);
      path.forEach((v, t) => c.money(`${k}/${id}[${t}]`, v, expected[t]));
    }
    c.done();
  });

  it('facts + templateStory: the app pipeline, string for string', () => {
    const c = new Checker('templateStory');
    for (const s of V.stories) {
      const a = acct(s.id);
      const judgeShock = makeShock(s.judgeShock);
      const realShock = makeShock(s.realShock);
      const L = `${s.preset}/${s.id}/t${s.target}`;
      c.deep(`${L} card`, (PRESETS as Record<string, Shock>)[s.preset], s.judgeShock);
      const judge = applyShock(a, judgeShock);
      const jan = calendarPath(a, judgeShock);
      const g = goalPlan(a, s.target, 'ei_proof', goalShockFor(realShock));
      const lad = backupLadder(a, realShock, s.target);
      const f = facts(
        s.id,
        a,
        judgeShock,
        judge,
        { 'half-year spending': applyShock(a, withShock(judgeShock, { spendingBasis: 'S6' })), 'starting in January': jan },
        lad,
        g.targetBuffer,
        g.shortfall,
        g.monthsToTarget,
        s.target,
        s.planBasis,
      );
      c.deep(`${L} facts`, f, s.facts);
      c.deep(`${L} story`, templateStory(f), s.story);
    }
    c.done();
  });

  it('portfolio headline counts recomputed from accounts.json', () => {
    const c = new Checker('portfolio headlines');
    const fails = (s: Shock) =>
      accounts.filter((a) => {
        const r = applyShock(a, s);
        return !r.noShortfall && (r.months as number) < 6;
      }).length;
    const h = portfolio.headlines;
    c.same('accounts', accounts.length, h.accounts);
    c.same('fail_6mo_ei55', fails(LAID_OFF_EI), h.fail_6mo_ei55);
    c.same('fail_6mo_ei55_cap2026', fails(LAID_OFF_EI_CAPPED), h.fail_6mo_ei55_cap2026);
    c.same('fail_6mo_ei55_S6', fails(withShock(LAID_OFF_EI, { spendingBasis: 'S6' })), h.fail_6mo_ei55_S6);
    c.same('fail_6mo_ei55_pension_aware', fails(withShock(LAID_OFF_EI, { pensionAware: true })), h.fail_6mo_ei55_pension_aware);
    c.same(
      'fail_6mo_ei55_january_path',
      accounts.filter((a) => calendarPath(a, LAID_OFF_EI) < 6).length,
      h.fail_6mo_ei55_january_path,
    );
    c.same('fail_6mo_furnace', fails(FURNACE), h.fail_6mo_furnace);
    c.same('fail_6mo_double_whammy', fails(DOUBLE_WHAMMY), h.fail_6mo_double_whammy);
    c.same('ei_cap_monthly_2026', pyRound(EI_2026_MAX_MONTHLY, 2), h.ei_cap_monthly_2026);
    c.same('baseline is not a shock', fails(BASELINE) <= fails(LAID_OFF_EI), true);
    c.done();
  });

  it('realistic cuts and dollar cushions recomputed from accounts.json = portfolio.json', () => {
    const c = new Checker('realistic cuts + cushions');
    // resilience/portfolio.py per_account: the EI 55% cut back to 6 months, as a share of S
    const failing = accounts.filter((a) => {
      const r = applyShock(a, LAID_OFF_EI);
      return !r.noShortfall && (r.months as number) < 6 && a.B > 0;
    });
    const pct = failing.map((a) => (Math.max(a.S - 0.55 * a.I - a.B / 6, 0) / a.S) * 100);
    const cuts = [...(V.constants.REALISTIC_CUT_PCTS as number[]), V.constants.QUARTER_CUT_PCT as number];
    const rebuilt = cuts.map((k) => {
      const n = pct.filter((p) => p <= k).length;
      return { max_cut_pct: k, accounts: n, failing_with_buffer: failing.length,
               share_pct: pyRound((n / failing.length) * 100, 1) };
    });
    c.deep('realistic_cuts = portfolio.json', rebuilt, portfolio.realistic_cuts);
    c.deep('cuts tested', cuts, [13, 16, 25]);
    // income bands (pd.cut on I, right=False): median buffer B and median spending S in dollars
    const edges = [0, 2500, 5000, 7500, 10000, 15000, 20000, Infinity];
    const median = (xs: number[]) => {
      const s = [...xs].sort((x, y) => x - y);
      const m = s.length >> 1;
      return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
    };
    portfolio.income_bands.forEach((b, i) => {
      const inBand = accounts.filter((a) => a.I >= edges[i] && a.I < edges[i + 1]);
      c.same(`${b.income_band} accounts`, inBand.length, b.accounts);
      c.same(`${b.income_band} median_B`, npRound(median(inBand.map((a) => a.B)), 0), b.median_B);
      c.same(`${b.income_band} median_S`, npRound(median(inBand.map((a) => a.S)), 0), b.median_S);
    });
    c.done();
  });

  it('Python rounding and formatting: ties, extremes, real values', () => {
    const c = new Checker('pyformat');
    for (const [x, money0, fixed0, fixed1, g, round2, np1, pct0] of V.format) {
      c.same(`${x} :,.0f`, pyFixed(x, 0, true), money0);
      c.same(`${x} :.0f`, pyFixed(x, 0), fixed0);
      c.same(`${x} :.1f`, pyFixed(x, 1), fixed1);
      c.same(`${x} :g`, pyG(x), g);
      c.same(`${x} round(x, 2)`, Object.is(pyRound(x, 2), round2), true);
      c.same(`${x} np.round(x, 1)`, Object.is(npRound(x, 1), np1), true);
      c.same(`${x} :.0%`, pyPercent0(x), pct0);
    }
    c.done();
  });

  describe('2025 backtest evidence (resilience/evidence.py)', () => {
    const E = V.evidence;
    const bt = decodeBacktest(portfolio.early_warning);
    const inf = (v: number | null) => (v === null ? Infinity : v);
    // the population and the light's inputs at the snapshot come from the light backtest vectors
    const scores: EvidenceScore[] = (() => {
      const judges = new Map(E.snapshot.map(([id, I, S, B]) => [id, { I, S, B }]));
      const out: EvidenceScore[] = [];
      for (const row of V.lightBacktest.rows) {
        const [id, rowsUsed, daysBelowZero, min, cash, cv, trend, recentSpending, lastMonth, observed, went] = row;
        const raw = { min_bal_over_S: min, cash_share: cash, inc_cv: cv, bal_trend: trend };
        const l = computeLight(id, { rowsUsed, daysBelowZero, recentSpending, lastMonth, raw }, bt, V.lightBacktest.snapshot);
        if (l.status !== RATED || !observed) continue;
        const j = judges.get(id);
        if (!j) throw new Error(`account ${id} is in the backtest but has no snapshot I, S, B`);
        const light = {
          points: l.points as number,
          minBalOverS: l.rules.find((r) => r.rule.code === 'min_bal_over_S')!.value,
          irregular: l.rules.find((r) => r.rule.code === 'inc_cv')!.fired,
        };
        out.push(evidenceScore(id, light, j.I, j.S, j.B, went));
      }
      return out;
    })();
    const P = portfolio.evidence;

    it('constants', () => {
      const c = new Checker('evidence constants');
      const ts: Record<string, number | readonly number[] | readonly string[]> = {
        PASS_MONTHS,
        WATCH_POINTS,
        LIGHT_TIE_BREAK,
        LIST_PCTS,
        HEADLINE_LIST_PCT,
        WILSON_Z,
        S6_ORIGINS,
        S6_HISTORY,
        S6_HORIZON,
        RANKINGS,
      };
      c.deep('constant names', Object.keys(ts).sort(), Object.keys(E.constants).sort());
      for (const [k, v] of Object.entries(ts)) c.deep(k, Array.isArray(v) ? [...v] : v, E.constants[k]);
      for (const [p, n, k] of E.listSize) c.same(`listSize(${p}, ${n})`, listSize(p, n), k);
      for (const [k, n, lo, hi] of E.wilson) {
        const [a, b] = wilson(k, n);
        c.same(`wilson(${k}, ${n}) low`, Number.isNaN(a) ? null : a, lo);
        c.same(`wilson(${k}, ${n}) high`, Number.isNaN(b) ? null : b, hi);
      }
      c.done();
    });

    it('every backtest account: points, runway, buffer months, pass and outcome', () => {
      const c = new Checker('evidence scores');
      c.same('population', scores.length, E.scores.length);
      c.same('3,847 accounts', scores.length, 3847);
      scores.forEach((s, i) => {
        const [id, points, mb, irregular, rw, exact, buf, passes, went] = E.scores[i];
        const L = `${id}`;
        c.same(`${L} id`, s.id, id);
        c.same(`${L} points`, s.points, points);
        c.same(`${L} minBalOverS`, s.minBalOverS, mb);
        c.same(`${L} irregular`, s.irregular, irregular);
        c.same(`${L} runwayEi55`, s.runwayEi55, inf(rw));
        c.same(`${L} runwayEi55Exact`, s.runwayEi55Exact, inf(exact));
        c.same(`${L} bufferMonths`, s.bufferMonths, inf(buf));
        c.same(`${L} passesEi55`, s.passesEi55, passes);
        c.same(`${L} wentOverdrawn`, s.wentOverdrawn, went);
      });
      for (const r of RANKINGS) c.deep(`order ${r}`, riskOrder(scores, r), E.order[r]);
      c.done();
    });

    it('lift chart, passed-but-overdrawn and the 2x2, rebuilt = Python = portfolio.json', () => {
      const c = new Checker('evidence tables');
      const lift = liftTable(scores);
      c.deep('lift = Python', lift, E.lift);
      c.deep('lift = portfolio.json', lift, P.lift);
      const s = evidenceSummary(scores, bt.snapshot, bt.labelYear);
      c.deep('summary = Python', s, E.summary);
      const { headline_list_pct, lift: _l, irregular: _i, s6: _s, ...fileSummary } = P;
      c.deep('summary = portfolio.json', s, fileSummary);
      c.same('headline list', headline_list_pct, HEADLINE_LIST_PCT);
      const irr = irregularTable(scores);
      c.deep('2x2 = Python', irr, E.irregular);
      c.deep('2x2 = portfolio.json', irr, P.irregular);
      // the pinned headline numbers
      const at10 = lift.find((r) => r.list_pct === 10)!;
      c.deep('10% list', [at10.list_accounts, at10.light, at10.ei55_runway, at10.buffer_months, at10.events], [385, 47, 25, 29, 75]);
      c.deep('passed / flagged', [s.passed_ei55, s.passed_and_flagged], [28, 17]);
      c.same('lift line', liftLine(lift, s), E.lines.lift);
      c.same('passed line', passedLine(s), E.lines.passed);
      c.same('2x2 line', irregularLine(irr, s), E.lines.irregular);
      c.same('2x2 caveat', irregularCaveat(irr), E.lines.irregular_caveat);
      c.done();
    });

    it('half-year spending checked forward, rebuilt = Python = portfolio.json, and every line', () => {
      const c = new Checker('evidence s6');
      const rows = E.halfyears.map(([B, I, S, S6, nextSpending]) => ({ B, I, S, S6, nextSpending }));
      const check = s6Check(rows);
      c.deep('s6 = Python', check, E.s6);
      c.deep('s6 = portfolio.json', check, P.s6.rows);
      c.deep('origins', P.s6.origins, [...S6_ORIGINS]);
      c.same('horizon', P.s6.horizon, S6_HORIZON);
      c.same('s6 line', s6Line(check), E.lines.s6);
      c.deep('every line from portfolio.json', evidenceLines(P), E.lines);
      c.done();
    });
  });

  describe('early-warning light (resilience/warning.py)', () => {
    const bt = decodeBacktest(portfolio.early_warning);
    const tiersOf = (rows: PyTier[]) => rows.map(([p, n, k]) => [p, n, k]);

    it('constants, cuts and rule wording', () => {
      const c = new Checker('light constants');
      const K = V.lightConstants;
      const ts: Record<string, number | string | readonly number[]> = {
        WINDOW_ROWS,
        MIN_BAL_CUT,
        MIN_BAL_CLIP,
        MIN_BAL_MISSING,
        CASH_SHARE_CUT,
        INCOME_CV_CUT,
        BAL_TREND_CUT,
        BAL_TREND_CLIP,
        BACKTEST_SNAPSHOT,
        BACKTEST_LABEL_YEAR,
        MAX_POINTS,
        RATED,
        ALREADY_OVERDRAWN,
        NOT_ENOUGH_HISTORY,
        STALE,
      };
      c.deep('constant names', Object.keys(ts).sort(), Object.keys(K).filter((k) => k !== 'rules').sort());
      for (const [k, v] of Object.entries(ts)) c.deep(k, Array.isArray(v) ? [...v] : v, K[k]);
      c.deep('rules', RULES.map((r) => [r.code, r.label, r.firesWhen, r.op, r.cut]), K.rules);
      c.done();
    });

    it('every account today: values, rules fired, points, status and the card line', () => {
      const c = new Checker('light today');
      c.same('one light per account', V.lightToday.length, V.ids.length);
      c.same('4,500 accounts', V.ids.length, 4500);
      c.deep('portfolio.json tiers = Python backtest', bt.tiers.map((t) => [t.points, t.accounts, t.wentOverdrawn]),
        tiersOf(V.lightBacktest.tiers));
      c.same('snapshot', bt.snapshot, V.lightBacktest.snapshot);
      c.same('label year', bt.labelYear, V.lightBacktest.labelYear);
      V.ids.forEach((id, i) => c.light(`${id}`, accountLight(acct(id), bt), V.lightToday[i]));
      c.done();
    });

    it('backtest snapshot: every account, and the tier table rebuilt from per-account rules', () => {
      const c = new Checker('light backtest');
      const B = V.lightBacktest;
      c.same('rows', B.rows.length, V.ids.length);
      const tally = Array.from({ length: MAX_POINTS + 1 }, (_, p) => ({ points: p, accounts: 0, wentOverdrawn: 0 }));
      const statuses = new Set<string>();
      B.rows.forEach((row, i) => {
        const [id, rowsUsed, daysBelowZero, min, cash, cv, trend, recentSpending, lastMonth, observed, went] = row;
        const raw = { min_bal_over_S: min, cash_share: cash, inc_cv: cv, bal_trend: trend };
        const l = computeLight(id, { rowsUsed, daysBelowZero, recentSpending, lastMonth, raw }, bt, B.snapshot);
        c.light(`${B.snapshot}/${id}`, l, B.lights[i]);
        statuses.add(l.status);
        // population: rated at the snapshot and still observed in the label year
        if (l.status === RATED && observed) {
          tally[l.points as number].accounts++;
          if (went) tally[l.points as number].wentOverdrawn++;
        }
      });
      c.deep('all four statuses covered', [...statuses].sort(), [ALREADY_OVERDRAWN, NOT_ENOUGH_HISTORY, RATED, STALE]);
      c.deep('tiers rebuilt', tally.map((t) => [t.points, t.accounts, t.wentOverdrawn]), tiersOf(B.tiers));
      const rebuilt = { snapshot: B.snapshot, labelYear: B.labelYear, today: B.snapshot, tiers: tally };
      c.same('population', backtestPopulation(rebuilt), B.population);
      c.same('events', backtestEvents(rebuilt), B.events);
      c.same('population 3,847', B.population, 3847);
      c.same('events 75', B.events, 75);
      B.tiers.forEach(([, , , rateText, line], p) => {
        c.same(`tier ${p} rateText`, tierRateText(tally[p]), rateText);
        c.same(`tier ${p} line`, tierLine(tally[p], B.labelYear), line);
      });
      c.done();
    });

    it('value text and tier text: cuts, near-cuts, ties, empty tiers', () => {
      const c = new Checker('light text');
      const rule = new Map(RULES.map((r) => [r.code, r]));
      for (const [code, raw, text] of V.lightValueText) {
        c.same(`${code} ${raw}`, ruleValueText(rule.get(code)!, raw), text);
      }
      for (const [points, accounts, wentOverdrawn, rateText, line] of V.lightTiers) {
        const t = { points, accounts, wentOverdrawn };
        c.same(`${wentOverdrawn}/${accounts} rateText`, tierRateText(t), rateText);
        c.same(`${points}: ${wentOverdrawn}/${accounts} line`, tierLine(t), line);
      }
      c.done();
    });

    it('rules fire strictly past the cut: the cut and one double either side', () => {
      const c = new Checker('light cuts');
      const rule = new Map(RULES.map((r) => [r.code, r]));
      c.same('4 rules x 3 values', V.lightCuts.length, 12);
      c.same('only the value past each cut fires', V.lightCuts.filter(([, , fired]) => fired).length, 4);
      const neutral = { min_bal_over_S: 2.5, cash_share: 0.5, inc_cv: 0, bal_trend: 0 }; // no rule fires
      for (const [code, x, fired] of V.lightCuts) {
        c.same(`${code} ruleFires(${x})`, ruleFires(rule.get(code)!, x), fired);
        // the same value through the card's path: raw -> clip/fill -> rule -> points
        const inp = { rowsUsed: 6, daysBelowZero: 0, recentSpending: 1, lastMonth: bt.today, raw: { ...neutral, [code]: x } };
        const l = computeLight(1, inp, bt);
        const r = l.rules.find((q) => q.rule.code === code)!;
        c.same(`${code} ${x} value`, r.value, x);
        c.same(`${code} ${x} fired`, r.fired, fired);
        c.same(`${code} ${x} points`, l.points, fired ? 1 : 0);
      }
      c.done();
    });
  });
});
