/**
 * The chat on the live twist: messages write the same levers the Fine-tune sliders show, the engine computes every
 * number from them, and checkView (port of resilience/consistency.py) finds no disagreement on any screen.
 */
import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ChatPanel } from '../src/components/ChatPanel';
import { screenIssues } from '../src/components/Live';
import { FURNACE, README_TWISTS, applyShock, decodeAccounts, withShock } from '../src/engine';
import type { Account, AccountsFile } from '../src/engine';
import { checkView } from '../src/engine/consistency';
import { HINT_CHIPS, describeShock } from '../src/engine/shock_parser';
import type { AccountIndex } from '../src/engine/shock_parser';
import { EMPTY_CHAT, SHOWN_MESSAGES, send } from '../src/lib/chat';
import type { ChatState } from '../src/lib/chat';
import { rwText } from '../src/lib/format';
import { buildLive } from '../src/lib/live';
import { DEFAULT_SCENARIO } from '../src/lib/scenario';
import type { Scenario } from '../src/lib/scenario';
import { reducer } from '../src/lib/state';

const read = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const accounts = decodeAccounts(read('../public/data/accounts.json') as AccountsFile);
const byId = new Map<number, Account>(accounts.map((a) => [a.id, a]));
const ids = accounts.map((a) => a.id);
const index: AccountIndex = { get: (id) => byId.get(id), minId: Math.min(...ids), maxId: Math.max(...ids) };

/** A tiny session: type messages one after another, as the Live screen does. */
function session(id = DEFAULT_SCENARIO.id) {
  let scn: Scenario = { ...DEFAULT_SCENARIO, id };
  let chat: ChatState = EMPTY_CHAT;
  return {
    type(...msgs: string[]) {
      for (const m of msgs) {
        const out = send(m, scn, byId.get(scn.id) as Account, index, chat);
        chat = out.chat;
        if (out.action) scn = reducer(scn, out.action);
      }
      return this;
    },
    nudge(patch: Partial<Scenario['levers']>) {
      scn = reducer(scn, { type: 'levers', patch });
      return this;
    },
    get scn() { return scn; },
    get chat() { return chat; },
    get model() { return buildLive(byId.get(scn.id) as Account, scn); },
    issues() { return screenIssues(byId.get(scn.id) as Account, scn, this.model, chat); },
  };
}

const REHEARSAL = [20331, 20143, 88269, 98952, 77743];
const EDGE = [32078, 20578, 26939, 20303, 20866, 21903, 75489, 91609, 99477, 55819];
const MESSAGES = [
  'Laid off: EI at 55% of usual income', 'Furnace dies: repair = 1 month of typical spending',
  'Job loss (EI 55%) + household bills +15%', 'job loss, bills up 15% and two months of spending one-off',
  'partner loses their job and cut spending 25%', 'pay cut 30% for 9 months', 'Income drops to $2,000 a month',
  'rent goes to $1,800 a month', 'laid off and a $2,500 repair', 'laid off with the 2026 EI cap',
  'laid off, waiting week, 2026 EI cap', 'job loss on EI, keep pension', 'on EI, half-year spending',
  'bills by standing order, bills up 20%', 'rent up $300 a month and must last 12 months',
];

describe('chat -> levers -> engine', () => {
  it('each README twist by chat gives the engine runway, the same as the levers', () => {
    for (const id of REHEARSAL) {
      for (const twist of README_TWISTS) {
        const s = session(id).type('reset', twist.name);
        expect(rwText(s.model.judge), `${id} ${twist.name}`).toBe(rwText(applyShock(byId.get(id) as Account, twist)));
      }
    }
  });

  it('every hint chip is understood, and the chips build on each other', () => {
    const s = session(20331);
    for (const chip of HINT_CHIPS) {
      s.type(chip);
      const last = s.chat.messages[s.chat.messages.length - 1];
      expect(last.clarify, chip).toBeUndefined();
      expect(last.source).toBe('golden');
    }
    expect(s.scn.target).toBe(9);
    expect(s.scn.levers.extra).toBe(300);
    expect(s.issues()).toEqual([]);
  });

  it('a chat message then a slider nudge stays one consistent state', () => {
    const s = session(20331).type('reset', 'job loss on EI and bills up 15%');
    expect([s.scn.levers.billsPct, s.scn.levers.jobLoss]).toEqual([15, true]);
    s.nudge({ billsPct: 25 });
    expect(describeShock(s.model.realShock, byId.get(20331) as Account, 6)).toContain('household bills +25%');
    expect(s.issues()).toEqual([]);
    s.type('make it 10% instead');
    expect(s.scn.levers.billsPct).toBe(10);
    expect(s.issues()).toEqual([]);
  });

  it('account-relative dollars are resolved for the customer on screen', () => {
    const s = session(98952).type('reset', 'Income drops to $2,000 a month');
    expect(s.scn.levers.incomePct).toBeCloseTo((2000 / 3915.2) * 100, 3);
    const reply = s.chat.messages[s.chat.messages.length - 1];
    expect(reply.text.startsWith('Income drops to $2,000/mo (51.1% of your usual $3,915)')).toBe(true);
    expect(reply.resolved).toEqual(['income $2,000/mo ÷ usual $3,915/mo = 51.1% of money in']);
  });

  it('the chat can switch account and keeps the shock', () => {
    const s = session(77743).type('account 98952, keep the pension');
    expect(s.scn.id).toBe(98952);
    expect(s.scn.levers.oneOffX).toBe(1);   // the furnace twist the page opened with
    expect(s.issues()).toEqual([]);
  });

  it('unparseable input leaves the state unchanged and asks', () => {
    for (const msg of ["what's the weather like?", 'account 12345', 'make it 20% instead']) {
      const s = session(20331).type('Income drops to $2,000 a month');
      const before = s.scn;
      s.type(msg);
      expect(s.scn, msg).toEqual(before);
      expect(s.chat.messages[s.chat.messages.length - 1].clarify).toBe(true);
    }
  });
});

describe('every number on screen agrees (checkView)', () => {
  it(`no issues on rehearsal, edge and 200 sampled accounts for ${MESSAGES.length} shocks`, () => {
    const named = new Set([...REHEARSAL, ...EDGE]);
    const sample = ids.filter((id, i) => i % 20 === 0 && !named.has(id)).slice(0, 200);
    const all = [...new Set([...REHEARSAL, ...EDGE, ...sample])];
    expect(all.length).toBeGreaterThanOrEqual(215);
    const bad: string[] = [];
    for (const id of all) {
      for (const msg of MESSAGES) {
        const s = session(id).type('reset', msg);
        const issues = s.issues();
        if (issues.length) bad.push(`${id} ${msg}: ${issues.map((i) => i.detail).join('; ')}`);
      }
    }
    expect(bad.slice(0, 5)).toEqual([]);
  });

  it('a corrupted value is caught', () => {
    const acct = byId.get(20331) as Account;
    const s = session(20331).type('reset', 'Laid off: EI at 55% of usual income');
    const m = s.model;
    const base = { accountId: 20331, levers: s.scn.levers, toggles: s.scn.toggles };
    const caught = (extra: object, prefix: string) => {
      const issues = checkView(acct, m.realShock, 6, { ...base, ...extra });
      expect(issues.some((i) => i.check.startsWith(prefix)), JSON.stringify(issues)).toBe(true);
    };
    caught({ card: { B: acct.B + 1 } }, '2 ');
    caught({ judgeText: '9.9 mo' }, '3 ');
    caught({ verdict: 'survives' }, '3 ');
    caught({ judgePath: [100, 50, -1] }, '4 ');
    const lad = m.ladder;
    const i = lad.firstSufficient as number;
    expect(i).toBeGreaterThan(0);
    caught({ ladder: { ...lad, firstSufficient: i - 1,
      rungs: lad.rungs.map((r, k) => ({ ...r, reachesTarget: r.reachesTarget || k === i - 1 })) } }, '5 ');
    caught({ story: { ...m.story, headline: `${m.story.headline} 7,777` }, facts: m.facts }, '7 ');
    caught({ flags: ['no_income'] }, '9 ');
    caught({ levers: { ...s.scn.levers, billsPct: 20 } }, '1 ');
    expect(checkView(acct, withShock(FURNACE, { incomeCapMonthly: 3159 }), 6, { accountId: 20331 })
      .some((x) => x.check.startsWith('6 '))).toBe(true);
  });
});

describe('chat panel', () => {
  it('shows the current shock, the chips, a closed "What can I type?", the badge, and the last 10 messages', () => {
    const s = session(20331);
    for (let i = 0; i < 7; i++) s.type(`must last ${i + 2} months`);
    const html = renderToStaticMarkup(createElement(ChatPanel, {
      chat: s.chat, understoodAs: 'Laid off, EI pays 55%', issues: [], onSend: () => {},
    }));
    for (const chip of HINT_CHIPS) expect(html).toContain(chip);
    expect(html).toContain('<strong>Current shock:</strong> Laid off, EI pays 55%');
    expect(html).toContain('✓ All numbers consistent');
    expect(html).toMatch(/<details[^>]*><summary>What can I type\?<\/summary>/);
    expect(html).not.toMatch(/<details[^>]*open/);
    expect(s.chat.messages.length).toBe(14);
    expect((html.match(/<li /g) ?? []).length).toBe(SHOWN_MESSAGES);
    expect(html).not.toContain('Gemini');
    const bad = renderToStaticMarkup(createElement(ChatPanel, {
      chat: EMPTY_CHAT, understoodAs: 'x', issues: [{ check: '3 runway -> formula', detail: 'off by one' }],
      onSend: () => {},
    }));
    expect(bad).toContain('Numbers disagree');
    expect(bad).toContain('3 runway -&gt; formula: off by one');
  });
});
