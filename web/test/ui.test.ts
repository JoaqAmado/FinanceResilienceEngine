/**
 * UI-side guarantees on top of the engine parity suite:
 *   - the twist cards' lever values mean exactly the engine presets (and app.py's twist labels)
 *   - the January balance series crosses $0 exactly where calendarPath() says
 *   - the hero number's Intl formatting (NumberFlow) prints the same digits as Python's :.1f
 *   - the portfolio drill-down bands reproduce resilience/portfolio.py's table
 *   - a scenario survives the URL-hash round trip
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  FURNACE,
  LAID_OFF_EI,
  DOUBLE_WHAMMY,
  PRESETS,
  applyShock,
  calendarPath,
  decodeAccounts,
  makeShock,
  npRound,
  pyFixed,
  withShock,
} from '../src/engine';
import type { AccountsFile, PortfolioFile, Shock } from '../src/engine';
import { buildLive } from '../src/lib/live';
import { calendarBalancePath } from '../src/lib/paths';
import { INCOME_LABELS, failsSix, portfolioRows } from '../src/lib/portfolio';
import {
  CARDS,
  CARD_LEVERS,
  DEFAULT_SCENARIO,
  decodeScenario,
  encodeScenario,
  judgeShockFor,
  leversMatchCard,
  shockFromLevers,
  twistLabel,
} from '../src/lib/scenario';
import type { Scenario } from '../src/lib/scenario';

const read = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const accounts = decodeAccounts(read('../public/data/accounts.json') as AccountsFile);
const portfolio = read('../public/data/portfolio.json') as PortfolioFile;

const SHOCK_FIELDS: (keyof Shock)[] = [
  'incomeMultiplier',
  'incomeCapMonthly',
  'billsIncreasePct',
  'extraMonthlyCost',
  'oneOffCost',
  'oneOffMultipleOfS',
  'flexibleCutPct',
  'waitingWeek',
  'pensionAware',
  'spendingBasis',
  'billsFallback',
  'jobLoss',
  'name',
];

describe('twist cards', () => {
  it('each card applies exactly its engine preset, named by the card', () => {
    for (const c of CARDS) {
      const got = judgeShockFor(c.id, CARD_LEVERS[c.id]);
      const want = PRESETS[c.preset];
      for (const k of SHOCK_FIELDS) {
        // Custom's label is app.py's "Custom: no shock", which is the preset's name too
        expect(got[k], `${c.id}.${k}`).toBe(want[k]);
      }
      expect(leversMatchCard(c.id, CARD_LEVERS[c.id])).toBe(true);
    }
  });

  it('the presets are the README twists the vectors were exported for', () => {
    const same = (a: Shock, b: Shock) => SHOCK_FIELDS.filter((k) => k !== 'name').every((k) => a[k] === b[k]);
    expect(same(PRESETS['Laid off: EI 55%'], LAID_OFF_EI)).toBe(true);
    expect(same(PRESETS['Furnace dies: 1× spending'], FURNACE)).toBe(true);
    expect(same(PRESETS['Job loss + bills +15%'], DOUBLE_WHAMMY)).toBe(true);
  });

  it('twist labels follow app.py', () => {
    const custom = CARD_LEVERS.custom;
    expect(twistLabel('custom', custom)).toBe('Custom: no shock');
    expect(twistLabel('custom', { ...custom, incomePct: 70, extra: 400 })).toBe('Custom: income kept 70%, +$400/mo');
    expect(twistLabel('ei', { ...CARD_LEVERS.ei, incomePct: 60 })).toBe('Custom: job loss, EI 60%');
    expect(twistLabel('double', { ...CARD_LEVERS.double, billsPct: 20 })).toBe('Custom: job loss, EI 55%, bills +20%');
    expect(twistLabel('furnace', { ...CARD_LEVERS.furnace, oneOffX: 1.5 })).toBe('Custom: one-off 1.5× spending');
    expect(twistLabel('furnace', { ...CARD_LEVERS.furnace, oneOffMode: 'amt', oneOffAmt: 12500 })).toBe(
      'Custom: one-off $12,500',
    );
    // the inactive one-off input doesn't count: switching mode with $0 is no shock
    expect(twistLabel('custom', { ...custom, oneOffMode: 'amt', oneOffX: 2 })).toBe('Custom: no shock');
    // the job-loss box only counts while income is below 100%
    expect(shockFromLevers({ ...custom, jobLoss: true }).jobLoss).toBe(false);
    expect(twistLabel('ei', { ...CARD_LEVERS.ei, jobLoss: false })).toBe('Custom: income kept 55%');
  });

  it('a lever-built shock equals the engine shock with the same fractions', () => {
    const l = { ...CARD_LEVERS.custom, incomePct: 57.5, billsPct: 15, jobLoss: true };
    const s = shockFromLevers(l);
    expect(s.incomeMultiplier).toBe(0.575);
    expect(s.billsIncreasePct).toBe(0.15);
  });
});

describe('January balance series', () => {
  const shocks = [LAID_OFF_EI, FURNACE, DOUBLE_WHAMMY, makeShock(), withShock(LAID_OFF_EI, { waitingWeek: true })];
  it('crosses $0 where calendarPath() says, for every account', () => {
    let checked = 0;
    for (const a of accounts) {
      for (const sh of shocks) {
        const cp = calendarPath(a, sh);
        const path = calendarBalancePath(a, sh, 120);
        expect(path.length).toBe(121);
        if (path[0] <= 0) {
          expect(cp).toBe(0);
        } else {
          const k = path.findIndex((v, i) => i > 0 && v < 0);
          if (k === -1) {
            expect(cp).toBe(Infinity);
          } else {
            // calendarPath = round(k - 1 + bal / (spend - inc), 1): inside month k
            expect(cp).toBeGreaterThanOrEqual(k - 1);
            expect(cp).toBeLessThanOrEqual(k);
            const interp = npRound(k - 1 + path[k - 1] / (path[k - 1] - path[k]), 1);
            expect(Math.abs(interp - cp)).toBeLessThanOrEqual(0.1 + 1e-9);
          }
        }
        checked++;
      }
    }
    expect(checked).toBe(accounts.length * shocks.length);
  });
});

describe('hero number formatting', () => {
  const fmt = new Intl.NumberFormat('en-CA', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  it("Intl en-CA one-decimal output equals Python's :.1f for every judges' runway", () => {
    let n = 0;
    // the four cards, plus an income-kept grid in 5% steps with the bills and one-off levers moved
    const grid = Array.from({ length: 21 }, (_, i) =>
      shockFromLevers({ ...CARD_LEVERS.custom, incomePct: i * 5, jobLoss: true, billsPct: i % 4 * 5, oneOffX: (i % 3) * 0.25 }),
    );
    const shocks = [...Object.values(PRESETS), ...grid];
    let bad = 0;
    for (const a of accounts) {
      for (const sh of shocks) {
        const r = applyShock(a, sh);
        if (r.months === null) continue;
        if (fmt.format(r.months).replace(/,/g, '') !== pyFixed(r.months, 1)) bad++;
        n++;
      }
    }
    expect(bad).toBe(0);
    expect(n).toBeGreaterThan(50_000);
  });
});

describe('portfolio drill-down', () => {
  it('bands reproduce the income_bands table of resilience/portfolio.py', () => {
    const rows = portfolioRows(accounts);
    expect(rows.every((r) => r.band >= 0)).toBe(true);
    INCOME_LABELS.forEach((label, i) => {
      const band = rows.filter((r) => r.band === i);
      const want = portfolio.income_bands[i];
      expect(want.income_band).toBe(label);
      expect(band.length).toBe(want.accounts);
      expect(npRound((band.filter((r) => failsSix(r.ei)).length / band.length) * 100, 1)).toBe(want.fail_6mo_ei55_pct);
      expect(npRound((band.filter((r) => failsSix(r.cap)).length / band.length) * 100, 1)).toBe(
        want.fail_6mo_ei55_cap2026_pct,
      );
    });
    expect(rows.filter((r) => failsSix(r.ei)).length).toBe(portfolio.headlines.fail_6mo_ei55);
    expect(rows.filter((r) => failsSix(r.cap)).length).toBe(portfolio.headlines.fail_6mo_ei55_cap2026);
  });
});

describe('scenario state', () => {
  it('round-trips through the URL hash', () => {
    const s: Scenario = {
      tab: 'portfolio',
      id: 20331,
      card: 'double',
      levers: { incomePct: 57.5, jobLoss: true, billsPct: 22, extra: 350, oneOffMode: 'amt', oneOffX: 0.75, oneOffAmt: 4200 },
      target: 9,
      toggles: { cap: true, ww: false, pens: true, s6: true, bfb: false },
    };
    expect(decodeScenario(`#${encodeScenario(s)}`)).toEqual(s);
    expect(decodeScenario(encodeScenario(DEFAULT_SCENARIO))).toEqual(DEFAULT_SCENARIO);
  });

  it('falls back to safe values on junk', () => {
    const s = decodeScenario('#tab=nope&id=-4&card=zzz&inc=900&n=40&bills=abc');
    expect(s.tab).toBe('live');
    expect(s.id).toBe(DEFAULT_SCENARIO.id);
    expect(s.card).toBe(DEFAULT_SCENARIO.card);
    expect(s.levers.incomePct).toBe(100);
    expect(s.target).toBe(12);
    expect(s.levers.billsPct).toBe(CARD_LEVERS[DEFAULT_SCENARIO.card].billsPct);
  });
});

describe('live screen model', () => {
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const at = (id: number, patch: Partial<Scenario> = {}) =>
    buildLive(byId.get(id)!, { ...DEFAULT_SCENARIO, id, card: 'ei', levers: CARD_LEVERS.ei, ...patch });

  it('rehearsal numbers from the pitch script', () => {
    // research/pitch-and-twist-script.md, "Rehearsal accounts"
    expect(at(77743).judge.months).toBe(4.8);
    expect(at(77743, { card: 'furnace', levers: CARD_LEVERS.furnace }).judge.months).toBe(0);
    expect(at(20331).judge.months).toBe(5.1);
    expect(at(20143).judge.months).toBe(2.2);
    expect(at(88269).judge.months).toBe(11.3);
    expect(at(98952).judge.months).toBe(4.2);
    const pens = at(98952, { toggles: { cap: false, ww: false, pens: true, s6: false, bfb: false } });
    expect(pens.real.months).toBe(23.4);
    const cap = at(20331).checks.find((c) => c.key === 'cap')!;
    expect(cap.result.months).toBe(2.4);
  });

  it('reality checks never change the judges number, and disabled checks never apply', () => {
    const allOn = { cap: true, ww: true, pens: true, s6: true, bfb: true };
    for (const a of accounts.slice(0, 400)) {
      for (const card of ['ei', 'furnace', 'custom'] as const) {
        const m = buildLive(a, { ...DEFAULT_SCENARIO, id: a.id, card, levers: CARD_LEVERS[card], toggles: allOn });
        const plain = buildLive(a, { ...DEFAULT_SCENARIO, id: a.id, card, levers: CARD_LEVERS[card] });
        expect(m.judge).toEqual(plain.judge);
        for (const c of m.checks) if (!c.enabled) expect(c.on).toBe(false);
        if (!m.jobLoss) {
          expect(m.realShock.incomeCapMonthly).toBe(null);
          expect(m.realShock.waitingWeek).toBe(false);
          expect(m.realShock.pensionAware).toBe(false);
        }
      }
    }
  });

  it('grey-zone note only on the plain EI 55% card', () => {
    const inZone = accounts.filter((a) => {
      const m = applyShock(a, LAID_OFF_EI).months;
      return m !== null && m >= 6 && m < 12;
    });
    expect(inZone.length).toBeGreaterThan(100);
    for (const a of inZone.slice(0, 50)) {
      expect(at(a.id).greyNote).not.toBe(null);
      expect(at(a.id, { levers: { ...CARD_LEVERS.ei, incomePct: 60 } }).greyNote).toBe(null);
    }
  });
});
