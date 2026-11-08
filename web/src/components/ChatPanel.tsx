import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { Issue } from '../engine/consistency';
import { HINT_CHIPS } from '../engine/shock_parser';
import { EXAMPLES, SHOWN_MESSAGES, SOURCE_BADGE } from '../lib/chat';
import type { ChatState } from '../lib/chat';
import s from './ChatPanel.module.css';

interface Props {
  chat: ChatState;
  /** the current shock, in this customer's dollars (shock_parser.describe_shock) */
  understoodAs: string;
  /** what resilience/consistency found wrong with the numbers on screen ([] = all consistent) */
  issues: Issue[];
  onSend: (text: string) => void;
  inputRef?: React.RefObject<HTMLInputElement | null>;
}

/** The chat: the main input of the live twist. It only sets the levers; the engine computes every number. */
export function ChatPanel({ chat, understoodAs, issues, onSend, inputRef }: Props) {
  const [draft, setDraft] = useState('');
  const log = useRef<HTMLOListElement | null>(null);
  const shown = chat.messages.slice(-SHOWN_MESSAGES);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [chat.messages.length]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!draft.trim()) return;
    onSend(draft);
    setDraft('');
  };

  return (
    <section className={s.panel} aria-labelledby="chat-title">
      <div className={s.head}>
        <h2 id="chat-title" className={s.title}>
          Describe the twist
        </h2>
        {issues.length === 0 ? (
          <span className={s.ok} role="status">
            ✓ All numbers consistent
          </span>
        ) : (
          <span className={s.warn} role="status">
            ⚠ {issues.length} number check{issues.length === 1 ? '' : 's'} failed
          </span>
        )}
      </div>

      <div className={s.now} aria-live="polite">
        <span>
          <strong>Current shock:</strong> {understoodAs}
        </span>
        <button type="button" className={s.reset} onClick={() => onSend('reset')} aria-keyshortcuts="r">
          ↺ Reset
        </button>
      </div>

      {issues.length > 0 && (
        <div className={s.issues} role="alert">
          <strong>Numbers disagree</strong> (shown, never hidden):
          <ul>
            {issues.map((i) => (
              <li key={`${i.check}:${i.detail}`}>
                {i.check}: {i.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className={s.chips} role="group" aria-label="Try a twist">
        {HINT_CHIPS.map((c) => (
          <button key={c} type="button" className={s.chip} onClick={() => onSend(c)}>
            {c}
          </button>
        ))}
      </div>

      {shown.length > 0 && (
        <ol className={s.log} ref={log} aria-label="Chat">
          {shown.map((m, i) => (
            <li key={chat.messages.length - shown.length + i} className={m.role === 'user' ? s.user : s.bot}>
              {m.role === 'user' ? (
                m.text
              ) : (
                <>
                  <p className={s.reply}>
                    {m.clarify ? '❓ ' : <strong>Understood as: </strong>}
                    {m.text}
                  </p>
                  {m.resolved?.map((line) => (
                    <p key={line} className={s.meta}>
                      ↳ {line}
                    </p>
                  ))}
                  {m.warnings?.map((w) => (
                    <p key={w} className={s.warning}>
                      ⚠️ {w}
                    </p>
                  ))}
                  <p className={s.meta}>
                    {[`source: ${SOURCE_BADGE[m.source ?? 'none']}`, ...(m.hints ?? [])].join(' · ')}
                  </p>
                </>
              )}
            </li>
          ))}
        </ol>
      )}

      <form className={s.form} onSubmit={submit}>
        <label htmlFor="chat-input" className={s.srOnly}>
          Type a twist
        </label>
        <input
          id="chat-input"
          ref={inputRef}
          className={s.input}
          type="text"
          autoComplete="off"
          placeholder="Type a twist, e.g. “rent up $300 a month”"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" className={s.send} disabled={!draft.trim()}>
          Send
        </button>
      </form>

      <details className={s.help}>
        <summary>What can I type?</summary>
        <table className={s.examples}>
          <thead>
            <tr>
              <th scope="col">to set</th>
              <th scope="col">type</th>
            </tr>
          </thead>
          <tbody>
            {EXAMPLES.map(([what, ex]) => (
              <tr key={what}>
                <td>{what}</td>
                <td>{ex}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className={s.meta}>
          Each message changes only what it mentions; everything else keeps its value. Golden phrases are instant and
          identical every time; anything else is read by the offline rules, the same ones the Streamlit app uses.
        </p>
      </details>
    </section>
  );
}
