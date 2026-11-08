/**
 * Parity harness: the TypeScript engine must reproduce the Python engine's outputs.
 *
 *     ../.venv/bin/python ../scripts/export_web_data.py   # regenerate the vectors from Python
 *     npm test
 *
 * Exact equality for runway months, flags, verdicts, steps and every string; money values
 * within 1e-6 (the summary also counts how many are bit-for-bit identical).
 */
import { readFileSync } from 'node:fs';
import { isDeepStrictEqual } from 'node:util';
import { afterAll, describe, expect, it } from 'vitest';
import {
  BASELINE,
  DOUBLE_WHAMMY,
  EI_2026_MAX_MONTHLY,
  EI_2026_MAX_WEEKLY,
  FURNACE,
  LAID_OFF_EI,
  LAID_OFF_EI_CAPPED,
  NO_SHORTFALL_LABEL,
  PRESETS,
  RUNWAY_CAP_MONTHS,
  WEEKS_PER_MONTH,
  accountFlags,
  applyShock,
  backupLadder,
  backupPlan,
  balancePath,
  calendarPath,
  creditAdvice,
  decodeAccounts,
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
  templateStory,
  withShock,
} from '../src/engine';
import type { Account, AccountsFile, PortfolioFile, RunwayResult, Shock } from '../src/engine';

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
  constants: Record<string, number | string>;
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
}

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
});
