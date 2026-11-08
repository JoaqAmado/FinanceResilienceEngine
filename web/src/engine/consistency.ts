/**
 * Every number on the Live twist screen agrees with every other number: port of resilience/consistency.py's
 * check_view for the browser. The raw-CSV recomputation of the customer card (invariant 2) runs in Python only
 * (tests/test_consistency.py); here the card is checked against the exported account record.
 *
 * 1 input -> shock   3 runway -> formula   4 runway -> chart   5 plan -> runway   6 reality checks
 * 7 narrative -> numbers   9 flags -> data
 */
import { DATA_END_MONTH, DEFAULTED_LOAN_STATUSES, EI_2026_MAX_MONTHLY, applyShock, survives, withShock } from './core';
import type { Facts, Story } from './narrative';
import { pyFixed, pyMax, rint } from './pyformat';
import { canBillsFallback, checksFree, describeShock, sameShock, shockFromState } from './shock_parser';
import type { CheckToggles, LeverState } from './shock_parser';
import type { Account, GoalPlan, Ladder, RunwayResult, Shock } from './types';

export interface Issue {
  check: string;
  detail: string;
}

export type VerdictKind = 'survives' | 'overdrawn' | 'buffer_gone' | 'runs_out';

/** Which verdict badge the judges' panel shows (app.py's order). */
export function verdictKind(acct: Account, judge: RunwayResult, target: number): VerdictKind {
  if (survives(judge, target)) return 'survives';
  if (acct.B <= 0) return 'overdrawn';
  if (judge.bufferLeft <= 0) return 'buffer_gone';
  return 'runs_out';
}

export interface ChatLast {
  shock: Shock;
  levers: LeverState;
  toggles: CheckToggles;
  target: number;
  accountId: number;
  understoodAs: string;
}

export interface CheckShown {
  key: keyof CheckToggles;
  enabled: boolean;
  on: boolean;
  result: RunwayResult;
}

/** What the view displayed. A missing key skips the checks that need it. */
export interface ViewNumbers {
  accountId: number;
  levers?: LeverState;
  toggles?: CheckToggles;
  chat?: ChatLast | null;
  understoodAs?: string;
  twistLabel?: string;
  card?: Partial<Record<'I' | 'F' | 'S' | 'B' | 'H' | 'P' | 'Pn', number>>;
  judgeShock?: Shock;
  judge?: RunwayResult;
  judgeText?: string;
  verdict?: VerdictKind;
  /** the judges' balance path the burn-down chart draws, month 0 first */
  judgePath?: number[];
  jan?: number;
  real?: RunwayResult;
  checks?: CheckShown[];
  ladder?: Ladder;
  goal?: GoalPlan;
  goalShock?: Shock;
  story?: Story;
  facts?: Facts;
  flags?: string[];
}

const TOL = 0.01;
const close = (a: number, b: number, tol = TOL) => Math.abs(a - b) <= tol + 1e-9;

function rw(res: RunwayResult): string {
  if (res.noShortfall) return 'No shortfall (120+)';
  const m = res.months ?? 0;
  return m >= 120 ? '120.0 mo (cap)' : `${pyFixed(m, 1)} mo`;
}

/** The published runway, written out again with no engine code (judges' levers only). */
export function judgesFormula(acct: Account, shock: Shock): RunwayResult {
  const incomeAfter = shock.incomeMultiplier * acct.I;
  const spendingAfter = acct.S + shock.billsIncreasePct * acct.H + shock.extraMonthlyCost -
    shock.flexibleCutPct * acct.flexible_median;
  const oneOff = shock.oneOffCost + shock.oneOffMultipleOfS * acct.S;
  const bufferLeft = acct.B - oneOff;
  const gap = spendingAfter - incomeAfter;
  const base = { bufferLeft, gap, incomeAfter, spendingAfter, oneOff };
  if (bufferLeft <= 0) return { months: 0, noShortfall: false, capped: false, ...base };
  if (gap <= 0) return { months: null, noShortfall: true, capped: false, ...base };
  const months = rint(Math.min(bufferLeft / gap, 120) * 10) / 10;
  return { months, noShortfall: false, capped: months >= 120, ...base };
}

/** Month by month from January, each month costing that account's median spending for its calendar month. */
export function januaryPath(acct: Account, shock: Shock, horizon = 120): number {
  const income = shock.incomeMultiplier * acct.I;
  const addons = shock.billsIncreasePct * acct.H + shock.extraMonthlyCost - shock.flexibleCutPct * acct.flexible_median;
  let bal = acct.B - (shock.oneOffCost + shock.oneOffMultipleOfS * acct.S);
  if (bal <= 0) return 0;
  for (let k = 0; k < horizon; k++) {
    const c = acct.cal[k % 12];
    const spend = (c === null || c === undefined || Number.isNaN(c) ? acct.S : c) + addons;
    if (bal + income - spend < 0) return rint((k + bal / (spend - income)) * 10) / 10;
    bal += income - spend;
  }
  return Infinity;
}

const NUMBER = /\d+(?:,\d{3})*(?:\.\d+)?/g;

/** narrative.numbers_ok: every number in the story already appears in the facts. */
export function numbersOk(story: Story, f: Facts): boolean {
  const allowed = new Set(JSON.stringify(f).match(NUMBER) ?? []);
  for (const a of [...allowed]) allowed.add(a.replaceAll(',', ''));
  const text = Object.values(story).map((v) => (Array.isArray(v) ? v.join(' ') : String(v))).join(' ');
  return (text.match(NUMBER) ?? []).every((n) => allowed.has(n) || allowed.has(n.replaceAll(',', '')));
}

export function checkView(acct: Account, shock: Shock, target: number, v: ViewNumbers): Issue[] {
  const out: Issue[] = [];
  const bad = (check: string, detail: string) => out.push({ check, detail });
  const judgeShock = checksFree(shock);

  // 1 input -> shock
  const c1 = '1 input -> shock';
  if (v.levers && v.toggles) {
    const built = shockFromState(v.levers, v.toggles, acct);
    if (!sameShock(built, shock)) {
      bad(c1, `the engine ran "${describeShock(shock)}" but the levers say "${describeShock(built)}"`);
    }
    const chat = v.chat;
    if (chat && chat.accountId === v.accountId && chat.target === target &&
        JSON.stringify(chat.levers) === JSON.stringify(v.levers) &&
        JSON.stringify(chat.toggles) === JSON.stringify(v.toggles)) {
      if (!sameShock(chat.shock, shock)) bad(c1, 'the chat produced a different shock than the engine ran');
      if (chat.understoodAs !== describeShock(shock, acct, target)) {
        bad(c1, "the chat's 'understood as' line describes a different shock");
      }
    }
  }
  if (v.judgeShock && !sameShock(v.judgeShock, judgeShock)) {
    bad(c1, "the judges' runway was computed on a different twist than the levers");
  }
  if (v.understoodAs !== undefined && v.understoodAs !== describeShock(shock, acct, target)) {
    bad(c1, `the current-shock line "${v.understoodAs}" doesn't describe the engine's shock`);
  }
  if (v.twistLabel !== undefined && v.twistLabel !== describeShock(judgeShock)) {
    bad(c1, `the twist label "${v.twistLabel}" doesn't describe the engine's shock`);
  }

  // 2 customer card -> data (the exported record; Python checks it against data/raw/)
  if (v.card) {
    for (const [f, shown] of Object.entries(v.card)) {
      const want = acct[f as keyof Account] as number;
      if (shown !== undefined && !close(shown, want)) bad('2 customer card -> data', `${f} shown ${shown} but the data has ${want}`);
    }
  }

  // 3 runway -> formula
  const c3 = '3 runway -> formula';
  const want = judgesFormula(acct, judgeShock);
  if (v.judge) {
    if (v.judge.noShortfall !== want.noShortfall || v.judge.months !== want.months) {
      bad(c3, `judges' runway ${rw(v.judge)} but the formula gives ${rw(want)}`);
    }
    for (const f of ['bufferLeft', 'gap', 'incomeAfter', 'spendingAfter', 'oneOff'] as const) {
      if (!close(v.judge[f], want[f])) bad(c3, `${f} ${v.judge[f]} but the formula gives ${want[f]}`);
    }
  }
  if (v.judgeText !== undefined && v.judgeText !== rw(want)) {
    bad(c3, `the runway reads "${v.judgeText}" but the formula gives "${rw(want)}"`);
  }
  if (v.verdict !== undefined && v.verdict !== verdictKind(acct, want, target)) {
    bad(c3, `the verdict says ${v.verdict} but the numbers say ${verdictKind(acct, want, target)}`);
  }

  // 4 runway -> chart
  const c4 = '4 runway -> chart';
  if (!want.noShortfall && want.months && want.months > 0 && want.months < 120) {
    const crossing = want.bufferLeft - want.months * want.gap;
    if (Math.abs(crossing) > 0.05 * want.gap + TOL) bad(c4, `the buffer is ${crossing} at month ${want.months}, not $0`);
  }
  if (v.judgePath && !want.capped) {   // a capped runway (120, the formula's cap) crosses $0 later, by design
    const cross = v.judgePath.findIndex((x) => x < 0);
    if (want.noShortfall || want.months === null) {
      if (cross >= 0) bad(c4, 'the burn-down goes below $0 but the runway says no shortfall');
    } else if (cross >= 0 && !(want.months - 1 <= cross && cross <= Math.ceil(want.months) + 1)) {
      bad(c4, `the burn-down crosses $0 in month ${cross} but the runway is ${want.months}`);
    } else if (cross < 0 && want.months < v.judgePath.length - 2) {
      bad(c4, `the burn-down never crosses $0 but the runway is ${want.months}`);
    }
  }
  if (v.jan !== undefined) {
    const ind = januaryPath(acct, judgeShock);
    const ok = ind === Infinity ? v.jan === Infinity : v.jan !== Infinity && Math.abs(ind - v.jan) <= 0.1 + 1e-9;
    if (!ok) bad(c4, `January path ${v.jan} but a month-by-month rerun gives ${ind}`);
  }

  // 5 plan -> runway
  const c5 = '5 plan -> runway';
  if (v.ladder) {
    const lad = v.ladder;
    if (lad.alreadySafe !== survives(applyShock(acct, shock), target)) {
      bad(c5, "the backup plan's 'survives without changes' disagrees with the runway");
    }
    let prevOk = false;
    lad.rungs.forEach((rung, i) => {
      const again = applyShock(acct, withShock(shock, { extraMonthlyCost: shock.extraMonthlyCost - rung.monthlySaving }));
      const ok = survives(again, target);
      if (ok !== rung.reachesTarget) bad(c5, `rung "${rung.step}" is marked wrong: re-applied it gives ${rw(again)}`);
      if (lad.firstSufficient === i && prevOk) bad(c5, `rung "${rung.step}" is marked first but an earlier one reaches`);
      prevOk = prevOk || ok;
    });
    if (lad.firstSufficient !== null && !lad.rungs[lad.firstSufficient]?.reachesTarget) {
      bad(c5, "the rung marked as reaching the target doesn't");
    }
    if (lad.firstSufficient === null && lad.rungs.some((x) => x.reachesTarget)) {
      bad(c5, 'a rung reaches the target but none is marked');
    }
  }
  if (v.goal && v.goalShock) {
    const g = v.goal;
    const passesNow = survives(applyShock(acct, v.goalShock), target);
    const wantShort = passesNow ? 0 : pyMax(g.targetBuffer - acct.B, 0.01);
    if (!close(g.shortfall, wantShort)) bad(c5, `goal shortfall ${g.shortfall} but target buffer - B gives ${wantShort}`);
    let funded = applyShock({ ...acct, B: g.targetBuffer }, v.goalShock);
    // known boundary (see resilience/consistency.py): with no monthly gap the target is exactly the one-off
    if (funded.gap <= 0) funded = applyShock({ ...acct, B: g.targetBuffer + 0.01 }, v.goalShock);
    if (!survives(funded, target)) bad(c5, `a buffer of ${g.targetBuffer} gives ${rw(funded)} under the goal's shock`);
  }

  // 6 reality checks -> toggles
  const c6 = '6 reality checks -> toggles';
  const jl = shock.jobLoss && shock.incomeMultiplier < 1;
  if (!jl && (shock.incomeCapMonthly !== null || shock.waitingWeek || shock.pensionAware)) {
    bad(c6, 'an EI check is on without a job loss');
  }
  if (shock.pensionAware && !(acct.Pn > 0)) bad(c6, "'keep pension' is on for an account with no pension");
  if (shock.billsFallback && !canBillsFallback(acct)) bad(c6, "'bills by standing order' is on where it can't apply");
  if (v.checks) {
    const guard: Record<keyof CheckToggles, boolean> = { cap: jl, ww: jl, pens: jl && acct.Pn > 0, s6: true,
      bfb: canBillsFallback(acct) };
    const alone: Record<keyof CheckToggles, Partial<Shock>> = {
      cap: { incomeCapMonthly: EI_2026_MAX_MONTHLY }, ww: { waitingWeek: true }, pens: { pensionAware: true },
      s6: { spendingBasis: 'S6' }, bfb: { billsFallback: true },
    };
    for (const c of v.checks) {
      if (c.enabled !== guard[c.key]) bad(c6, `check ${c.key} is ${c.enabled ? 'enabled' : 'disabled'} where it shouldn't be`);
      if (c.on && !c.enabled) bad(c6, `check ${c.key} is applied while disabled`);
      const again = applyShock(acct, withShock(judgeShock, alone[c.key]));
      if (rw(again) !== rw(c.result)) bad(c6, `check ${c.key} alone shows ${rw(c.result)} but the engine gives ${rw(again)}`);
    }
  }
  if (v.real && rw(v.real) !== rw(applyShock(acct, shock))) {
    bad(c6, `'runway with selected checks' ${rw(v.real)} but the engine gives ${rw(applyShock(acct, shock))}`);
  }

  // 7 narrative -> numbers
  if (v.story && v.facts && !numbersOk(v.story, v.facts)) {
    bad('7 narrative -> numbers', "the summary has numbers that aren't in the computed facts");
  }

  // 9 flags -> data
  if (v.flags) {
    const shown = new Set(v.flags);
    const truth: Record<string, boolean> = {
      overdrawn: acct.B <= 0,
      no_income: acct.I === 0,
      no_bills: acct.H === 0 && !(acct.H_SO > 0),
      bills_by_standing_order: acct.H === 0 && acct.H_SO > 0,
      stale: (acct.last_month ?? DATA_END_MONTH) < DATA_END_MONTH,
      loan_trouble: (DEFAULTED_LOAN_STATUSES as readonly string[]).includes(acct.loan_status ?? ''),
      pre_loan_overdraft: Boolean(acct.pre_loan_negative),
    };
    for (const [code, t] of Object.entries(truth)) {
      if (shown.has(code) !== t) bad('9 flags -> data', `flag ${code} is ${shown.has(code) ? 'shown' : 'missing'} but the data says ${t ? 'yes' : 'no'}`);
    }
  }
  return out;
}
