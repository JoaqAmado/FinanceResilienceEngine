/**
 * Python/numpy-compatible rounding and number formatting.
 *
 * The engine's numbers and story strings must match the Python engine character for
 * character, so nothing here uses Math.round or toFixed (both break ties away from zero).
 * Python formats and rounds the EXACT binary value of a double with ties to even;
 * numpy's np.round(x, d) is rint(x * 10**d) / 10**d with rint ties to even.
 */

/** numpy.rint: round to the nearest integer, ties to even. */
export function rint(x: number): number {
  if (!Number.isFinite(x)) return x;
  const f = Math.floor(x);
  const d = x - f; // exact for every double
  let r: number;
  if (d < 0.5) r = f;
  else if (d > 0.5) r = f + 1;
  else r = f % 2 === 0 ? f : f + 1;
  return r === 0 && (x < 0 || Object.is(x, -0)) ? -0 : r;
}

/** numpy.round(x, decimals) for decimals >= 0: rint(x * 10**decimals) / 10**decimals. */
export function npRound(x: number, decimals = 1): number {
  const f = 10 ** decimals;
  return rint(x * f) / f;
}

/** Python's builtin min(a, b): the first argument unless the second is strictly smaller. */
export function pyMin(a: number, b: number): number {
  return b < a ? b : a;
}

/** Python's builtin max(a, b): the first argument unless the second is strictly larger. */
export function pyMax(a: number, b: number): number {
  return b > a ? b : a;
}

/** |x| = n / 10^k exactly (n a BigInt, k >= 0), plus the sign bit. */
function exactDecimal(x: number): { neg: boolean; n: bigint; k: number } {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const hi = view.getUint32(0);
  const lo = view.getUint32(4);
  const neg = hi >>> 31 === 1;
  const e = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let exp: number;
  if (e === 0) {
    exp = -1074;
  } else {
    mant |= 1n << 52n;
    exp = e - 1075;
  }
  if (exp >= 0) return { neg, n: mant << BigInt(exp), k: 0 };
  // mant / 2^k == mant * 5^k / 10^k
  return { neg, n: mant * 5n ** BigInt(-exp), k: -exp };
}

/** n / d rounded to an integer, ties to even (n, d > 0). */
function divHalfEven(n: bigint, d: bigint): bigint {
  const q = n / d;
  const r2 = (n % d) * 2n;
  if (r2 > d) return q + 1n;
  if (r2 === d) return q % 2n === 0n ? q : q + 1n;
  return q;
}

function group(intPart: string): string {
  return intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function nonFinite(x: number): string {
  if (Number.isNaN(x)) return 'nan';
  return x < 0 ? '-inf' : 'inf';
}

/** Python f"{x:.{digits}f}", or f"{x:,.{digits}f}" with grouping. */
export function pyFixed(x: number, digits: number, grouping = false): string {
  if (!Number.isFinite(x)) return nonFinite(x);
  const { neg, n, k } = exactDecimal(x);
  const q = k > digits ? divHalfEven(n, 10n ** BigInt(k - digits)) : n * 10n ** BigInt(digits - k);
  const s = q.toString().padStart(digits + 1, '0');
  const intPart = s.slice(0, s.length - digits);
  const frac = s.slice(s.length - digits);
  return (neg ? '-' : '') + (grouping ? group(intPart) : intPart) + (digits > 0 ? `.${frac}` : '');
}

/** Python f"{x:,.0f}". */
export function pyMoney0(x: number): string {
  return pyFixed(x, 0, true);
}

/** Python f"{x:.0%}" (Python multiplies by 100 as a float first). */
export function pyPercent0(x: number): string {
  return `${pyFixed(x * 100, 0)}%`;
}

/** Python f"{x:g}" (precision 6). */
export function pyG(x: number, precision = 6): string {
  if (!Number.isFinite(x)) return nonFinite(x);
  const p = precision === 0 ? 1 : precision;
  const { neg, n, k } = exactDecimal(x);
  const sign = neg ? '-' : '';
  if (n === 0n) return `${sign}0`;
  let digits = n.toString();
  let X = digits.length - 1 - k; // decimal exponent of the leading digit
  if (digits.length > p) {
    let q = divHalfEven(n, 10n ** BigInt(digits.length - p));
    if (q.toString().length > p) {
      q /= 10n; // 9.999995 -> 10.0000: one more digit, one more exponent
      X += 1;
    }
    digits = q.toString();
  } else {
    digits = digits.padEnd(p, '0');
  }
  const strip = (s: string) => s.replace(/0+$/, '');
  if (X >= -4 && X < p) {
    let intPart: string;
    let frac: string;
    if (X >= 0) {
      intPart = digits.slice(0, X + 1);
      frac = digits.slice(X + 1);
    } else {
      intPart = '0';
      frac = '0'.repeat(-X - 1) + digits;
    }
    frac = strip(frac);
    return sign + intPart + (frac ? `.${frac}` : '');
  }
  const rest = strip(digits.slice(1));
  const e = Math.abs(X).toString().padStart(2, '0');
  return `${sign}${digits[0]}${rest ? `.${rest}` : ''}e${X < 0 ? '-' : '+'}${e}`;
}

/** Python round(x, ndigits): the double nearest the correctly rounded decimal (ties to even). */
export function pyRound(x: number, ndigits: number): number {
  if (!Number.isFinite(x)) return x;
  return Number.parseFloat(pyFixed(x, ndigits));
}
