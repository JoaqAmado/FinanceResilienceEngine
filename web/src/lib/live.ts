/**
 * Everything the live-twist screen shows for one account and one scenario, computed in one pass
 * from the engine, in the same order and with the same rules as app.py.
 */
import {
  EI_2026_MAX_MONTHLY,
  WAITING_WEEK_LABEL,
  applyShock,
  backupLadder,
  calendarPath,
  facts,
  goalPlan,
  goalShockFor,
  greyZoneNote,
  isJobLoss,
  makeShock,
  pyMoney0,
  templateStory,
  withShock,
} from '../engine';
import type { Account, Facts, GoalPlan, Ladder, RunwayResult, Shock, Story } from '../engine';
import { shockFromLevers } from './scenario';
import type { Scenario, Toggles } from './scenario';

export type CheckKey = keyof Toggles;

export interface CheckRow {
  key: CheckKey;
  label: string;
  help: string;
  /** the check makes sense for this account and twist */
  enabled: boolean;
  /** why it is disabled */
  reason: string | null;
  /** the toggle is on and applies */
  on: boolean;
  /** runway with this check alone on top of the judges' twist */
  result: RunwayResult;
}

export interface LiveModel {
  judgeShock: Shock;
  jobLoss: boolean;
  judge: RunwayResult;
  /** runway before any shock */
  baseline: RunwayResult;
  /** judges' twist + every reality check that is on */
  realShock: Shock;
  real: RunwayResult;
  anyCheckOn: boolean;
  activeNames: string[];
  checks: CheckRow[];
  /** month-by-month path starting in January, on the judges' twist */
  jan: number;
  greyNote: string | null;
  planShock: Shock;
  /** the shock the job-loss-proof fund is sized on */
  goalShock: Shock;
  goal: GoalPlan;
  /** conventional benchmark: 3 months of spending */
  conventional: GoalPlan;
  ladder: Ladder;
  facts: Facts;
  story: Story;
}

export function buildLive(acct: Account, s: Scenario): LiveModel {
  const judgeShock = shockFromLevers(s.levers);
  const jobLoss = isJobLoss(judgeShock);
  const N = s.target;

  const can: Toggles = {
    cap: jobLoss,
    ww: jobLoss,
    pens: jobLoss && acct.Pn > 0,
    s6: true,
    bfb: acct.H === 0 && acct.H_SO > 0,
  };
  // a disabled toggle keeps its old value, so only apply each check where it makes sense (app.py)
  const on: Toggles = {
    cap: s.toggles.cap && can.cap,
    ww: s.toggles.ww && can.ww,
    pens: s.toggles.pens && can.pens,
    s6: s.toggles.s6 && can.s6,
    bfb: s.toggles.bfb && can.bfb,
  };
  const realShock = withShock(judgeShock, {
    incomeCapMonthly: on.cap ? EI_2026_MAX_MONTHLY : null,
    waitingWeek: on.ww,
    pensionAware: on.pens,
    spendingBasis: on.s6 ? 'S6' : 'S',
    billsFallback: on.bfb,
  });

  const judge = applyShock(acct, judgeShock);
  const real = applyShock(acct, realShock);
  const baseline = applyShock(acct, makeShock());
  const jan = calendarPath(acct, judgeShock);
  const alone = (changes: Partial<Shock>) => applyShock(acct, withShock(judgeShock, changes));
  const notEI = 'Only for a job loss on EI';

  const checks: CheckRow[] = [
    {
      key: 'cap',
      label: `2026 EI cap ($${pyMoney0(EI_2026_MAX_MONTHLY)}/mo)`,
      help: 'EI pays at most $729/week in 2026 (canada.ca)',
      enabled: can.cap,
      reason: can.cap ? null : notEI,
      on: on.cap,
      result: alone({ incomeCapMonthly: EI_2026_MAX_MONTHLY }),
    },
    {
      key: 'ww',
      label: WAITING_WEEK_LABEL,
      help: 'No EI for the first week of the claim',
      enabled: can.ww,
      reason: can.ww ? null : notEI,
      on: on.ww,
      result: alone({ waitingWeek: true }),
    },
    {
      key: 'pens',
      label: 'Keep pension on job loss',
      help: 'A pension keeps paying when a job stops',
      enabled: can.pens,
      reason: can.pens ? null : jobLoss ? 'No pension income on this account' : notEI,
      on: on.pens,
      result: alone({ pensionAware: true }),
    },
    {
      key: 's6',
      label: 'Typical half-year spending',
      help:
        acct.S6 === null
          ? 'No full half-year on record, so this falls back to S'
          : 'Median 6-month spend ÷ 6, instead of the median month',
      enabled: true,
      reason: null,
      on: on.s6,
      result: alone({ spendingBasis: 'S6' }),
    },
    {
      key: 'bfb',
      label: 'Bills paid by standing order',
      help: `Count $${pyMoney0(acct.H_SO)}/mo of standing-order bills as household bills`,
      enabled: can.bfb,
      reason: can.bfb ? null : acct.H > 0 ? 'Household bills are already in H' : 'No standing-order bills on record',
      on: on.bfb,
      result: alone({ billsFallback: true }),
    },
  ];

  const activeNames = (
    [
      ['2026 EI cap', on.cap],
      ['waiting week', on.ww],
      ['pension kept', on.pens],
      ['half-year spending', on.s6],
      ['bills by standing order', on.bfb],
    ] as const
  )
    .filter(([, v]) => v)
    .map(([n]) => n);

  const planShock = realShock;
  const goalShock = goalShockFor(planShock);
  const goal = goalPlan(acct, N, 'ei_proof', goalShock);
  const conventional = goalPlan(acct, 3);
  const ladder = backupLadder(acct, planShock, N);
  const f: Facts = facts(
    acct.id,
    acct,
    judgeShock,
    judge,
    { 'half-year spending': alone({ spendingBasis: 'S6' }), 'starting in January': jan },
    ladder,
    goal.targetBuffer,
    goal.shortfall,
    goal.monthsToTarget,
    N,
    activeNames.join(', '),
  );

  return {
    judgeShock,
    jobLoss,
    judge,
    baseline,
    realShock,
    real,
    anyCheckOn: activeNames.length > 0,
    activeNames,
    checks,
    jan,
    greyNote: greyZoneNote(judge, judgeShock),
    planShock,
    goalShock,
    goal,
    conventional,
    ladder,
    facts: f,
    story: templateStory(f),
  };
}
