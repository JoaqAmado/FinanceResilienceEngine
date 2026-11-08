/** Scenario reducer for the whole app (the live twist and the tab that is open). */
import { DEFAULT_SCENARIO, NO_SHOCK, NO_TOGGLES } from './scenario';
import type { Levers, Scenario, Tab, Toggles } from './scenario';

export type Action =
  | { type: 'open'; id: number; tab?: Tab }
  | { type: 'levers'; patch: Partial<Levers> }
  | { type: 'reset' }
  | { type: 'target'; n: number }
  | { type: 'toggle'; key: keyof Toggles; on: boolean }
  | { type: 'tab'; tab: Tab }
  /** a chat message was understood: it sets every lever (and may name another account) */
  | { type: 'apply'; levers: Levers; toggles: Toggles; target: number; id?: number }
  | { type: 'replace'; scenario: Scenario };

export function reducer(st: Scenario, a: Action): Scenario {
  switch (a.type) {
    case 'open':
      // a new customer keeps the current shock (app.py: switching account keeps the twist)
      return { ...st, id: a.id, tab: a.tab ?? st.tab };
    case 'levers':
      return { ...st, levers: { ...st.levers, ...a.patch } };
    case 'reset':
      return { ...st, levers: NO_SHOCK, target: DEFAULT_SCENARIO.target, toggles: NO_TOGGLES };
    case 'target':
      return { ...st, target: a.n };
    case 'toggle':
      return { ...st, toggles: { ...st.toggles, [a.key]: a.on } };
    case 'tab':
      return { ...st, tab: a.tab };
    case 'apply':
      return { ...st, id: a.id ?? st.id, levers: a.levers, toggles: a.toggles, target: a.target, tab: 'live' };
    case 'replace':
      return a.scenario;
  }
}
