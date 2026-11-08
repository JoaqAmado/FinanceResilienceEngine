/**
 * Display helpers, matching app.py's money / rw_text / path_text so the web app prints the same
 * strings as the Streamlit app. All decimal formatting goes through the engine's Python-exact
 * formatters (ties to even), never toFixed.
 */
import { money, pyFixed, pyMoney0 } from '../engine';
import type { RunwayResult } from '../engine';

export { money };

/** app.py rw_text */
export function rwText(res: RunwayResult): string {
  if (res.noShortfall) return 'No shortfall (120+)';
  const m = res.months ?? 0;
  return m >= 120 ? '120.0 mo (cap)' : `${pyFixed(m, 1)} mo`;
}

/** app.py path_text (calendar path: Infinity = never runs out within the horizon) */
export function pathText(x: number): string {
  return x === Infinity ? 'No shortfall (120+)' : `${pyFixed(x, 1)} mo`;
}

/** Months as a number for sorting and deltas: no shortfall = Infinity. */
export function monthsOf(v: RunwayResult | number): number {
  if (typeof v === 'number') return v;
  return v.noShortfall ? Infinity : (v.months ?? 0);
}

/** Signed change vs the judges' number, e.g. "-2.7 mo" (Python f"{x:+.1f}"). */
export function deltaText(v: RunwayResult | number, judge: RunwayResult): string {
  const a = monthsOf(v);
  const b = monthsOf(judge);
  if (a === Infinity && b === Infinity) return 'no change';
  if (a === Infinity) return 'now no shortfall';
  if (b === Infinity) return 'shortfall appears';
  const d = a - b;
  if (d === 0) return 'no change';
  const s = pyFixed(d, 1);
  return `${s.startsWith('-') ? s : `+${s}`} mo`;
}

/** -1, 0 or 1: is the check's runway shorter, equal or longer than the judges'. */
export function deltaSign(v: RunwayResult | number, judge: RunwayResult): number {
  const a = monthsOf(v);
  const b = monthsOf(judge);
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

/** Python f"{x:.1%}" */
export function pct1(share: number): string {
  return `${pyFixed(share * 100, 1)}%`;
}

/** A value that is already a percentage, one decimal: 4.8 -> "4.8%" */
export function pctValue(v: number | null): string {
  return v === null ? 'n/a' : `${pyFixed(v, 1)}%`;
}

/** Dollars in thousands, one decimal: 13943 -> "$13.9k" (resilience.portfolio._k). */
export function kMoney(x: number): string {
  return `$${pyFixed(x / 1000, 1)}k`;
}

/** Whole number with thousands separators (Python f"{n:,}"). */
export function count(n: number): string {
  return pyMoney0(n);
}

const compact = new Intl.NumberFormat('en-CA', { notation: 'compact', maximumFractionDigits: 1 });

/** Axis ticks: $0, $5K, $1.2M, -$5K. */
export function axisMoney(v: number): string {
  if (v === 0) return '$0';
  return `${v < 0 ? '-' : ''}$${compact.format(Math.abs(v))}`;
}
