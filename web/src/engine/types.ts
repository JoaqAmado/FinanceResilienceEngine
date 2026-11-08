/** One account's engine inputs: the judges' numbers plus the extras the reality checks and plans use. */
export interface Account {
  id: number;
  /** typical monthly money in = median(money_in) */
  I: number;
  /** typical fixed costs = median(household_bills + insurance + loan_payments) */
  F: number;
  /** typical monthly spending = median(money_out) */
  S: number;
  /** buffer = mean(avg_daily_balance) over the last 6 months */
  B: number;
  /** household bills = median(household_bills) */
  H: number;
  /** running loan payment (loan status C or D), else 0 */
  P: number;
  /** median monthly pension income */
  Pn: number;
  /** typical half-year spending per month (median 6-month window / 6) */
  S6: number | null;
  flexible_median: number;
  bank_fees_median: number;
  transfers_out_other_median: number;
  loan_payments_median: number;
  so_other: number;
  H_SO: number;
  months_of_data: number;
  first_month: string;
  last_month: string;
  loan_status: string | null;
  pre_loan_negative: boolean;
  ever_negative: boolean;
  owner_age: number | null;
  owner_gender: string | null;
  /** median spending per calendar month, January first (null = no full month seen) */
  cal: (number | null)[];
  /** early-warning light inputs today (resilience.warning.light_table): months used after the opening month */
  light_rows_used: number;
  /** days below zero summed over those months */
  light_days_below_zero: number;
  /** the 4 rule inputs over the last 6 of those months, before clipping (null = undefined) */
  light_min_bal_over_S_raw: number | null;
  light_cash_share_raw: number | null;
  light_inc_cv_raw: number | null;
  light_bal_trend_raw: number | null;
  /** median money out over those 6 months: the rules' month of spending, not S (null with no months) */
  light_recent_spending: number | null;
  /** the last of those months, the end of the window (null with no months) */
  light_last_month: string | null;
}

export type SpendingBasis = 'S' | 'S6';

/** A scenario applied to one account's typical month (Python: resilience.core.Shock). */
export interface Shock {
  /** share of I still coming in (0.55 = EI at 55%) */
  incomeMultiplier: number;
  /** reality check: ceiling on the EI part of income */
  incomeCapMonthly: number | null;
  /** household bills rise by this share of H */
  billsIncreasePct: number;
  extraMonthlyCost: number;
  oneOffCost: number;
  /** a one-time cost as a multiple of S */
  oneOffMultipleOfS: number;
  /** share of non-fixed spending (card + cash) cut */
  flexibleCutPct: number;
  waitingWeek: boolean;
  pensionAware: boolean;
  spendingBasis: SpendingBasis;
  billsFallback: boolean;
  /** true when the income drop is a layoff on EI (not a pay cut) */
  jobLoss: boolean;
  name: string;
}

export interface RunwayResult {
  /** null when there is no shortfall */
  months: number | null;
  noShortfall: boolean;
  bufferLeft: number;
  gap: number;
  incomeAfter: number;
  spendingAfter: number;
  oneOff: number;
  capped: boolean;
}

export interface ShockTerms {
  income: number;
  /** monthly spending add-ons on top of the base spending */
  addons: number;
  oneOff: number;
  /** S, or S6 when spendingBasis is 'S6' */
  base: number;
}

export type GoalKind = 'months_of_S' | 'ei_proof';

export interface GoalPlan {
  targetBuffer: number;
  currentBuffer: number;
  shortfall: number;
  monthlySurplus: number;
  /** null when the normal surplus can't close the gap */
  monthsToTarget: number | null;
  targetKind: GoalKind;
}

export interface BackupPlan {
  targetMonths: number;
  shocked: RunwayResult;
  monthlyCutNeeded: number;
  flexiblePool: number;
  cutShareOfFlexible: number | null;
  feasible: boolean;
  afterCut: RunwayResult;
  bufferWiped: boolean;
  cashNeeded: number;
  normalSurplus: number;
}

export interface Rung {
  step: string;
  /** cumulative saving vs the shocked spending, CAD/month, rounded to the cent */
  monthlySaving: number;
  result: RunwayResult;
  reachesTarget: boolean;
}

export interface Ladder {
  targetMonths: number;
  shocked: RunwayResult;
  alreadySafe: boolean;
  bufferWiped: boolean;
  /** the buffer was negative before any shock */
  overdrawn: boolean;
  rungs: Rung[];
  /** index into rungs */
  firstSufficient: number | null;
  cashOrCreditNeeded: number;
  verdict: string;
}

export type Flag = [code: string, text: string];
