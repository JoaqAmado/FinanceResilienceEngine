/**
 * The chat: one message in, the lever state out. Mirrors app.py's send(): parse (golden table, then the offline
 * rules), write every lever, keep the reply. The chat never computes a number; the engine does, from the levers.
 */
import type { Account } from '../engine';
import type { ChatLast } from '../engine/consistency';
import { followUpHints, parseShock, shockFromState, shockToState } from '../engine/shock_parser';
import type { AccountIndex, Source } from '../engine/shock_parser';
import type { Scenario } from './scenario';
import type { Action } from './state';

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  /** the reply is a question: nothing changed */
  clarify?: boolean;
  resolved?: string[];
  warnings?: string[];
  source?: Source;
  hints?: string[];
}

export interface ChatState {
  messages: ChatMessage[];
  /** the most recently set percent lever, for "make it 20% instead" */
  pctLever: string | null;
  /** what the last understood message set, to check it is still what the engine runs */
  last: ChatLast | null;
}

export const EMPTY_CHAT: ChatState = { messages: [], pctLever: null, last: null };

/** How many messages the history shows. */
export const SHOWN_MESSAGES = 10;

export const SOURCE_BADGE: Record<Source, string> = { golden: 'golden phrase', rules: 'offline rules', none: 'not parsed' };

/** One message: the new chat state, and the action that writes the levers (null when the reply is a question). */
export function send(text: string, scenario: Scenario, acct: Account, index: AccountIndex, chat: ChatState):
  { chat: ChatState; action: Action | null } {
  const msg = text.trim();
  if (!msg) return { chat, action: null };
  const current = shockFromState(scenario.levers, scenario.toggles, acct);
  const res = parseShock(msg, acct, current, scenario.target, index, chat.pctLever);
  const user: ChatMessage = { role: 'user', text: msg };
  if (res.clarify !== null) {
    const reply: ChatMessage = { role: 'assistant', text: res.clarify, clarify: true, source: res.source,
      warnings: res.warnings, resolved: [], hints: [] };
    return { chat: { ...chat, messages: [...chat.messages, user, reply] }, action: null };
  }
  const id = res.accountId ?? acct.id;
  const shown = res.accountId !== null ? (index.get(res.accountId) as Account) : acct;
  const { levers, toggles } = shockToState(res.shock);
  const reply: ChatMessage = { role: 'assistant', text: res.understoodAs, source: res.source, resolved: res.resolved,
    warnings: res.warnings, hints: followUpHints(res, shown) };
  const last: ChatLast = { shock: res.shock, levers, toggles, target: res.target, accountId: id,
    understoodAs: res.understoodAs };
  return {
    chat: { messages: [...chat.messages, user, reply], pctLever: res.pctLever, last },
    action: { type: 'apply', levers, toggles, target: res.target, id: res.accountId ?? undefined },
  };
}

/** One example per lever and per edit command, for the "What can I type?" box. */
export const EXAMPLES: readonly [string, string][] = [
  ['Job loss on EI', 'Laid off, EI pays 55%'],
  ['Pay cut / reduced hours', 'Pay cut 20%'],
  ['Income in dollars', 'Income drops to $2,000 a month'],
  ["Partner's job", 'Partner loses their job'],
  ['Household bills', 'Bills up 15%'],
  ['Rent / new monthly cost', 'Rent up $300 a month · baby, $900 a month more'],
  ['Rent to an amount', 'Rent goes to $1,800 a month'],
  ['One-off in dollars', 'A $2,500 car repair'],
  ['One-off in months of spending', 'Furnace dies, repair = a month of spending'],
  ['Spending cut', 'Cut spending 25%'],
  ['Target', 'Must last 9 months'],
  ['Another customer', 'Account 20143'],
  ['Reality checks', 'With the 2026 EI cap · waiting week · keep pension · half-year spending · bills by standing order'],
  ['Change the last percent', 'Make it 20% instead'],
  ['Add to the one-off', 'Add a $2,000 repair'],
  ['Undo one lever', 'Remove the bills increase · no job loss'],
  ['Start again', 'Reset'],
];
