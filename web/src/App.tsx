import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent } from 'react';
import s from './App.module.css';
import { Live } from './components/Live';
import { Method } from './components/Method';
import { Portfolio } from './components/Portfolio';
import { useAppData } from './lib/load';
import { EMPTY_CHAT } from './lib/chat';
import type { ChatState } from './lib/chat';
import { DEFAULT_ACCOUNT, NO_SHOCK, NO_TOGGLES, decodeScenario, encodeScenario } from './lib/scenario';
import type { Tab } from './lib/scenario';
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

/** A developer's own copy (opened from disk or a local server) gets the how-to-run hint on a load error. */
function isLocalRun(): boolean {
  const { protocol, hostname } = window.location;
  return protocol === 'file:' || ['localhost', '127.0.0.1', '[::1]'].includes(hostname);
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
  const chatRef = useRef<HTMLInputElement | null>(null);
  // the chat history lives here, so it survives switching tabs (it is not part of the shareable URL)
  const [chat, setChat] = useState<ChatState>(EMPTY_CHAT);

  // presenter mode scales the root font size; every size in the app is in rem
  useEffect(() => {
    document.documentElement.dataset.presenter = presenter ? 'on' : 'off';
    try {
      localStorage.setItem('twin-runway:presenter', presenter ? 'on' : 'off');
    } catch {
      /* private window: presenter mode just won't be remembered */
    }
  }, [presenter]);

  // the URL hash holds the scenario, so a reload or a shared link reopens the same twist. A new tab or account
  // is a history entry (Back returns to it); levers, target and checks replace the current one.
  const shown = useRef({ tab: scn.tab, id: scn.id });
  const fromUrl = useRef(true); // this scenario came from the URL itself: rewrite it, don't add an entry
  useEffect(() => {
    const next = `#${encodeScenario(scn)}`;
    const moved = shown.current.tab !== scn.tab || shown.current.id !== scn.id;
    const push = moved && !fromUrl.current;
    shown.current = { tab: scn.tab, id: scn.id };
    fromUrl.current = false;
    if (window.location.hash === next) return;
    if (push) window.history.pushState(null, '', next);
    else window.history.replaceState(null, '', next);
  }, [scn]);

  useEffect(() => {
    // pushState and replaceState never fire hashchange, so this runs on Back/Forward or an edited or pasted URL
    const onHash = () => {
      fromUrl.current = true;
      dispatch({ type: 'replace', scenario: decodeScenario(window.location.hash) });
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // an id from the hash that isn't in the data falls back to the default account, keeping the link's twist
  useEffect(() => {
    if (data && !data.byId.has(scn.id)) {
      fromUrl.current = true;
      dispatch({ type: 'replace', scenario: { ...scn, id: DEFAULT_ACCOUNT } });
    }
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
      if (e.key === 't' || e.key === 'T') {
        e.preventDefault();
        dispatch({ type: 'tab', tab: 'live' });
        window.setTimeout(() => chatRef.current?.focus(), 0);
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

  const openInLive = useCallback((id: number, ei?: boolean) => {
    if (ei) dispatch({ type: 'apply', id, levers: { ...NO_SHOCK, incomePct: 55, jobLoss: true }, toggles: NO_TOGGLES,
      target: 6 });
    else dispatch({ type: 'open', id, tab: 'live' });
    window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    // keyboard focus follows the account to the live twist (the heading names it)
    window.setTimeout(() => document.getElementById('customer-title')?.focus({ preventScroll: true }), 0);
  }, []);

  // tabs follow the ARIA tabs pattern: one Tab stop, arrow keys move between them, Home and End jump
  const onTabsKey = (e: ReactKeyboardEvent<HTMLElement>) => {
    const i = TABS.findIndex((t) => t.id === scn.tab);
    const j =
      e.key === 'ArrowRight' ? (i + 1) % TABS.length
      : e.key === 'ArrowLeft' ? (i - 1 + TABS.length) % TABS.length
      : e.key === 'Home' ? 0
      : e.key === 'End' ? TABS.length - 1
      : -1;
    if (j < 0) return;
    e.preventDefault();
    dispatch({ type: 'tab', tab: TABS[j].id });
    document.getElementById(`tab-${TABS[j].id}`)?.focus();
  };

  // the skip link moves focus without touching the hash, which holds the scenario
  const skipToMain = (e: ReactMouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    document.getElementById('main')?.focus();
  };

  return (
    <div className={s.app}>
      <a href="#main" className={s.skip} onClick={skipToMain}>
        Skip to content
      </a>
      <header className={s.header}>
        <div className={s.brand}>
          <span className={s.logo} aria-hidden="true" />
          <div>
            <h1 className={s.title}>Twin Runway</h1>
            <p className={s.tagline}>The judges' number, then the real world</p>
          </div>
        </div>
        <nav className={s.tabs} role="tablist" aria-label="Sections" onKeyDown={onTabsKey}>
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              tabIndex={scn.tab === t.id ? 0 : -1}
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
        <p className={s.subhead}>
          Tangerine · Resilience Rewired · Sheridan Datathon 2026. Runway uses the judges' published formula;
          reality checks are labelled assumptions shown beside it. Runs offline: no keys, no network.
        </p>
      </header>

      <main id="main" tabIndex={-1} className={s.main}>
        {error ? (
          <div className={s.loadError} role="alert">
            Couldn't load the account data. Reload the page.
            {isLocalRun() && (
              <>
                {' '}
                ({error}) Run <code>npm run dev</code> or <code>npm run build &amp;&amp; npm run preview</code> from{' '}
                <code>web/</code>; opening <code>dist/index.html</code> straight from disk doesn't work.
              </>
            )}
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
                <Live data={data} scenario={scn} dispatch={dispatch} searchRef={searchRef} chat={chat}
                  setChat={setChat} chatRef={chatRef} />
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
        Keys: <kbd>/</kbd> account box · <kbd>T</kbd> type a twist · <kbd>R</kbd> reset to no shock · arrow keys nudge
        a focused slider.
      </footer>
    </div>
  );
}
