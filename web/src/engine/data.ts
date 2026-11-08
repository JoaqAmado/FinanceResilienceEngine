/**
 * Shapes of the files scripts/export_web_data.py writes to web/public/data, and the decoder
 * for the columnar accounts.json.
 */
import type { Account } from './types';

export const ACCOUNT_FIELDS = [
  'id',
  'I',
  'F',
  'S',
  'B',
  'H',
  'P',
  'Pn',
  'S6',
  'flexible_median',
  'bank_fees_median',
  'transfers_out_other_median',
  'loan_payments_median',
  'so_other',
  'H_SO',
  'months_of_data',
  'first_month',
  'last_month',
  'loan_status',
  'pre_loan_negative',
  'ever_negative',
  'owner_age',
  'owner_gender',
  'cal',
] as const satisfies readonly (keyof Account)[];

/** accounts.json: one row per account, values in the order of `fields`. */
export interface AccountsFile {
  version: 1;
  fields: string[];
  rows: unknown[][];
}

export function decodeAccounts(file: AccountsFile): Account[] {
  if (file.version !== 1) throw new Error(`accounts.json version ${String(file.version)} is not supported`);
  const index = new Map(file.fields.map((f, i) => [f, i]));
  const missing = ACCOUNT_FIELDS.filter((f) => !index.has(f));
  if (missing.length) throw new Error(`accounts.json is missing fields: ${missing.join(', ')}`);
  return file.rows.map((row) => {
    const a: Record<string, unknown> = {};
    for (const f of ACCOUNT_FIELDS) a[f] = row[index.get(f) as number];
    return a as unknown as Account;
  });
}

/** history/<id>.json: the account's months, oldest first. */
export interface AccountHistory {
  id: number;
  month: string[];
  money_in: number[];
  money_out: number[];
  month_end_balance: number[];
}

export interface PortfolioHeadlines {
  accounts: number;
  fail_6mo_ei55: number;
  fail_6mo_ei55_cap2026: number;
  fail_6mo_ei55_S6: number;
  fail_6mo_ei55_pension_aware: number;
  fail_6mo_ei55_january_path: number;
  fail_6mo_furnace: number;
  fail_6mo_double_whammy: number;
  ei_cap_monthly_2026: number;
  median_min_cut_failing: number;
}

/** portfolio.json: headline numbers and the chart tables of resilience.portfolio.build_all. */
export interface PortfolioFile {
  version: 1;
  headlines: PortfolioHeadlines;
  income_bands: {
    income_band: string;
    accounts: number;
    fail_6mo_ei55_pct: number | null;
    fail_6mo_ei55_cap2026_pct: number | null;
    median_buffer_months: number | null;
    median_I: number | null;
  }[];
  s6_calibration: { judge_runway_months: string; accounts: number; fail_6mo_on_S6_pct: number | null }[];
  cut_histogram: { cut_as_share_of_spending: string; accounts: number }[];
  preloan_overdraft: Record<string, string | number | null>[];
  runway_columns: string[];
}
