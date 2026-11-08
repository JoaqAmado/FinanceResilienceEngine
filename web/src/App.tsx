import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import s from './App.module.css';
import { Live } from './components/Live';
import { Method } from './components/Method';
import { Portfolio } from './components/Portfolio';
import { useAppData } from './lib/load';
import { CARDS, DEFAULT_ACCOUNT, decodeScenario, encodeScenario } from './lib/scenario';
import type { CardId, Tab } from './lib/scenario';
import { reducer } from './lib/state';

const TABS: { id: Tab; label: string }[] = [
  { id: 'live', label: 'Live twist' },
  { id: 'portfolio', label: 'Portfolio discoveries' },
  { id: 'method', label: 'Method & limits' },
];

function readPresenter(): boolean {
  try {
    return localStorage.getItem('twin-runway:presenter') === 'on';
  } catch {
    return false;
  }
}

/** Keys typed into a text field belong to the field, not to the shortcuts. */
function isTyping(t: EventTarget | null): boolean {
  if (t instanceof HTMLInputElement) return !['range', 'checkbox', 'radio', 'button'].includes(t.type);
  return t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement || (t instanceof HTMLElement && t.isContentEditable);
}

export function App() {
  const { data, error } = useAppData();
  const [scn, dispatch] = useReducer(reducer, undefined, () => decodeScenario(window.location.hash));
  const [presenter, setPresenter] = useState(readPresenter);
  const [copied, setCopied] = useState(false);
  const searchRef = useRef<HTMLInputElement | null>(null);

  // presenter mode scales the root font size; every size in the app is in rem
  useEffect(() => {
    document.documentElement.dataset.presenter = presenter ? 'on' : 'off';
    try {
      localStorage.setItem('twin-runway:presenter', presenter ? 'on' : 'off');
    } catch {
      /* private window: presenter mode just won't be remembered */
    }
  }, [presenter]);

  // the URL hash holds the scenario, so a reload or a shared link reopens the same twist
  useEffect(() => {
    const next = `#${encodeScenario(scn)}`;
    if (window.location.hash !== next) window.history.replaceState(null, '', next);
  }, [scn]);

  useEffect(() => {
    // replaceState never fires hashchange, so this only runs when someone edits or pastes the URL
    const onHash = () => dispatch({ type: 'replace', scenario: decodeScenario(window.location.hash) });
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // an id from the hash that isn't in the data falls back to the default account
  useEffect(() => {
    if (data && !data.byId.has(scn.id)) dispatch({ type: 'open', id: DEFAULT_ACCOUNT });
  }, [data, scn.id]);

  const focusSearch = useCallback(() => {
    dispatch({ type: 'tab', tab: 'live' });
    window.setTimeout(() => {
      searchRef.current?.focus();
      searchRef.current?.select();
    }, 0);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      if (e.key === '/') {
        e.preventDefault();
        focusSearch();
        return;
      }
      const card = CARDS.find((c) => c.key === e.key);
      if (card) {
        e.preventDefault();
        dispatch({ type: 'card', card: card.id });
        return;
      }
      if (e.key === 'r' || e.key === 'R') {
        dispatch({ type: 'reset' });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [focusSearch]);

  const copyLink = useCallback(() => {
    void navigator.clipboard?.writeText(window.location.href).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    });
  }, []);

  const openInLive = useCallback((id: number, card?: CardId) => {
    dispatch({ type: 'open', id, card, tab: 'live' });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  return (
    <div className={s.app}>
      <header className={s.header}>
        <div className={s.brand}>
          <span className={s.logo} aria-hidden="true" />
          <div>
            <h1 className={s.title}>Twin Runway</h1>
            <p className={s.tagline}>The judges' number, then the real world</p>
          </div>
        </div>
        <nav className={s.tabs} role="tablist" aria-label="Sections">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={scn.tab === t.id}
              aria-controls={`panel-${t.id}`}
              className={s.tab}
              onClick={() => dispatch({ type: 'tab', tab: t.id })}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className={s.tools}>
          <button type="button" className={s.tool} onClick={copyLink} title="Copy a link to this exact scenario">
            {copied ? 'Link copied' : 'Copy link'}
          </button>
          <button
            type="button"
            className={s.tool}
            aria-pressed={presenter}
            onClick={() => setPresenter((p) => !p)}
            title="Bigger type for the projector"
          >
            Presenter mode {presenter ? 'on' : 'off'}
          </button>
        </div>
      </header>

      <p className={s.subhead}>
        Tangerine · Resilience Rewired · Sheridan Datathon 2026. Runway uses the judges' published formula;
        reality checks are labelled assumptions shown beside it. Runs offline: no keys, no network.
      </p>

      <main className={s.main}>
        {error ? (
          <div className={s.loadError} role="alert">
            Couldn't load the account data ({error}). Run <code>npm run dev</code> or{' '}
            <code>npm run build &amp;&amp; npm run preview</code> from <code>web/</code>; opening{' '}
            <code>dist/index.html</code> straight from disk doesn't work.
          </div>
        ) : !data ? (
          <div className={s.loading} aria-busy="true">
            Loading 4,500 accounts…
          </div>
        ) : (
          <>
            <section
              role="tabpanel"
              id="panel-live"
              aria-labelledby="tab-live"
              hidden={scn.tab !== 'live'}
            >
              {data.byId.has(scn.id) && (
                <Live data={data} scenario={scn} dispatch={dispatch} searchRef={searchRef} />
              )}
            </section>
            <section
              role="tabpanel"
              id="panel-portfolio"
              aria-labelledby="tab-portfolio"
              hidden={scn.tab !== 'portfolio'}
            >
              {scn.tab === 'portfolio' && <Portfolio data={data} onOpen={openInLive} />}
            </section>
            <section role="tabpanel" id="panel-method" aria-labelledby="tab-method" hidden={scn.tab !== 'method'}>
              {scn.tab === 'method' && <Method />}
            </section>
          </>
        )}
      </main>
      <footer className={s.footer}>
        Keys: <kbd>/</kbd> account box · <kbd>1</kbd>–<kbd>4</kbd> twist cards · <kbd>R</kbd> reset levers to the
        card · arrow keys nudge a focused slider.
      </footer>
    </div>
  );
}
