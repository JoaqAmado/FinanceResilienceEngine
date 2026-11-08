import { useEffect, useId, useMemo, useState } from 'react';
import type { RefObject } from 'react';
import s from './AccountPicker.module.css';

/** Rehearsal accounts and the story each one tells (research/pitch-and-twist-script.md). */
export const REHEARSAL: readonly [number, string][] = [
  [77743, 'high money-in, thin buffer'],
  [20331, 'overdrawn before its loan'],
  [20143, 'spends more than comes in'],
  [88269, "looks safe, isn't"],
  [98952, 'retiree'],
];

const ID_DIGITS = 5;
const MAX_SUGGESTIONS = 8;

interface Props {
  ids: number[];
  has: (id: number) => boolean;
  current: number;
  onOpen: (id: number) => void;
  inputRef: RefObject<HTMLInputElement | null>;
}

/** The two ids either side of a missing one. */
function nearest(ids: number[], n: number): number[] {
  let lo = 0;
  let hi = ids.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (ids[mid] < n) lo = mid + 1;
    else hi = mid;
  }
  return [ids[lo - 1], ids[lo]].filter((x): x is number => x !== undefined);
}

export function AccountPicker({ ids, has, current, onOpen, inputRef }: Props) {
  const listId = useId();
  const errId = useId();
  const [text, setText] = useState(String(current));
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [error, setError] = useState<{ text: string; near: number[] } | null>(null);

  // the box follows the account when it changes elsewhere (chips, random, portfolio, URL)
  useEffect(() => {
    setText(String(current));
    setError(null);
  }, [current]);

  const suggestions = useMemo(() => {
    if (!text || text === String(current)) return [];
    const out: number[] = [];
    for (const id of ids) {
      if (String(id).startsWith(text)) {
        out.push(id);
        if (out.length === MAX_SUGGESTIONS) break;
      }
    }
    return out;
  }, [ids, text, current]);

  const range = `IDs run ${ids[0]} to ${ids[ids.length - 1]} with gaps.`;

  function go(id: number) {
    setOpen(false);
    setError(null);
    setText(String(id));
    onOpen(id);
    // leave the box once an account opens, so keys 1-4 pick the twist card straight away (/ comes back here)
    inputRef.current?.blur();
  }

  function reject(t: string) {
    const n = Number(t);
    setError({ text: `account_id ${t} is not in the data. ${range}`, near: nearest(ids, n) });
    setOpen(false);
  }

  function onChange(raw: string) {
    const t = raw.replace(/\D/g, '').slice(0, 7);
    setText(t);
    setActive(0);
    setOpen(true);
    if (t.length >= ID_DIGITS) {
      const n = Number(t);
      if (has(n)) go(n);
      else reject(t);
    } else if (t && !ids.some((id) => String(id).startsWith(t))) {
      setError({ text: `No account_id starts with ${t}. ${range}`, near: [] });
    } else {
      setError(null);
    }
  }

  function submit() {
    if (open && suggestions[active] !== undefined && Number(text) !== suggestions[active]) {
      go(suggestions[active]);
      return;
    }
    if (!text) return;
    const n = Number(text);
    if (has(n)) go(n);
    else reject(text);
  }

  function pickRandom() {
    if (ids.length < 2) return;
    let id = current;
    while (id === current) id = ids[Math.floor(Math.random() * ids.length)];
    go(id);
  }

  const showList = open && suggestions.length > 0;

  return (
    <div className={s.picker}>
      <div className={s.searchWrap}>
        <label htmlFor="account-search" className={s.label}>
          account_id <span className={s.hint}>press /</span>
        </label>
        <div className={s.combo}>
          <input
            id="account-search"
            ref={inputRef}
            className={s.input}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            spellCheck={false}
            role="combobox"
            aria-expanded={showList}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={showList ? `${listId}-${active}` : undefined}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errId : undefined}
            placeholder="e.g. 20331"
            value={text}
            onFocus={(e) => e.currentTarget.select()}
            onChange={(e) => onChange(e.target.value)}
            onBlur={() => window.setTimeout(() => setOpen(false), 120)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown' && suggestions.length) {
                e.preventDefault();
                setOpen(true);
                setActive((a) => Math.min(a + 1, suggestions.length - 1));
              } else if (e.key === 'ArrowUp' && suggestions.length) {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === 'Enter') {
                e.preventDefault();
                submit();
              } else if (e.key === 'Escape') {
                setOpen(false);
                setText(String(current));
                setError(null);
              }
            }}
          />
          {showList && (
            <ul id={listId} role="listbox" className={s.list} aria-label="Matching account ids">
              {suggestions.map((id, i) => (
                <li
                  key={id}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  className={s.option}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => go(id)}
                  onMouseEnter={() => setActive(i)}
                >
                  {id}
                </li>
              ))}
            </ul>
          )}
        </div>
        <button type="button" className={s.random} onClick={pickRandom}>
          Random account
        </button>
      </div>

      <div className={s.chips} role="group" aria-label="Rehearsal accounts">
        {REHEARSAL.map(([id, why]) => (
          <button
            key={id}
            type="button"
            className={s.chip}
            aria-pressed={current === id}
            onClick={() => go(id)}
          >
            <span className={s.chipId}>{id}</span>
            <span className={s.chipWhy}>{why}</span>
          </button>
        ))}
      </div>

      {error && (
        <div id={errId} className={s.error} role="alert">
          <span>
            {error.text} Still showing account {current}.
          </span>
          {error.near.length > 0 && (
            <span className={s.near}>
              Nearest:
              {error.near.map((id) => (
                <button key={id} type="button" className={s.nearBtn} onClick={() => go(id)}>
                  {id}
                </button>
              ))}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
