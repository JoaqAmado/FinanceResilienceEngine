/**
 * UI-side guarantees on top of the engine parity suite:
 *   - the README twists' lever values mean exactly the engine presets (and app.py's twist labels)
 *   - the January balance series crosses $0 exactly where calendarPath() says
 *   - the hero number's Intl formatting (NumberFlow) prints the same digits as Python's :.1f
 *   - the portfolio drill-down bands reproduce resilience/portfolio.py's table
 *   - a scenario survives the URL-hash round trip
 *   - the early-warning light renders on the customer card (server-rendered markup)
 *   - the Portfolio tab shows the 2025 backtest evidence first, with the lines Python writes
 *   - chart axis labels follow the rem scale and every chart is named (review fixes)
 */
import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { CustomerCard } from '../src/components/CustomerCard';
import { EarlyWarningLight } from '../src/components/EarlyWarningLight';
import { JudgesPanel } from '../src/components/JudgesPanel';
import { Levers } from '../src/components/Levers';
import { Portfolio } from '../src/components/Portfolio';
import { RealityPanel } from '../src/components/RealityPanel';
import {
  BASELINE,
  FURNACE,
  LAID_OFF_EI,
  DOUBLE_WHAMMY,
  PRESETS,
  applyShock,
  calendarPath,
  computeLight,
  decodeAccounts,
  decodeBacktest,
  evidenceLines,
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
  DEFAULT_SCENARIO,
  FURNACE_LEVERS,
  NO_SHOCK,
  NO_TOGGLES,
  decodeScenario,
  encodeScenario,
  shockFromLevers,
  twistLabel,
} from '../src/lib/scenario';
import type { Scenario } from '../src/lib/scenario';
import { reducer } from '../src/lib/state';

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

/** The levers of the three README twists and of no shock (what the chat's golden phrases write). */
const L = {
  ei: { ...NO_SHOCK, incomePct: 55, jobLoss: true },
  furnace: FURNACE_LEVERS,
  double: { ...NO_SHOCK, incomePct: 55, jobLoss: true, billsPct: 15 },
  custom: NO_SHOCK,
};

describe('twist levers', () => {
  it("each README twist's levers apply exactly its engine preset, named as app.py names it", () => {
    for (const [k, name] of [['ei', 'Laid off: EI 55%'], ['furnace', 'Furnace dies: 1× spending'],
      ['double', 'Job loss + bills +15%']] as const) {
      const got = shockFromLevers(L[k]);
      for (const f of SHOCK_FIELDS) expect(got[f], `${k}.${f}`).toBe(PRESETS[name][f]);
    }
    expect(shockFromLevers(L.custom).name).toBe('No shock');
  });

  it('the presets are the README twists the vectors were exported for', () => {
    const same = (a: Shock, b: Shock) => SHOCK_FIELDS.filter((k) => k !== 'name').every((k) => a[k] === b[k]);
    expect(same(PRESETS['Laid off: EI 55%'], LAID_OFF_EI)).toBe(true);
    expect(same(PRESETS['Furnace dies: 1× spending'], FURNACE)).toBe(true);
    expect(same(PRESETS['Job loss + bills +15%'], DOUBLE_WHAMMY)).toBe(true);
  });

  it('twist labels follow app.py (shock_parser.describe_shock)', () => {
    const custom = L.custom;
    expect(twistLabel(custom)).toBe('No shock');
    expect(twistLabel({ ...custom, incomePct: 70, extra: 400 })).toBe('Income kept 70%, +$400/mo');
    expect(twistLabel({ ...L.ei, incomePct: 60 })).toBe('Laid off, EI pays 60%');
    expect(twistLabel({ ...L.double, billsPct: 20 })).toBe('Laid off, EI pays 55%, household bills +20%');
    expect(twistLabel({ ...L.furnace, oneOffX: 1.5 })).toBe('One-off 1.5× spending');
    expect(twistLabel({ ...L.furnace, oneOffMode: 'amt', oneOffAmt: 12500 })).toBe('One-off $12,500');
    expect(twistLabel({ ...custom, cutPct: 25 })).toBe('Non-fixed spending cut 25%');
    // the inactive one-off input doesn't count: switching mode with $0 is no shock
    expect(twistLabel({ ...custom, oneOffMode: 'amt', oneOffX: 2 })).toBe('No shock');
    // the job-loss box only counts while income is below 100%
    expect(shockFromLevers({ ...custom, jobLoss: true }).jobLoss).toBe(false);
    expect(twistLabel({ ...L.ei, jobLoss: false })).toBe('Income kept 55%');
  });

  it('a lever-built shock equals the engine shock with the same fractions', () => {
    const s = shockFromLevers({ ...L.custom, incomePct: 57.5, billsPct: 15, jobLoss: true });
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
      shockFromLevers({ ...L.custom, incomePct: i * 5, jobLoss: true, billsPct: i % 4 * 5, oneOffX: (i % 3) * 0.25 }),
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
      // the dollar cushion beside the months (pandas median: the mean of the two middle values)
      const median = (xs: number[]) => {
        const s = [...xs].sort((x, y) => x - y);
        const m = s.length >> 1;
        return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
      };
      expect(npRound(median(band.map((r) => r.B)), 0)).toBe(want.median_B);
      expect(npRound(median(band.map((r) => r.S)), 0)).toBe(want.median_S);
    });
    expect([portfolio.income_bands[0].median_B, portfolio.income_bands[0].median_S]).toEqual([13943, 1433]);
    expect([portfolio.income_bands[6].median_B, portfolio.income_bands[6].median_S]).toEqual([38869, 22952]);
    expect(rows.filter((r) => failsSix(r.ei)).length).toBe(portfolio.headlines.fail_6mo_ei55);
    expect(rows.filter((r) => failsSix(r.cap)).length).toBe(portfolio.headlines.fail_6mo_ei55_cap2026);
  });
});

describe('scenario state', () => {
  it('round-trips through the URL hash', () => {
    const s: Scenario = {
      tab: 'portfolio',
      id: 20331,
      levers: { incomePct: 57.5, jobLoss: true, billsPct: 22, extra: 350, oneOffMode: 'amt', oneOffX: 0.75,
        oneOffAmt: 4200, cutPct: 12.5 },
      target: 9,
      toggles: { cap: true, ww: false, pens: true, s6: true, bfb: false },
    };
    expect(decodeScenario(`#${encodeScenario(s)}`)).toEqual(s);
    expect(decodeScenario(encodeScenario(DEFAULT_SCENARIO))).toEqual(DEFAULT_SCENARIO);
  });

  it('a link from before the chat (a twist card, no levers) opens that card', () => {
    expect(decodeScenario('#id=20331&card=double').levers).toEqual(L.double);
    expect(decodeScenario('#id=20331&card=ei').levers).toEqual(L.ei);
    expect(decodeScenario('#id=20331&card=custom').levers).toEqual(L.custom);
  });

  it('another account keeps the twist; a chat message sets every lever; reset goes back to no shock', () => {
    const edited: Scenario = { ...DEFAULT_SCENARIO, id: 20143, levers: { ...L.double, billsPct: 40 }, target: 9,
      toggles: { ...DEFAULT_SCENARIO.toggles, cap: true } };
    expect(reducer(edited, { type: 'open', id: 20143 })).toEqual(edited);
    expect(reducer(edited, { type: 'open', id: 20331 })).toEqual({ ...edited, id: 20331 });
    const applied = reducer({ ...edited, tab: 'portfolio' }, { type: 'apply', id: 98952, levers: L.ei,
      toggles: { ...NO_TOGGLES, pens: true }, target: 12 });
    expect(applied).toEqual({ tab: 'live', id: 98952, levers: L.ei, toggles: { ...NO_TOGGLES, pens: true }, target: 12 });
    expect(reducer(edited, { type: 'reset' })).toEqual({ ...edited, levers: NO_SHOCK, target: 6, toggles: NO_TOGGLES });
  });

  it('falls back to safe values on junk', () => {
    const s = decodeScenario('#tab=nope&id=-4&card=zzz&inc=900&n=40&bills=abc');
    expect(s.tab).toBe('live');
    expect(s.id).toBe(DEFAULT_SCENARIO.id);
    expect(s.levers.incomePct).toBe(100);
    expect(s.target).toBe(24);
    expect(s.levers.billsPct).toBe(DEFAULT_SCENARIO.levers.billsPct);
  });
});

describe('live screen model', () => {
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const at = (id: number, patch: Partial<Scenario> = {}) =>
    buildLive(byId.get(id)!, { ...DEFAULT_SCENARIO, id, levers: L.ei, ...patch });

  it('rehearsal account numbers', () => {
    // rehearsal accounts
    expect(at(77743).judge.months).toBe(4.8);
    expect(at(77743, { levers: L.furnace }).judge.months).toBe(0);
    expect(at(20331).judge.months).toBe(5.1);
    expect(at(20143).judge.months).toBe(2.2);
    expect(at(88269).judge.months).toBe(11.3);
    expect(at(98952).judge.months).toBe(4.2);
    const pens = at(98952, { toggles: { cap: false, ww: false, pens: true, s6: false, bfb: false } });
    expect(pens.real.months).toBe(23.4);
    const cap = at(20331).checks.find((c) => c.key === 'cap')!;
    expect(cap.result.months).toBe(2.4);
  });

  it('the waiting week starts off and is labelled the normal rule, once the waiver ends', () => {
    expect(DEFAULT_SCENARIO.toggles.ww).toBe(false);
    const ww = at(20331).checks.find((c) => c.key === 'ww')!;
    expect(ww.on).toBe(false);
    expect(ww.label).toBe('EI waiting week: normal rule, once the waiver ends (waived until Oct 9, 2027, canada.ca)');
  });

  it('reality checks never change the judges number, and disabled checks never apply', () => {
    const allOn = { cap: true, ww: true, pens: true, s6: true, bfb: true };
    for (const a of accounts.slice(0, 400)) {
      for (const card of ['ei', 'furnace', 'custom'] as const) {
        const m = buildLive(a, { ...DEFAULT_SCENARIO, id: a.id, levers: L[card], toggles: allOn });
        const plain = buildLive(a, { ...DEFAULT_SCENARIO, id: a.id, levers: L[card] });
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

  it('screen readers hear the verdict and the reality-check runway, not just the judges number', () => {
    const live = (html: string) =>
      [...html.matchAll(/<span[^>]*aria-live="polite"[^>]*>(.*?)<\/span>/g)].map((x) => x[1].replace(/&#x27;/g, "'"));
    const acct = byId.get(88269)!;
    for (const [n, verdict] of [[6, 'SURVIVES 6 MONTHS'], [12, 'RUNS OUT IN 11.3 MONTHS (needs 12)']] as const) {
      const m = at(88269, { target: n });
      const html = renderToStaticMarkup(
        createElement(JudgesPanel, { acct, judge: m.judge, baseline: m.baseline, shock: m.judgeShock, target: n, greyNote: m.greyNote }),
      );
      expect(live(html)).toEqual([`Judges' runway: 11.3 mo. ${verdict}`]);
    }
    const pens = at(98952, { toggles: { cap: false, ww: false, pens: true, s6: false, bfb: false } });
    const html = renderToStaticMarkup(
      createElement(RealityPanel, {
        judge: pens.judge,
        real: pens.real,
        anyOn: pens.anyCheckOn,
        activeNames: pens.activeNames,
        checks: pens.checks,
        jan: pens.jan,
        onToggle: () => {},
      }),
    );
    expect(live(html)).toEqual(['Runway with the selected checks: 23.4 mo']);
  });

  it("the Income kept lever's EI hint shows only on a job loss, in money-in wording", () => {
    const hint = (levers: Scenario['levers']) => {
      const html = renderToStaticMarkup(
        createElement(Levers, { levers, target: 6, onLevers: () => {}, onTarget: () => {}, onReset: () => {} }),
      );
      return html.match(/<p id="lever-income-hint"[^>]*>(.*?)<\/p>/)?.[1] ?? null;
    };
    expect(hint(L.furnace)).toBe(null); // 100% kept, no job loss
    expect(hint({ ...L.custom, incomePct: 37 })).toBe(null); // a cut, but not a job loss
    expect(hint(L.ei)).toBe('EI pays 55% of usual money in');
    expect(hint(L.double)).toBe('EI pays 55% of usual money in');
  });

  it('grey-zone note only on the plain EI 55% twist', () => {
    const inZone = accounts.filter((a) => {
      const m = applyShock(a, LAID_OFF_EI).months;
      return m !== null && m >= 6 && m < 12;
    });
    expect(inZone.length).toBeGreaterThan(100);
    for (const a of inZone.slice(0, 50)) {
      expect(at(a.id).greyNote).not.toBe(null);
      expect(at(a.id, { levers: { ...L.ei, incomePct: 60 } }).greyNote).toBe(null);
    }
  });
});

describe('early-warning light on the customer card', () => {
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const bt = decodeBacktest(portfolio.early_warning);
  const unescape = (h: string) =>
    h.replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  const text = (h: string) => unescape(h.replace(/<[^>]+>/g, ''));
  const card = (id: number) => {
    const acct = byId.get(id)!;
    return renderToStaticMarkup(createElement(CustomerCard, { acct, baseline: applyShock(acct, BASELINE), earlyWarning: bt }));
  };
  /** the flag-style line, without its aria-hidden points icon */
  const line = (html: string) => {
    const m = html.match(/<p[^>]*data-testid="early-warning-line"[^>]*>(.*?)<\/p>/);
    expect(m, 'early-warning line rendered').not.toBe(null);
    return text(m![1].replace(/^<span[^>]*aria-hidden="true"[^>]*>.*?<\/span>/, ''));
  };
  const column = (html: string, table: number, col: number) =>
    [...html.matchAll(/<table>(.*?)<\/table>/g)][table][1]
      .split('<tbody>')[1]
      .split('</tr>')
      .filter((r) => r.includes('<td'))
      .map((r) => text(r.split(/<t[hd][^>]*>/)[col + 1]));

  it('77743 (the default account): 3/4, the three rules that fired, the 3-point backtest line', () => {
    const html = card(77743);
    // the same sentence tests/test_app.py pins on the Streamlit card
    expect(line(html)).toBe(
      'Early-warning light 3/4: lowest balance under half a month of spending; almost all spending is cash; ' +
        'irregular money in. In the 2025 backtest, 15 of 146 accounts with 3 points went overdrawn (10.3%).',
    );
    expect(column(html, 0, 1)).toEqual(['0.04 months of spending', '99.9% of spending', '1.13', '+0.49 months of spending per month']);
    expect(column(html, 0, 3)).toEqual(['! fired', '! fired', '! fired', 'not fired']);
    expect(column(html, 1, 1)).toEqual(['2,390', '833', '463', '146', '15']);
    expect(column(html, 1, 2)).toEqual(['2', '18', '33', '15', '7']);
    expect(column(html, 1, 3)).toEqual(['0.08%', '2.2%', '7.1%', '10.3%', '46.7%']);
    expect(text(html)).toContain('3 this account');
    expect([...html.matchAll(/aria-current="true"/g)].length).toBe(1);
    const caption = text(html.match(/<p class="[^"]*caption[^"]*">(.*?)<\/p>/)?.[1] ?? html);
    // the backtest needed 6 months after the opening month (7+ counting it), as app.py's caption says
    expect(caption).toContain('on the 3,847 accounts with 6+ months after the opening month that had never gone below zero');
    expect(caption).not.toContain('months of history');
    expect(caption).toContain('75 of them went overdrawn in 2025');
    // the light sits after the warning flags and before the month history
    expect(html.indexOf('Read these first')).toBeLessThan(html.indexOf('early-warning-line'));
    expect(html.indexOf('early-warning-line')).toBeLessThan(html.indexOf('Loading month history'));
  });

  it('20331 (rehearsal account): already overdrawn, points and rules but no backtest rate', () => {
    const html = card(20331);
    const l = line(html);
    expect(l.startsWith('Early-warning light 2/4: lowest balance under half a month of spending; irregular money in. ')).toBe(true);
    expect(l).toContain('Already overdrawn before');
    expect(l).not.toContain('In the 2025 backtest');
    expect(html).not.toContain('aria-current'); // no tier row is marked as this account's
    // the judges' number is untouched
    const live = buildLive(byId.get(20331)!, { ...DEFAULT_SCENARIO, id: 20331, levers: L.ei });
    expect(live.judge.months).toBe(5.1);
  });

  it('not enough history: no points, no rule table, no rate', () => {
    const raw = { min_bal_over_S: 0.1, cash_share: 1, inc_cv: 2, bal_trend: -1 };
    const light = computeLight(1, { rowsUsed: 5, daysBelowZero: 0, recentSpending: 100, lastMonth: bt.today, raw }, bt);
    const html = renderToStaticMarkup(createElement(EarlyWarningLight, { light, backtest: bt }));
    // the same sentence as app.py (tests/test_app.py pins it there): the card renders the engine's line
    const sentence =
      'Early-warning light: Not enough history: the light needs 6 months after the opening month and this ' +
      'account has 5, so no points or backtest rate.';
    expect(light.line).toBe(sentence);
    expect(line(html)).toBe(light.line);
    expect([...html.matchAll(/<table>/g)].length).toBe(1); // only the tier table
    expect(html).not.toContain('early-warning-spending');
  });

  it('99477 (activity stops 2024-03): points from its last 6 months, no backtest rate', () => {
    const html = card(99477);
    expect(text(html)).toContain('Account activity stops in 2024-03: the buffer may be out of date.');
    expect(line(html)).toBe(
      'Early-warning light 3/4: almost all spending is cash; irregular money in; balance sliding more than 10% ' +
        "of a month's spending per month. Activity stops in 2024-03: the points are from the account's last 6 " +
        'months up to then, so no backtest rate is shown (the backtest only followed accounts that were still active).',
    );
    expect(html).not.toContain('aria-current'); // no tier row is marked as this account's
  });

  it("55819: the rules' month of spending is named and priced, beside the card's Buffer", () => {
    const html = card(55819);
    expect(text(html)).toContain('0.3 months of spending'); // the Buffer, on S
    expect(column(html, 0, 1)[0]).toBe('116.96 months of spending'); // rule 1, on the window's median money out
    const note = text(html.match(/<p[^>]*data-testid="early-warning-spending"[^>]*>(.*?)<\/p>/)?.[1] ?? '');
    expect(note).toBe(
      "In the lowest-balance and balance-trend rules, a month of spending is this account's median money out " +
        "over the same 6 months: $9.19. That is not the card's S (the median over all history), so these months " +
        "can differ from the Buffer's.",
    );
  });
});

describe('portfolio tab: 2025 backtest evidence', () => {
  const unescape = (h: string) =>
    h.replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  const data = {
    accounts,
    byId: new Map(accounts.map((a) => [a.id, a] as const)),
    ids: accounts.map((a) => a.id).sort((a, b) => a - b),
    portfolio,
    earlyWarning: decodeBacktest(portfolio.early_warning),
    loadMs: 0,
  };
  const html = renderToStaticMarkup(createElement(Portfolio, { data, onOpen: () => {} }));
  const text = unescape(html.replace(/<[^>]+>/g, ''));

  it('leads with the lift chart, then the 2x2, and shows every evidence line', () => {
    const heads = [...html.matchAll(/<h2[^>]*>(.*?)<\/h2>/g)].map((m) => unescape(m[1].replace(/<[^>]+>/g, '')));
    expect(heads.slice(0, 2)).toEqual([
      "1 · The judges' test misses people: who went overdrawn in 2025",
      '2 · A second finding: irregular money in',
    ]);
    expect(heads).toHaveLength(6);
    for (const [key, line] of Object.entries(evidenceLines(portfolio.evidence))) {
      expect(text, key).toContain(line);
    }
    // the same sentences tests/test_evidence.py pins on the Python side
    expect(text).toContain(
      'On a 10% watch-list (385 accounts), the light (most points first, then lowest balance against spending) ' +
        "catches 47 of the 75 accounts that went overdrawn in 2025; the judges' EI 55% runway catches 25 and buffer " +
        'months 29.',
    );
    expect(text).toContain('the light had flagged 17 of them (2+ points).');
    // review fixes: the 47 needs the balance tie-break, so the chart's series says so; the half-year check is
    // unrounded, so it is not credited to the judges
    expect(text).toContain('Early-warning light: most points, then lowest balance');
    expect(text).toContain('the same test on the median month S misses 2,406 and on half-year spending S6 misses 1,003');
    expect(text).not.toContain("judges' median month");
  });

  it('realistic cuts, dollar cushions and the reworded caveats, as Python writes them', () => {
    const L = portfolio.lines;
    // the quarter sentence the tab builds from cut_histogram is Python's, and the realistic-cut line sits beside it
    expect(text).toContain(`${L.quarter} ${L.realistic_cuts}`);
    expect(L.realistic_cuts).toBe(
      'Studies of people who lost a job find that by about 6 months out of work they have cut about 13–16% of ' +
        'spending. Held from the first month, a cut of 16% or less gets 778 of 1,555 (50.0%) back to 6 months and ' +
        '13% or less gets 606 (39.0%); a cut that builds up to those levels gets fewer back.',
    );
    expect(text).toContain(L.cushion);
    expect(L.cushion).toContain('the median buffer is $13.9k under $2.5k a month and $38.9k over $20k');
    expect(L.cushion).toContain('Median monthly spending grows faster ($1.4k → $23.0k)');
    for (const cell of ['$13,943', '$1,433', '$38,869', '$22,952']) expect(text).toContain(cell);
    expect(text).toContain('Spending is lumpy');
    expect(text).toContain('Calendar caveat: here spending peaks in January and June');
    expect(text).not.toContain('Spending peaks in January and June, which a median month never sees');
    expect(text).toContain(
      '27 of 27 borrowers who were overdrawn before their loan are labelled defaulted; none of the 606 who repaid ' +
        'or are on track was overdrawn before it. That is built into how this dataset labels loans',
    );
    const heads = [...html.matchAll(/<h2[^>]*>(.*?)<\/h2>/g)].map((m) => unescape(m[1].replace(/<[^>]+>/g, '')));
    expect(heads[5]).toBe('6 · Overdrawn before the loan: a red flag, built into the loan labels');
  });

  it('the 2x2 table and the numbers table carry every cell', () => {
    expect(text).toContain('14 of 376 · 3.7% (2.2–6.2%)');
    expect(text).toContain('17 of 1,072 · 1.6% (1.0–2.5%)');
    expect(text).toContain('47 of 75');
    expect([...html.matchAll(/<tr><th scope="row">\d+%<\/th>/g)]).toHaveLength(30);
  });
});

describe('charts: axis labels and names', () => {
  const src = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8');
  const charts = ['CustomerCard', 'BurnDown', 'Portfolio'].map((c) => [c, src(`../src/components/${c}.tsx`)] as const);

  it("the 0.78rem tick rule reaches Recharts 3.10's tick-label layer", () => {
    // Recharts 3.10 draws tick text under g.recharts-cartesian-axis-tick-label, outside .recharts-cartesian-axis-tick:
    // without this selector every tick label renders at 16px and long y labels lose their minus sign
    const rule = src('../src/styles/tokens.css').match(/([^{}]*)\{\s*font-size:\s*0\.78rem;\s*\}/);
    expect(rule?.[1]).toContain('.recharts-cartesian-axis-tick-label text');
  });

  it('y axes size to their labels, and stacked tick lines scale with the font', () => {
    for (const [name, code] of charts) {
      const axes = [...code.matchAll(/<YAxis\b[\s\S]*?\/>/g)].map((m) => m[0]);
      expect(axes.length, name).toBeGreaterThan(0);
      for (const a of axes) expect(a, name).toContain('width="auto"');
    }
    const portfolio = charts[2][1];
    expect(portfolio).not.toMatch(/<text[^>]*dy=\{\d+\}/); // px offsets don't grow in presenter mode
  });

  it('every chart has a title and a description (accessibility layer kept on)', () => {
    let n = 0;
    for (const [name, code] of charts) {
      for (const m of code.matchAll(/<(ComposedChart|LineChart|BarChart)\b([^>]*)>/gs)) {
        expect(m[2], `${name} ${m[1]}`).toMatch(/\btitle=/);
        expect(m[2], `${name} ${m[1]}`).toMatch(/\bdesc=/);
        expect(m[2], `${name} ${m[1]}`).not.toContain('accessibilityLayer={false}');
        n++;
      }
    }
    expect(n).toBe(7);
  });
});
