/**
 * Month-by-month balance for the January calendar path, for charting.
 *
 * The engine's calendarPath() returns only the month the balance goes negative; this walks the
 * very same arithmetic (shockTerms, each calendar month's median spending, post-shock income every
 * month) and keeps every month-end balance. test/ui.test.ts checks that the zero crossing of this
 * series sits exactly where calendarPath() says, for every account.
 */
import { shockTerms } from '../engine';
import type { Account, RunwayResult, Shock } from '../engine';

export function calendarBalancePath(acct: Account, shock: Shock, months: number, startMonth = 1): number[] {
  const { income, addons, oneOff } = shockTerms(acct, shock);
  let bal = acct.B - oneOff;
  const out = [bal];
  for (let k = 0; k < months; k++) {
    const idx = (((startMonth - 1 + k) % 12) + 12) % 12;
    const c = acct.cal[idx];
    const spend = (c === null || c === undefined || Number.isNaN(c) ? acct.S : c) + addons;
    bal = bal + (income - spend);
    out.push(bal);
  }
  return out;
}

/** The burn-down chart's horizon: months 0..max(24, 2 x the judges' runway). */
export function burnDownHorizon(judge: RunwayResult): number {
  return Math.max(24, Math.ceil(2 * (judge.noShortfall ? 0 : (judge.months ?? 0))));
}
