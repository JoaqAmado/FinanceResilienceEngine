/**
 * The chat shock parser in TypeScript must give exactly what the Python parser gives (test/shock_vectors.json,
 * written by scripts/export_shock_vectors.py): every Shock, target, label, resolved line, warning, question and
 * hint, for every golden and practice phrase and a set of edge cases, on 7 accounts and 4 starting shocks, plus
 * multi-step conversations that exercise the edits.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  DOUBLE_WHAMMY,
  EI_2026_MAX_MONTHLY,
  FURNACE,
  LAID_OFF_EI,
  decodeAccounts,
  makeShock,
  withShock,
} from '../src/engine';
import type { Account, AccountsFile, Shock } from '../src/engine';
import {
  HINT_CHIPS,
  SUGGESTIONS,
  coercePct,
  describeShock,
  followUpHints,
  normalize,
  parseMoney,
  parseShock,
  ruleIntent,
  sameShock,
  shockFromState,
  shockToState,
} from '../src/engine/shock_parser';
import type { AccountIndex, ParseResult } from '../src/engine/shock_parser';

const read = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const V = read('./shock_vectors.json');
const accounts = decodeAccounts(read('../public/data/accounts.json') as AccountsFile);
const byId = new Map<number, Account>(accounts.map((a) => [a.id, a]));
const ids = accounts.map((a) => a.id);
const index: AccountIndex = { get: (id) => byId.get(id), minId: Math.min(...ids), maxId: Math.max(...ids) };

const CURRENTS: Record<string, Shock> = {
  none: makeShock(),
  ei: withShock(LAID_OFF_EI, { name: 'Laid off: EI 55%' }),
  double_cap: withShock(DOUBLE_WHAMMY, { incomeCapMonthly: EI_2026_MAX_MONTHLY, oneOffCost: 900, flexibleCutPct: 0.1 }),
  furnace: FURNACE,
};

const PY_STATE: Record<string, string> = {
  incomePct: 'income_pct', jobLoss: 'job_loss', billsPct: 'bills_pct', extra: 'extra', oneOffX: 'oneoff_x',
  oneOffAmt: 'oneoff_amt', cutPct: 'cut_pct',
};

function view(res: ParseResult, acct: Account) {
  let state: Record<string, unknown> | null = null;
  if (!res.clarify) {
    const { levers, toggles } = shockToState(res.shock);
    state = Object.fromEntries(Object.entries(PY_STATE).map(([k, p]) => [p, levers[k as keyof typeof levers]]));
    state.oneoff_mode = levers.oneOffMode === 'x' ? '× typical spending' : '$ amount';
    state.target = res.target;
    Object.assign(state, { t_cap: toggles.cap, t_ww: toggles.ww, t_pens: toggles.pens, t_s6: toggles.s6,
      t_bfb: toggles.bfb });
  }
  return {
    shock: res.shock, target: res.target, accountId: res.accountId, source: res.source,
    understoodAs: res.understoodAs, resolved: res.resolved, warnings: res.warnings, clarify: res.clarify,
    pctLever: res.pctLever, intent: res.intent, hints: res.clarify ? null : followUpHints(res, acct), state,
  };
}

describe('chat shock parser: TypeScript = Python', () => {
  it('has the same chips and suggestions', () => {
    expect([...HINT_CHIPS]).toEqual(V.hint_chips);
    expect([...SUGGESTIONS]).toEqual(V.suggestions);
  });

  it('normalizes every message the same way', () => {
    for (const [msg, want] of V.normalize) expect(normalize(msg), msg).toBe(want);
  });

  it('coerces percents and parses money the same way', () => {
    for (const [x, want] of V.coerce_pct) {
      if (want === null) expect(() => coercePct(x), String(x)).toThrow();
      else expect(coercePct(x), String(x)).toBe(want);
    }
    for (const [x, want] of V.parse_money) {
      if (want === null) expect(() => parseMoney(x), String(x)).toThrow();
      else expect(parseMoney(x), String(x)).toBe(want);
    }
  });

  it('the rules read every message into the same intent', () => {
    for (const [msg, want] of V.rules) expect(ruleIntent(msg), msg).toEqual(want);
  });

  it(`gives the same result for all ${V.parse.length} parses`, () => {
    for (const c of V.parse) {
      const acct = byId.get(c.acct) as Account;
      const res = parseShock(c.msg, acct, CURRENTS[c.current], c.target, index, c.lever);
      const shown = byId.get(res.accountId ?? c.acct) as Account;
      expect(view(res, shown), `${c.msg} | ${c.acct} | ${c.current}`).toEqual(c.result);
    }
  });

  it('follows every multi-step conversation the same way', () => {
    for (const c of V.conversations) {
      let current = makeShock();
      let target = 6;
      let lever: string | null = null;
      let a = c.acct as number;
      c.msgs.forEach((msg: string, i: number) => {
        const res = parseShock(msg, byId.get(a) as Account, current, target, index, lever);
        if (res.clarify === null) {
          [current, target, lever] = [res.shock, res.target, res.pctLever];
          a = res.accountId ?? a;
        }
        expect(view(res, byId.get(a) as Account), `${c.acct}: ${c.msgs.slice(0, i + 1).join(' → ')}`).toEqual(c.steps[i]);
      });
    }
  });

  it('describes every shock the same way, with and without an account', () => {
    for (const d of V.describe) {
      const acct = d.acct === null ? null : (byId.get(d.acct) as Account);
      expect(describeShock(makeShock(d.shock), acct, d.target), JSON.stringify(d.shock)).toBe(d.text);
    }
  });
});

describe('chat state', () => {
  it('a parsed shock and the levers it writes are the same Shock', () => {
    const acct = byId.get(98952) as Account;
    for (const msg of ['Income drops to $2,000 a month', 'laid off, keep pension, half-year spending',
      'a $2,500 repair', 'Furnace dies', 'cut spending 25% and bills up 12.5%', 'reset']) {
      const res = parseShock(msg, acct, makeShock(), 6, index);
      const { levers, toggles } = shockToState(res.shock);
      expect(shockFromState(levers, toggles, acct), msg).toEqual(res.shock);
      expect(sameShock(shockFromState(levers, toggles, acct), res.shock)).toBe(true);
    }
  });

  it('ten identical calls give identical results', () => {
    const acct = byId.get(20331) as Account;
    const first = parseShock('income down to 2k/mo and a 3k car repair', acct, LAID_OFF_EI, 6, index);
    for (let i = 0; i < 10; i++) {
      expect(parseShock('income down to 2k/mo and a 3k car repair', acct, LAID_OFF_EI, 6, index)).toEqual(first);
    }
  });
});
