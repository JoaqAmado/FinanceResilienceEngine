/** Scenario reducer for the whole app (the live twist and the tab that is open). */
import { CARD_LEVERS, DEFAULT_SCENARIO, NO_TOGGLES } from './scenario';
import type { CardId, Levers, Scenario, Tab, Toggles } from './scenario';

export type Action =
  | { type: 'open'; id: number; card?: CardId; tab?: Tab }
  | { type: 'card'; card: CardId }
  | { type: 'levers'; patch: Partial<Levers> }
  | { type: 'reset' }
  | { type: 'target'; n: number }
  | { type: 'toggle'; key: keyof Toggles; on: boolean }
  | { type: 'tab'; tab: Tab }
  | { type: 'replace'; scenario: Scenario };

export function reducer(st: Scenario, a: Action): Scenario {
  switch (a.type) {
    case 'open': {
      // re-opening the account already on screen (its chip, or its id typed again) keeps the twist
      if (a.id === st.id && !a.card) return { ...st, tab: a.tab ?? st.tab };
      // a new customer starts from the selected card's own values (app.py pick)
      const card = a.card ?? st.card;
      // a new customer also starts with the default target and every reality check off
      return { ...st, id: a.id, card, levers: CARD_LEVERS[card], target: DEFAULT_SCENARIO.target,
               toggles: NO_TOGGLES, tab: a.tab ?? st.tab };
    }
    case 'card':
      // switching card resets every lever to that card
      return { ...st, card: a.card, levers: CARD_LEVERS[a.card], target: DEFAULT_SCENARIO.target,
               toggles: NO_TOGGLES, tab: 'live' };
    case 'levers':
      return { ...st, levers: { ...st.levers, ...a.patch } };
    case 'reset':
      return { ...st, levers: CARD_LEVERS[st.card], target: DEFAULT_SCENARIO.target, toggles: NO_TOGGLES };
    case 'target':
      return { ...st, target: a.n };
    case 'toggle':
      return { ...st, toggles: { ...st.toggles, [a.key]: a.on } };
    case 'tab':
      return { ...st, tab: a.tab };
    case 'replace':
      return a.scenario;
  }
}
