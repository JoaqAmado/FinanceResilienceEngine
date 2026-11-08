/**
 * Live-twist state: the lever values (one source of truth: the chat writes them, the Fine-tune sliders show them),
 * the Shock they mean, and the URL-hash encoding that lets a scenario survive a reload or be shared.
 * Mirrors app.py and resilience/shock_parser.py (shock_from_state, shock_to_state, twist_label).
 */
import { judgesShockFromLevers, twistLabel as describe } from '../engine/shock_parser';
import type { CheckToggles, LeverState } from '../engine/shock_parser';
import type { Shock } from '../engine';

export type OneOffMode = 'x' | 'amt';
export type Levers = LeverState;
export type Toggles = CheckToggles;

/** No shock at all: what "reset" goes back to. */
export const NO_SHOCK: Levers = {
  incomePct: 100, jobLoss: false, billsPct: 0, extra: 0, oneOffMode: 'x', oneOffX: 0, oneOffAmt: 0, cutPct: 0,
};

/** The first screen: account 77743, the furnace twist (one-off of 1 month of typical spending). */
export const FURNACE_LEVERS: Levers = { ...NO_SHOCK, oneOffX: 1 };

/** Lever limits: sliders cover the usual range, the exact inputs accept the wider one. */
export const LIMITS = {
  incomePct: { min: 0, max: 100, sliderMax: 100, step: 1 },
  billsPct: { min: 0, max: 100, sliderMax: 50, step: 1 },
  cutPct: { min: 0, max: 100, sliderMax: 100, step: 1 },
  extra: { min: 0, max: 1_000_000, sliderMax: 5_000, step: 50 },
  oneOffX: { min: 0, max: 12, sliderMax: 3, step: 0.25 },
  oneOffAmt: { min: 0, max: 1_000_000, sliderMax: 50_000, step: 500 },
  target: { min: 1, max: 24, sliderMax: 24, step: 1 },
} as const;

/** The judges' twist a set of lever values means, named by its twist label (shock_parser.judges_shock_from_state). */
export function shockFromLevers(l: Levers): Shock {
  return judgesShockFromLevers(l);
}

/** app.py twist_label: one function with the chat's "understood as" line (shock_parser.describe_shock). */
export function twistLabel(l: Levers): string {
  return describe(shockFromLevers(l));
}

// ------------------------------------------------------------------ whole scenario + URL hash

export type Tab = 'live' | 'portfolio' | 'method';

export const NO_TOGGLES: Toggles = { cap: false, ww: false, pens: false, s6: false, bfb: false };

export interface Scenario {
  tab: Tab;
  id: number;
  levers: Levers;
  /** must survive (months) */
  target: number;
  toggles: Toggles;
}

export const DEFAULT_ACCOUNT = 77743;

export const DEFAULT_SCENARIO: Scenario = {
  tab: 'live',
  id: DEFAULT_ACCOUNT,
  levers: FURNACE_LEVERS,
  target: 6,
  toggles: NO_TOGGLES,
};

const TOGGLE_KEYS = ['cap', 'ww', 'pens', 's6', 'bfb'] as const satisfies readonly (keyof Toggles)[];
const TABS: readonly Tab[] = ['live', 'portfolio', 'method'];

export function encodeScenario(s: Scenario): string {
  const p = new URLSearchParams();
  p.set('tab', s.tab);
  p.set('id', String(s.id));
  p.set('inc', String(s.levers.incomePct));
  p.set('ei', s.levers.jobLoss ? '1' : '0');
  p.set('bills', String(s.levers.billsPct));
  p.set('extra', String(s.levers.extra));
  p.set('oneoff', s.levers.oneOffMode);
  p.set('x', String(s.levers.oneOffX));
  p.set('amt', String(s.levers.oneOffAmt));
  p.set('cut', String(s.levers.cutPct));
  p.set('n', String(s.target));
  const on = TOGGLE_KEYS.filter((k) => s.toggles[k]);
  if (on.length) p.set('checks', on.join(','));
  return p.toString();
}

function clampNum(v: string | null, lo: number, hi: number, fallback: number): number {
  if (v === null || v.trim() === '') return fallback;
  const n = Number(v);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(hi, Math.max(lo, n));
}

/** Parse a location.hash (with or without '#'); anything missing or invalid falls back to the default. */
export function decodeScenario(hash: string): Scenario {
  const p = new URLSearchParams(hash.replace(/^#/, ''));
  const d = DEFAULT_SCENARIO;
  const tabRaw = p.get('tab');
  const tab = TABS.includes(tabRaw as Tab) ? (tabRaw as Tab) : d.tab;
  // a link from before the chat names a twist card and no levers: start from that card's levers
  const card = p.get('card');
  const cl: Levers = card === 'ei' ? { ...NO_SHOCK, incomePct: 55, jobLoss: true }
    : card === 'double' ? { ...NO_SHOCK, incomePct: 55, jobLoss: true, billsPct: 15 }
    : card === 'custom' ? NO_SHOCK : d.levers;
  const idRaw = Number(p.get('id'));
  const id = Number.isInteger(idRaw) && idRaw > 0 ? idRaw : d.id;
  const mode = p.get('oneoff');
  const levers: Levers = {
    incomePct: clampNum(p.get('inc'), LIMITS.incomePct.min, LIMITS.incomePct.max, cl.incomePct),
    jobLoss: p.has('ei') ? p.get('ei') === '1' : cl.jobLoss,
    billsPct: clampNum(p.get('bills'), LIMITS.billsPct.min, LIMITS.billsPct.max, cl.billsPct),
    extra: clampNum(p.get('extra'), LIMITS.extra.min, LIMITS.extra.max, cl.extra),
    oneOffMode: mode === 'amt' || mode === 'x' ? mode : cl.oneOffMode,
    oneOffX: clampNum(p.get('x'), LIMITS.oneOffX.min, LIMITS.oneOffX.max, cl.oneOffX),
    oneOffAmt: clampNum(p.get('amt'), LIMITS.oneOffAmt.min, LIMITS.oneOffAmt.max, cl.oneOffAmt),
    cutPct: clampNum(p.get('cut'), LIMITS.cutPct.min, LIMITS.cutPct.max, cl.cutPct),
  };
  const target = Math.round(clampNum(p.get('n'), LIMITS.target.min, LIMITS.target.max, d.target));
  const checks = new Set((p.get('checks') ?? '').split(',').filter(Boolean));
  const toggles: Toggles = { cap: false, ww: false, pens: false, s6: false, bfb: false };
  for (const k of TOGGLE_KEYS) toggles[k] = checks.has(k);
  return { tab, id, levers, target, toggles };
}
