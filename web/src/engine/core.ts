/**
 * Deterministic resilience engine, a line-by-line port of resilience/core.py.
 *
 * Runway (months), the judges' published formula:
 *     buffer_left = B - one_off_costs
 *     gap         = spending_after_shock - income_after_shock
 *     buffer_left <= 0 -> 0
 *     gap <= 0         -> "no shortfall (120+)"
 *     else             -> min(buffer_left / gap, 120), rounded to 1 decimal (numpy rounding)
 *
 * Reality checks (EI cap, waiting week, pension-aware, S6, January path, bills fallback) are
 * labelled extras shown next to the judges' number, never instead of it.
 * web/test/parity.test.ts checks every function here against the Python engine's outputs.
 */
import { npRound, pyFixed, pyG, pyMax, pyMin, pyMoney0, pyPercent0, pyRound } from './pyformat';
import type {
  Account,
  BackupPlan,
  Flag,
  GoalKind,
  GoalPlan,
  Ladder,
  Rung,
  RunwayResult,
  Shock,
  ShockTerms,
} from './types';

export const RUNWAY_CAP_MONTHS = 120;
export const NO_SHORTFALL_LABEL = 'no shortfall (120+)';
export const DEFAULTED_LOAN_STATUSES = ['B', 'D'] as const;
export const DATA_END_MONTH = '2025-12';

// Canadian reality check (opt-in; the judges' formula has no cap): EI pays at most $729/week in 2026.
// Source: https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit/benefit-amount.html
export const EI_2026_MAX_WEEKLY = 729;
export const EI_2026_MAX_MONTHLY = (EI_2026_MAX_WEEKLY * 52) / 12; // 3,159.00
export const WEEKS_PER_MONTH = 52 / 12;

// The one-week EI waiting period is the normal rule, but it is waived for all new claims that start between
// March 30, 2025 and October 9, 2027, so the waiting-week check is a post-waiver scenario, off by default.
// Source: https://www.canada.ca/en/services/benefits/ei/temporary-measures-for-major-economic-conditions.html
export const EI_WAITING_WEEK_WAIVED_UNTIL = '2027-10-09';
export const WAITING_WEEK_LABEL =
  'EI waiting week: normal rule, once the waiver ends (waived until Oct 9, 2027, canada.ca)';

// ---------------------------------------------------------------- shocks

const DEFAULT_SHOCK: Shock = {
  incomeMultiplier: 1,
  incomeCapMonthly: null,
  billsIncreasePct: 0,
  extraMonthlyCost: 0,
  oneOffCost: 0,
  oneOffMultipleOfS: 0,
  flexibleCutPct: 0,
  waitingWeek: false,
  pensionAware: false,
  spendingBasis: 'S',
  billsFallback: false,
  jobLoss: false,
  name: 'custom',
};

/** A Shock with Python's defaults for every field not given (undefined counts as not given). */
export function makeShock(partial: Partial<Shock> = {}): Shock {
  const out: Shock = { ...DEFAULT_SHOCK };
  for (const [k, v] of Object.entries(partial) as [keyof Shock, Shock[keyof Shock] | undefined][]) {
    if (v !== undefined) (out as unknown as Record<string, unknown>)[k] = v;
  }
  return out;
}

/** Python Shock.with_(**changes). */
export function withShock(shock: Shock, changes: Partial<Shock>): Shock {
  return makeShock({ ...shock, ...changes });
}

/** A job loss on EI: the income drop is a layoff, not a pay cut. */
export function isJobLoss(shock: Shock): boolean {
  return shock.jobLoss && shock.incomeMultiplier < 1;
}

export const BASELINE = makeShock({ name: 'Baseline (no shock)' });
export const LAID_OFF_EI = makeShock({
  incomeMultiplier: 0.55,
  jobLoss: true,
  name: 'Laid off: EI at 55% of usual income',
});
export const LAID_OFF_EI_CAPPED = makeShock({
  incomeMultiplier: 0.55,
  incomeCapMonthly: EI_2026_MAX_MONTHLY,
  jobLoss: true,
  name: 'Laid off: EI at 55%, capped at the 2026 maximum ($729/week)',
});
export const FURNACE = makeShock({
  oneOffMultipleOfS: 1,
  name: 'Furnace dies: repair = 1 month of typical spending',
});
export const DOUBLE_WHAMMY = makeShock({
  incomeMultiplier: 0.55,
  billsIncreasePct: 0.15,
  jobLoss: true,
  name: 'Job loss (EI 55%) + household bills +15%',
});
export const README_TWISTS = [LAID_OFF_EI, FURNACE, DOUBLE_WHAMMY] as const;

/** The three track twists as the levers apply them, named as app.py names them (shock_parser.describe_shock). */
export const PRESETS = {
  'Laid off: EI 55%': makeShock({ incomeMultiplier: 0.55, jobLoss: true, name: 'Laid off: EI 55%' }),
  'Furnace dies: 1× spending': makeShock({ oneOffMultipleOfS: 1, name: 'Furnace dies: 1× spending' }),
  'Job loss + bills +15%': makeShock({
    incomeMultiplier: 0.55,
    billsIncreasePct: 0.15,
    jobLoss: true,
    name: 'Job loss + bills +15%',
  }),
  // Custom starts from no shock at all: only the levers the user sets change anything
  Custom: makeShock({ name: 'Custom: no shock' }),
} as const satisfies Record<string, Shock>;
export type PresetName = keyof typeof PRESETS;

// ---------------------------------------------------------------- runway

function makeResult(
  months: number | null,
  noShortfall: boolean,
  bufferLeft: number,
  gap: number,
  incomeAfter: number,
  spendingAfter: number,
  oneOff: number,
): RunwayResult {
  return {
    months,
    noShortfall,
    bufferLeft,
    gap,
    incomeAfter,
    spendingAfter,
    oneOff,
    capped: !noShortfall && months !== null && months >= RUNWAY_CAP_MONTHS,
  };
}

/** The judges' runway formula, exactly as published. */
export function runway(buffer: number, oneOff: number, spendingAfter: number, incomeAfter: number): RunwayResult {
  const bufferLeft = buffer - oneOff;
  const gap = spendingAfter - incomeAfter;
  if (bufferLeft <= 0) return makeResult(0, false, bufferLeft, gap, incomeAfter, spendingAfter, oneOff);
  if (gap <= 0) return makeResult(null, true, bufferLeft, gap, incomeAfter, spendingAfter, oneOff);
  const months = npRound(pyMin(bufferLeft / gap, RUNWAY_CAP_MONTHS), 1); // same rounding as portfolio_runway
  return makeResult(months, false, bufferLeft, gap, incomeAfter, spendingAfter, oneOff);
}

/** Python RunwayResult.survives(months). */
export function survives(res: RunwayResult, months: number): boolean {
  return res.noShortfall || (res.months !== null && res.months >= months);
}

/** Python RunwayResult.label. */
export function runwayLabel(res: RunwayResult): string {
  if (res.noShortfall) return NO_SHORTFALL_LABEL;
  const m = pyFixed(res.months ?? 0, 1);
  return res.capped ? `${m} (cap)` : m;
}

/** Python _get on a row: missing / null / NaN -> default. */
function num(v: number | null | undefined, d = 0): number {
  return v === null || v === undefined || Number.isNaN(v) ? d : v;
}

/** (income_after, monthly spending add-ons, one_off, base spending) for one account. */
export function shockTerms(acct: Account, shock: Shock): ShockTerms {
  const I = num(acct.I);
  const S = num(acct.S);
  const H = num(acct.H);
  let pension: number;
  let earned: number;
  if (shock.pensionAware) {
    const Pn = num(acct.Pn);
    pension = Math.min(Pn, I);
    earned = I - pension;
  } else {
    pension = 0;
    earned = I;
  }
  let ei = shock.incomeMultiplier * earned;
  if (shock.incomeCapMonthly !== null && shock.incomeCapMonthly !== undefined) {
    ei = Math.min(ei, shock.incomeCapMonthly);
  }
  const income = ei + pension;

  const Heff = shock.billsFallback ? Math.max(H, num(acct.H_SO)) : H;
  const addons = shock.billsIncreasePct * Heff + shock.extraMonthlyCost - shock.flexibleCutPct * num(acct.flexible_median);

  let base: number;
  if (shock.spendingBasis === 'S6') {
    const s6 = acct.S6;
    base = s6 === null || s6 === undefined || Number.isNaN(s6) ? S : s6;
  } else if (shock.spendingBasis === 'S') {
    base = S;
  } else {
    throw new Error(`unknown spendingBasis ${JSON.stringify(shock.spendingBasis)}`);
  }

  let oneOff = shock.oneOffCost + shock.oneOffMultipleOfS * S;
  if (shock.waitingWeek && isJobLoss(shock)) {
    oneOff = oneOff + ei / WEEKS_PER_MONTH; // one week of EI not paid
  }
  return { income, addons, oneOff, base };
}

/** Runway for one account under a shock. */
export function applyShock(acct: Account, shock: Shock): RunwayResult {
  const t = shockTerms(acct, shock);
  return runway(acct.B, t.oneOff, t.base + t.addons, t.income);
}

// ------------------------------------------------- month-by-month reality path

/**
 * Runway when each month costs the account's median spending for that calendar month.
 * The shock hits at the start of `startMonth` (1 = January). Income is the post-shock income
 * every month; one-offs come off the buffer first. Months until the balance goes negative
 * (1 decimal), 0 if the buffer is already gone, Infinity if it never runs out within `horizon`.
 */
export function calendarPath(acct: Account, shock: Shock, startMonth = 1, horizon = 120): number {
  const { income: inc, addons: add, oneOff } = shockTerms(acct, shock);
  let bal = acct.B - oneOff;
  if (bal <= 0) return 0;
  if (!(bal > 0)) return Infinity; // NaN buffer: numpy marks it neither dead nor alive
  for (let k = 0; k < horizon; k++) {
    const idx = (((startMonth - 1 + k) % 12) + 12) % 12;
    const c = acct.cal[idx];
    const spend = (c === null || c === undefined || Number.isNaN(c) ? acct.S : c) + add;
    const net = inc - spend;
    if (bal + net < 0) return npRound(k + bal / (spend - inc), 1);
    bal = bal + net;
  }
  return Infinity;
}

// ------------------------------------------------------------------ plans

/**
 * The shock a job-loss-proof fund is sized on: the twist itself if it is a job loss, otherwise a job
 * loss on EI 55% (or the twist's deeper income cut, so a 30% pay cut is covered too).
 */
export function goalShockFor(shock: Shock): Shock {
  if (isJobLoss(shock)) return shock;
  return withShock(shock, {
    incomeMultiplier: pyMin(shock.incomeMultiplier, 0.55),
    oneOffCost: 0,
    oneOffMultipleOfS: 0,
    jobLoss: true,
    name: 'Laid off: EI 55%',
  });
}

/**
 * Emergency-fund goal from the customer's own numbers.
 *   months_of_S  target = targetMonths x S (the conventional benchmark)
 *   ei_proof     target = one-off + targetMonths x max(spending - income, 0) under `shock`;
 *                "already there" means the judges' rounded runway under `shock` reaches targetMonths.
 */
export function goalPlan(
  acct: Account,
  targetMonths = 6,
  kind: GoalKind = 'months_of_S',
  shock: Shock = LAID_OFF_EI,
  saveShare = 1,
): GoalPlan {
  let target: number;
  let shortfall: number;
  if (kind === 'months_of_S') {
    target = targetMonths * acct.S;
    shortfall = pyMax(target - acct.B, 0);
  } else if (kind === 'ei_proof') {
    const t = shockTerms(acct, shock);
    target = t.oneOff + targetMonths * pyMax(t.base + t.addons - t.income, 0);
    if (survives(applyShock(acct, shock), targetMonths)) {
      shortfall = 0;
    } else {
      // rounding can pass a buffer a hair under target; failing means something is missing
      shortfall = pyMax(target - acct.B, 0.01);
    }
  } else {
    throw new Error(`unknown target kind ${JSON.stringify(kind)}`);
  }
  const surplus = acct.I - acct.S;
  const saving = saveShare * surplus;
  let months: number | null;
  if (shortfall === 0) months = 0;
  else if (saving > 0) months = Math.ceil((shortfall / saving) * 10) / 10; // round up: 0 only when already there
  else months = null;
  return {
    targetBuffer: target,
    currentBuffer: acct.B,
    shortfall,
    monthlySurplus: surplus,
    monthsToTarget: months,
    targetKind: kind,
  };
}

/**
 * Monthly spending cut that brings runway back to >= target under the shock. If a one-off wipes
 * the buffer, the published formula gives 0 months whatever the spending, so the plan reports the
 * cash needed instead.
 */
export function backupPlan(acct: Account, shock: Shock, targetMonths = 6): BackupPlan {
  const shocked = applyShock(acct, shock);
  const pool = (1 - shock.flexibleCutPct) * acct.flexible_median;
  const surplus = acct.I - acct.S;
  const wiped = shocked.bufferLeft <= 0;
  let cut = 0;
  let cash = 0;
  if (wiped) {
    cut = pyMin(pyMax(shocked.gap, 0), pool); // cut what the pool allows, then
    cash = -shocked.bufferLeft + targetMonths * pyMax(shocked.gap - cut, 0) + 0.01;
    cash = Math.ceil(cash * 100) / 100; // the rest has to come from cash or credit
  } else if (!survives(shocked, targetMonths)) {
    const allowedGap = shocked.bufferLeft / targetMonths;
    cut = Math.ceil((shocked.gap - allowedGap) * 100) / 100; // round up to the cent
  }
  const cutShare = pool > 0 ? cut / pool : null;
  const feasible = !wiped && cut <= pool;
  const after = runway(
    shocked.bufferLeft + shocked.oneOff + cash,
    shocked.oneOff,
    shocked.spendingAfter - cut,
    shocked.incomeAfter,
  );
  return {
    targetMonths,
    shocked,
    monthlyCutNeeded: cut,
    flexiblePool: pool,
    cutShareOfFlexible: cutShare,
    feasible,
    afterCut: after,
    bufferWiped: wiped,
    cashNeeded: cash,
    normalSurplus: surplus,
  };
}

function ladderVerdict(
  targetMonths: number,
  alreadySafe: boolean,
  overdrawn: boolean,
  bufferWiped: boolean,
  rungs: Rung[],
  firstSufficient: number | null,
): string {
  if (alreadySafe) return 'Survives without changes';
  if (overdrawn) return 'Already overdrawn: clear the debt with cash or credit first';
  if (bufferWiped) return 'Buffer wiped by the one-off: needs cash or credit first';
  if (firstSufficient !== null) return `Reaches ${pyG(targetMonths)} months at: ${rungs[firstSufficient].step}`;
  return "Needs income or credit: spending cuts alone don't reach the target";
}

function makeLadder(
  targetMonths: number,
  shocked: RunwayResult,
  alreadySafe: boolean,
  bufferWiped: boolean,
  rungs: Rung[] = [],
  firstSufficient: number | null = null,
  cashOrCreditNeeded = 0,
  overdrawn = false,
): Ladder {
  return {
    targetMonths,
    shocked,
    alreadySafe,
    bufferWiped,
    overdrawn,
    rungs,
    firstSufficient,
    cashOrCreditNeeded,
    verdict: ladderVerdict(targetMonths, alreadySafe, overdrawn, bufferWiped, rungs, firstSufficient),
  };
}

/**
 * Minimum-pain ladder: stop at the first (cumulative) step that reaches the target.
 *   1 drop bank fees   2 non-fixed spending -10%   3 non-fixed -25%
 *   4 pause other (blank-purpose) standing orders, capped at the transfers seen in a typical month
 *   5 defer the running loan payment, capped at the loan payment seen in a typical month
 *   6 non-fixed -50%
 * If none reaches it: income or credit needed.
 */
export function backupLadder(acct: Account, shock: Shock, targetMonths = 6): Ladder {
  const shocked = applyShock(acct, shock);
  if (survives(shocked, targetMonths)) return makeLadder(targetMonths, shocked, true, false);
  if (shocked.bufferLeft <= 0) {
    const cash = -shocked.bufferLeft + targetMonths * pyMax(shocked.gap, 0) + 0.01;
    return makeLadder(targetMonths, shocked, false, true, [], null, Math.ceil(cash * 100) / 100, acct.B <= 0);
  }

  const fees = num(acct.bank_fees_median);
  const nf = (1 - shock.flexibleCutPct) * num(acct.flexible_median);
  const so = pyMin(num(acct.so_other), num(acct.transfers_out_other_median));
  const loan = pyMin(num(acct.P), num(acct.loan_payments_median));
  const steps: [string, number][] = [
    ['Drop bank fees', fees],
    ['+ cut non-fixed spending 10%', fees + 0.1 * nf],
    ['+ cut non-fixed spending 25%', fees + 0.25 * nf],
    ['+ pause other standing orders', fees + 0.25 * nf + so],
    ['+ defer the running loan payment', fees + 0.25 * nf + so + loan],
    ['+ cut non-fixed spending 50%', fees + 0.5 * nf + so + loan],
  ];
  const rungs: Rung[] = [];
  let first: number | null = null;
  let prev = 0;
  for (const [name, saving] of steps) {
    if (saving <= prev) continue; // this account has nothing (more) to cut at this step
    prev = saving;
    const res = runway(
      shocked.bufferLeft + shocked.oneOff,
      shocked.oneOff,
      shocked.spendingAfter - saving,
      shocked.incomeAfter,
    );
    const ok = survives(res, targetMonths);
    rungs.push({ step: name, monthlySaving: pyRound(saving, 2), result: res, reachesTarget: ok });
    if (ok && first === null) first = rungs.length - 1;
  }
  let cash = 0;
  if (first === null) {
    const lastGap = shocked.gap - steps[steps.length - 1][1];
    cash = pyMax(targetMonths * pyMax(lastGap, 0) - shocked.bufferLeft, 0);
    cash = Math.ceil(cash * 100) / 100;
  }
  return makeLadder(targetMonths, shocked, false, false, rungs, first, cash);
}

// ------------------------------------------------------------------ chart paths

/**
 * Balance month by month under the judges' constant-gap model: B - oneOff - gap * t for
 * t = 0..months (months + 1 points). Not clipped at 0, so the chart shows where it crosses.
 */
export function balancePath(acct: Account, shock: Shock, months: number): number[] {
  const r = applyShock(acct, shock);
  return Array.from({ length: months + 1 }, (_, t) => r.bufferLeft - r.gap * t);
}

/**
 * Balance month by month once the backup plan is in place (`ladder` from backupLadder for the
 * same account and shock): already safe -> the shocked path; buffer wiped (or nothing to cut) ->
 * the cash or credit is added at month 0; otherwise the first rung that reaches the target, or
 * the last rung plus the cash or credit still needed.
 */
export function planPath(acct: Account, shock: Shock, ladder: Ladder, months: number): number[] {
  if (ladder.alreadySafe) return balancePath(acct, shock, months);
  const s = ladder.shocked;
  let start: number;
  let gap: number;
  if (ladder.bufferWiped || ladder.rungs.length === 0) {
    start = s.bufferLeft + ladder.cashOrCreditNeeded;
    gap = s.gap;
  } else {
    const i = ladder.firstSufficient ?? ladder.rungs.length - 1;
    const res = ladder.rungs[i].result;
    const extra = ladder.firstSufficient !== null ? 0 : ladder.cashOrCreditNeeded;
    start = res.bufferLeft + extra;
    gap = res.gap;
  }
  return Array.from({ length: months + 1 }, (_, t) => start - gap * t);
}

// ------------------------------------------------------------------ flags

/**
 * Calibration of the judges' 6-month EI test against typical half-year spending (S6): share of
 * accounts in each judge-runway band that fail 6 months on S6.
 */
export const GREY_ZONE: readonly (readonly [number, number, number])[] = [
  [6.0, 8.0, 0.819],
  [8.0, 10.0, 0.423],
  [10.0, 12.0, 0.231],
];

const SHOCK_KEYS: readonly (keyof Shock)[] = [
  'incomeMultiplier',
  'incomeCapMonthly',
  'billsIncreasePct',
  'extraMonthlyCost',
  'oneOffCost',
  'oneOffMultipleOfS',
  'flexibleCutPct',
  'waitingWeek',
  'pensionAware',
  'spendingBasis',
  'billsFallback',
  'jobLoss',
];

/** Only for the judges' plain EI 55% job loss, the twist the calibration was measured on. */
export function greyZoneNote(result: RunwayResult, shock?: Shock | null): string | null {
  if (shock !== undefined && shock !== null && SHOCK_KEYS.some((k) => shock[k] !== LAID_OFF_EI[k])) return null;
  if (result.noShortfall || result.months === null) return null;
  for (const [lo, hi, share] of GREY_ZONE) {
    if (lo <= result.months && result.months < hi) {
      return (
        `Grey zone: ${pyPercent0(share)} of customers the formula puts at ${pyG(lo)}-${pyG(hi)} months ` +
        'run out within 6 months on their own half-year spending.'
      );
    }
  }
  return null;
}

/** Loan status B (defaulted) or D (running, client in debt). */
export function loanInTrouble(acct: Account): boolean {
  return (DEFAULTED_LOAN_STATUSES as readonly string[]).includes(acct.loan_status ?? '');
}

/** What to say about a cash/credit hole, without pushing credit on a borrower in trouble. */
export function creditAdvice(acct: Account, amount: number, jobLoss = true): string {
  const amt = `$${pyMoney0(amount)}`;
  if (loanInTrouble(acct)) {
    const first = jobLoss ? 'start the EI claim on day one, ' : '';
    return (
      `The remaining hole is ${amt}. With a loan already in arrears or default, no new credit: ` +
      `${first}ask for a hardship deferral on the loan, and run the spending steps.`
    );
  }
  return (
    `Line up ${amt} of credit before the shock: a Tangerine Line of Credit is easiest to arrange ` +
    'while still employed, subject to approval.'
  );
}

/** (code, plain-English note) for anything a judge or customer should know first. */
export function accountFlags(acct: Account): Flag[] {
  const f: Flag[] = [];
  if (acct.B <= 0) f.push(['overdrawn', 'Already overdrawn: the buffer is negative, so every runway is 0.']);
  if (acct.I === 0) {
    f.push(['no_income', 'No typical income (median money in is $0): a job-loss shock changes nothing.']);
  }
  if (acct.S === 0) f.push(['no_spending', "No typical spending: shocks sized as 'months of spending' are $0."]);
  if (acct.H === 0) {
    if (num(acct.H_SO) > 0) {
      f.push([
        'bills_by_standing_order',
        `Household bills paid by standing order ($${pyMoney0(num(acct.H_SO))}/mo) are not in H, ` +
          'so a bills shock adds $0 unless the bills fallback is on.',
      ]);
    } else {
      f.push(['no_bills', 'No household bills recorded (H = 0): a bills shock adds $0.']);
    }
  }
  const last = acct.last_month ?? DATA_END_MONTH;
  if (typeof last === 'string' && last < DATA_END_MONTH) {
    f.push(['stale', `Account activity stops in ${last}: the buffer may be out of date.`]);
  }
  if ((acct.months_of_data ?? 99) <= 13) {
    f.push(['short_history', `Only ${Math.trunc(num(acct.months_of_data))} months of history.`]);
  }
  const age = acct.owner_age;
  if (typeof age === 'number' && !Number.isNaN(age) && age < 18) {
    f.push(['minor_owner', `Owner is ${pyFixed(age, 0)}: under 18.`]);
  }
  if (num(acct.Pn) > 0) {
    f.push(['pension', 'Receives a pension: a job loss should not cut it (try the pension-aware view).']);
  }
  if (loanInTrouble(acct)) {
    f.push([
      'loan_trouble',
      `Loan status ${acct.loan_status ?? ''} (in arrears or defaulted): don't add new ` +
        'credit; lead with an EI claim, a hardship deferral on the loan, and the spending steps.',
    ]);
  }
  if (acct.pre_loan_negative) {
    f.push([
      'pre_loan_overdraft',
      'Overdrawn before taking the loan: a red flag, not evidence. Every such borrower here (27 of 27) is ' +
        'labelled defaulted, but that is built into how this dataset labels loans (good only if the balance ' +
        'never went below zero).',
    ]);
  } else if (acct.ever_negative) {
    f.push(['been_negative', 'Has gone below zero before.']);
  }
  return f;
}
