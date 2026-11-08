/**
 * Per-account rows behind the portfolio drill-down, computed in the browser by the same engine.
 * Bands match resilience/portfolio.py (pd.cut on I, right=False).
 */
import { LAID_OFF_EI, LAID_OFF_EI_CAPPED, applyShock, survives } from '../engine';
import type { Account, RunwayResult } from '../engine';

export const INCOME_EDGES = [0, 2500, 5000, 7500, 10000, 15000, 20000, Infinity] as const;
export const INCOME_LABELS = ['< $2.5k', '$2.5k-5k', '$5k-7.5k', '$7.5k-10k', '$10k-15k', '$15k-20k', '>= $20k'] as const;

/** Index into INCOME_LABELS, or -1 (negative or NaN money in). */
export function bandIndex(I: number): number {
  for (let i = 0; i < INCOME_LABELS.length; i++) {
    if (I >= INCOME_EDGES[i] && I < INCOME_EDGES[i + 1]) return i;
  }
  return -1;
}

export interface AccountRow {
  id: number;
  I: number;
  S: number;
  B: number;
  /** B / S, null when S is 0 */
  bufferMonths: number | null;
  band: number;
  ei: RunwayResult;
  cap: RunwayResult;
}

export function portfolioRows(accounts: readonly Account[]): AccountRow[] {
  return accounts.map((a) => ({
    id: a.id,
    I: a.I,
    S: a.S,
    B: a.B,
    bufferMonths: a.S === 0 ? null : a.B / a.S,
    band: bandIndex(a.I),
    ei: applyShock(a, LAID_OFF_EI),
    cap: applyShock(a, LAID_OFF_EI_CAPPED),
  }));
}

/** The portfolio's "fails 6 months" test: runway < 6, no shortfall counts as a pass. */
export function failsSix(res: RunwayResult): boolean {
  return !survives(res, 6);
}
