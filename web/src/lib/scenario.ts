/**
 * Live-twist state: the twist cards, the lever values a card sets, the Shock those levers mean,
 * the twist label, and the URL-hash encoding that lets a scenario survive a reload or be shared.
 * Mirrors app.py (PRESETS, shock_from, twist_label).
 */
import { makeShock, pyG, pyMoney0 } from '../engine';
import type { PresetName, Shock } from '../engine';

export type CardId = 'ei' | 'furnace' | 'double' | 'custom';

export interface Card {
  id: CardId;
  /** the engine preset (and the twist label while the levers equal the card) */
  preset: PresetName;
  key: string;
  title: string;
  detail: string;
}

export const CARDS: readonly Card[] = [
  { id: 'ei', preset: 'Laid off: EI 55%', key: '1', title: 'Laid off', detail: 'EI pays 55% of usual income' },
  {
    id: 'furnace',
    preset: 'Furnace dies: 1× spending',
    key: '2',
    title: 'Furnace dies',
    detail: 'One-off repair = 1 month of typical spending',
  },
  {
    id: 'double',
    preset: 'Job loss + bills +15%',
    key: '3',
    title: 'Job loss + bills +15%',
    detail: 'EI 55% and household bills up 15%',
  },
  { id: 'custom', preset: 'Custom', key: '4', title: 'Custom', detail: 'Starts from no shock: set the levers' },
];

export const CARD_BY_ID: Record<CardId, Card> = Object.fromEntries(CARDS.map((c) => [c.id, c])) as Record<
  CardId,
  Card
>;

export type OneOffMode = 'x' | 'amt';

export interface Levers {
  /** share of usual income still coming in, in percent */
  incomePct: number;
  /** the income drop is a layoff on EI (only counts while incomePct < 100) */
  jobLoss: boolean;
  billsPct: number;
  /** extra monthly cost, CAD */
  extra: number;
  oneOffMode: OneOffMode;
  /** one-off as a multiple of typical spending S */
  oneOffX: number;
  /** one-off in CAD */
  oneOffAmt: number;
}

/** app.py PRESETS, lever by lever. Written as percents so 55 / 100 is the same double as 0.55. */
export const CARD_LEVERS: Record<CardId, Levers> = {
  ei: { incomePct: 55, jobLoss: true, billsPct: 0, extra: 0, oneOffMode: 'x', oneOffX: 0, oneOffAmt: 0 },
  furnace: { incomePct: 100, jobLoss: false, billsPct: 0, extra: 0, oneOffMode: 'x', oneOffX: 1, oneOffAmt: 0 },
  double: { incomePct: 55, jobLoss: true, billsPct: 15, extra: 0, oneOffMode: 'x', oneOffX: 0, oneOffAmt: 0 },
  custom: { incomePct: 100, jobLoss: false, billsPct: 0, extra: 0, oneOffMode: 'x', oneOffX: 0, oneOffAmt: 0 },
};

/** Lever limits: sliders cover the usual range, the exact inputs accept the wider one. */
export const LIMITS = {
  incomePct: { min: 0, max: 100, sliderMax: 100, step: 1 },
  billsPct: { min: 0, max: 200, sliderMax: 50, step: 1 },
  extra: { min: 0, max: 100_000, sliderMax: 5_000, step: 50 },
  oneOffX: { min: 0, max: 12, sliderMax: 3, step: 0.25 },
  oneOffAmt: { min: 0, max: 1_000_000, sliderMax: 50_000, step: 500 },
  target: { min: 1, max: 12, sliderMax: 12, step: 1 },
} as const;

/** app.py shock_from: the Shock a set of lever values means (the inactive one-off input doesn't count). */
export function shockFromLevers(l: Levers, name = 'custom'): Shock {
  const byX = l.oneOffMode === 'x';
  return makeShock({
    incomeMultiplier: l.incomePct / 100,
    billsIncreasePct: l.billsPct / 100,
    extraMonthlyCost: l.extra,
    oneOffCost: byX ? 0 : l.oneOffAmt,
    oneOffMultipleOfS: byX ? l.oneOffX : 0,
    jobLoss: l.jobLoss && l.incomePct < 100,
    name,
  });
}

const LEVER_SHOCK_KEYS = [
  'incomeMultiplier',
  'billsIncreasePct',
  'extraMonthlyCost',
  'oneOffCost',
  'oneOffMultipleOfS',
  'jobLoss',
] as const satisfies readonly (keyof Shock)[];

export function sameLeverShock(a: Shock, b: Shock): boolean {
  return LEVER_SHOCK_KEYS.every((k) => a[k] === b[k]);
}

/** True while the levers still apply exactly what the card applies. */
export function leversMatchCard(card: CardId, l: Levers): boolean {
  return sameLeverShock(shockFromLevers(l), shockFromLevers(CARD_LEVERS[card]));
}

/** app.py twist_label: the card's name only while the shock equals the card; otherwise what is applied. */
export function twistLabel(card: CardId, l: Levers): string {
  if (card !== 'custom' && leversMatchCard(card, l)) return CARD_BY_ID[card].preset;
  const parts: string[] = [];
  if (l.incomePct !== 100) parts.push(`${l.jobLoss ? 'job loss, EI' : 'income kept'} ${pyG(l.incomePct)}%`);
  if (l.billsPct) parts.push(`bills +${pyG(l.billsPct)}%`);
  if (l.extra) parts.push(`+$${pyMoney0(l.extra)}/mo`);
  if (l.oneOffMode === 'x' && l.oneOffX) parts.push(`one-off ${pyG(l.oneOffX)}× spending`);
  if (l.oneOffMode !== 'x' && l.oneOffAmt) parts.push(`one-off $${pyMoney0(l.oneOffAmt)}`);
  return `Custom: ${parts.length ? parts.join(', ') : 'no shock'}`;
}

/** The judges' twist for a card and its levers, named by its twist label. */
export function judgeShockFor(card: CardId, l: Levers): Shock {
  return shockFromLevers(l, twistLabel(card, l));
}

// ------------------------------------------------------------------ whole scenario + URL hash

export type Tab = 'live' | 'portfolio' | 'method';

/** Reality checks: labelled extras, applied only where they make sense for the account and twist. */
export interface Toggles {
  cap: boolean;
  ww: boolean;
  pens: boolean;
  s6: boolean;
  bfb: boolean;
}

export const NO_TOGGLES: Toggles = { cap: false, ww: false, pens: false, s6: false, bfb: false };

export interface Scenario {
  tab: Tab;
  id: number;
  card: CardId;
  levers: Levers;
  /** must survive (months) */
  target: number;
  toggles: Toggles;
}

export const DEFAULT_ACCOUNT = 77743;

export const DEFAULT_SCENARIO: Scenario = {
  tab: 'live',
  id: DEFAULT_ACCOUNT,
  card: 'furnace',
  levers: CARD_LEVERS.furnace,
  target: 6,
  toggles: NO_TOGGLES,
};

const TOGGLE_KEYS = ['cap', 'ww', 'pens', 's6', 'bfb'] as const satisfies readonly (keyof Toggles)[];
const TABS: readonly Tab[] = ['live', 'portfolio', 'method'];

export function encodeScenario(s: Scenario): string {
  const p = new URLSearchParams();
  p.set('tab', s.tab);
  p.set('id', String(s.id));
  p.set('card', s.card);
  p.set('inc', String(s.levers.incomePct));
  p.set('ei', s.levers.jobLoss ? '1' : '0');
  p.set('bills', String(s.levers.billsPct));
  p.set('extra', String(s.levers.extra));
  p.set('oneoff', s.levers.oneOffMode);
  p.set('x', String(s.levers.oneOffX));
  p.set('amt', String(s.levers.oneOffAmt));
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
  const cardRaw = p.get('card');
  const card = cardRaw && cardRaw in CARD_LEVERS ? (cardRaw as CardId) : d.card;
  const cl = CARD_LEVERS[card];
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
  };
  const target = Math.round(clampNum(p.get('n'), LIMITS.target.min, LIMITS.target.max, d.target));
  const checks = new Set((p.get('checks') ?? '').split(',').filter(Boolean));
  const toggles: Toggles = { cap: false, ww: false, pens: false, s6: false, bfb: false };
  for (const k of TOGGLE_KEYS) toggles[k] = checks.has(k);
  return { tab, id, card, levers, target, toggles };
}
