/**
 * Plain-English story over numbers the engine already computed: a port of resilience/narrative.py
 * (facts + template_story). Deterministic, no key or network. Keys stay snake_case so a facts
 * object is the same dict the Python engine builds.
 */
import { isJobLoss, loanInTrouble, survives } from './core';
import { pyFixed, pyG, pyMax, pyMoney0 } from './pyformat';
import type { Account, Ladder, RunwayResult, Shock } from './types';

export interface Facts {
  account_id: number;
  shock: string;
  target_months: string;
  judge_runway: string;
  judge_verdict: 'survives' | 'runs out before';
  income_after: string;
  spending_after: string;
  monthly_gap: string;
  buffer_left: string;
  buffer_before: string;
  one_off: string | null;
  income_changed: boolean;
  already_overdrawn: boolean;
  loan_in_trouble: boolean;
  job_loss: boolean;
  goal_rounding_short: string | null;
  goal_target: string;
  goal_gap: string;
  goal_months: string | null;
  ladder_verdict: string;
  ladder_step: string | null;
  ladder_saving: string | null;
  cash_or_credit: string | null;
  reality: Record<string, string>;
  plan_basis: string;
}

export interface Story {
  headline: string;
  what_changed: string;
  reality_check: string;
  plan_steps: string[];
  caveat: string;
}

/** Money as the app prints it: whole dollars, |x| < 0.5 shown as $0. */
export function money(x: number): string {
  const v = Math.abs(x) < 0.5 ? 0 : x;
  return v < 0 ? `-$${pyMoney0(-v)}` : `$${pyMoney0(v)}`;
}

function rw(res: RunwayResult): string {
  if (res.noShortfall) return 'no shortfall (120+ months)';
  const m = pyFixed(res.months ?? 0, 1);
  return res.capped ? `${m} months (the 120-month cap)` : `${m} months`;
}

/** Everything the narrative may mention, already formatted. `reality` values: a runway or a calendar path. */
export function facts(
  accountId: number,
  acct: Account,
  shock: Shock,
  judge: RunwayResult,
  reality: Record<string, RunwayResult | number>,
  ladder: Ladder,
  goalTarget: number,
  goalGap: number,
  goalMonths: number | null,
  targetMonths: number,
  planBasis = '',
): Facts {
  const out: Facts = {
    account_id: accountId,
    shock: shock.name,
    target_months: pyG(targetMonths),
    judge_runway: rw(judge),
    judge_verdict: survives(judge, targetMonths) ? 'survives' : 'runs out before',
    income_after: money(judge.incomeAfter),
    spending_after: money(judge.spendingAfter),
    monthly_gap: money(pyMax(judge.gap, 0)),
    buffer_left: money(judge.bufferLeft),
    buffer_before: money(acct.B),
    one_off: judge.oneOff ? money(judge.oneOff) : null,
    income_changed: shock.incomeMultiplier !== 1 || (shock.incomeCapMonthly !== null && shock.incomeCapMonthly !== undefined),
    already_overdrawn: acct.B <= 0,
    loan_in_trouble: loanInTrouble(acct),
    job_loss: isJobLoss(shock),
    goal_rounding_short: goalGap === 0 && goalTarget - acct.B >= 0.5 ? money(goalTarget - acct.B) : null,
    goal_target: money(goalTarget),
    goal_gap: money(goalGap),
    goal_months: goalMonths === null ? null : pyG(goalMonths),
    ladder_verdict: ladder.verdict,
    ladder_step: null,
    ladder_saving: null,
    cash_or_credit: ladder.cashOrCreditNeeded ? money(ladder.cashOrCreditNeeded) : null,
    reality: {},
    plan_basis: planBasis,
  };
  if (ladder.firstSufficient !== null) {
    const used = ladder.rungs.slice(0, ladder.firstSufficient + 1);
    out.ladder_step = used.map((x) => x.step.replace(/^[+ ]+/, '').trim()).join(', then ');
    out.ladder_saving = money(used[used.length - 1].monthlySaving);
  }
  for (const [name, val] of Object.entries(reality)) {
    if (typeof val === 'number') {
      out.reality[name] = val === Infinity || val === -Infinity ? 'no shortfall (120+ months)' : `${pyFixed(val, 1)} months`;
    } else {
      out.reality[name] = rw(val);
    }
  }
  return out;
}

/** Deterministic story: headline, what changed, plan steps, caveat. */
export function templateStory(f: Facts): Story {
  const headline =
    `Account ${f.account_id}: ${f.judge_runway} of runway after ` +
    `"${f.shock}", so it ${f.judge_verdict} the ${f.target_months}-month test.`;
  const incomeWords = f.income_changed ? 'Income falls to' : 'Income stays at';
  let what: string;
  if (f.already_overdrawn) {
    what =
      `The buffer is already ${f.buffer_before} before any shock, so runway is ${f.judge_runway}; ` +
      `${incomeWords.toLowerCase()} ${f.income_after}/mo against ${f.spending_after}/mo of spending.`;
  } else if (f.judge_runway.startsWith('no shortfall')) {
    what = `${incomeWords} ${f.income_after}/mo, which still covers spending of ${f.spending_after}/mo.`;
    if (f.one_off) what += ` The ${f.one_off} one-off leaves ${f.buffer_left} in the buffer.`;
  } else {
    what = `${incomeWords} ${f.income_after}/mo against ${f.spending_after}/mo of spending`;
    if (f.one_off) {
      what += `, and the ${f.one_off} one-off leaves ${f.buffer_left} in the buffer`;
    } else {
      what += `: a ${f.monthly_gap}/mo gap drawn from a ${f.buffer_left} buffer`;
    }
    what += '.';
  }
  const reality = Object.entries(f.reality)
    .map(([k, v]) => `${k}: ${v}`)
    .join('; ');
  const steps: string[] = [];
  if (f.plan_basis) steps.push(`The plan below also assumes: ${f.plan_basis}.`);
  if (f.ladder_step) {
    steps.push(`If it hits: ${f.ladder_step} (together ${f.ladder_saving}/mo).`);
  } else if (f.cash_or_credit && f.loan_in_trouble) {
    const first = f.job_loss ? 'start the EI claim on day one and ' : '';
    steps.push(
      `If it hits: the remaining hole is ${f.cash_or_credit}. The loan is already in arrears or ` +
        `default, so no new credit: ${first}ask for a hardship deferral.`,
    );
  } else if (f.cash_or_credit) {
    steps.push(`If it hits: cuts alone aren't enough. Line up ${f.cash_or_credit} of credit while still employed.`);
  } else {
    steps.push(`If it hits: ${f.ladder_verdict.toLowerCase()}.`);
  }
  if (f.goal_gap === '$0' && f.goal_rounding_short) {
    steps.push(
      `Goal: the ${f.goal_target} job-loss-proof fund is in place within rounding ` +
        `(${f.goal_rounding_short} under the exact target). Top it up and keep it separate.`,
    );
  } else if (f.goal_gap === '$0') {
    steps.push(
      `Goal: the ${f.goal_target} job-loss-proof fund is already in place. Keep it in a separate savings account.`,
    );
  } else if (f.goal_months) {
    steps.push(
      `Goal: build a ${f.goal_target} job-loss-proof fund. ${f.goal_gap} to go, ` +
        `about ${f.goal_months} months with an automatic monthly transfer of the normal surplus.`,
    );
  } else {
    steps.push(
      `Goal: a ${f.goal_target} job-loss-proof fund is ${f.goal_gap} away, and the normal ` +
        "surplus can't close it: start with the backup steps as a permanent budget change.",
    );
  }
  return {
    headline,
    what_changed: what,
    reality_check: reality,
    plan_steps: steps,
    caveat: "Runway uses the judges' formula; reality checks are our labelled assumptions.",
  };
}
