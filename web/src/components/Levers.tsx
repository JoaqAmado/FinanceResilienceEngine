import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { LIMITS } from '../lib/scenario';
import type { Levers as LeverValues } from '../lib/scenario';
import s from './Levers.module.css';

interface Limit {
  min: number;
  max: number;
  sliderMax: number;
  step: number;
}

/** Exact numeric entry: keeps a draft while typing, commits every valid number, tidies up on blur. */
function NumberField({
  id,
  value,
  limit,
  disabled,
  integer,
  onChange,
  describedBy,
}: {
  id: string;
  value: number;
  limit: Limit;
  disabled?: boolean;
  integer?: boolean;
  onChange: (v: number) => void;
  describedBy?: string;
}) {
  const [draft, setDraft] = useState(String(value));
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused) setDraft(String(value));
  }, [value, focused]);
  const clamp = (n: number) => {
    const v = Math.min(limit.max, Math.max(limit.min, n));
    return integer ? Math.round(v) : v;
  };
  return (
    <input
      id={id}
      className={s.number}
      type="text"
      inputMode="decimal"
      autoComplete="off"
      disabled={disabled}
      value={draft}
      aria-describedby={describedBy}
      onFocus={(e) => {
        setFocused(true);
        e.currentTarget.select();
      }}
      onBlur={() => {
        setFocused(false);
        setDraft(String(value));
      }}
      onChange={(e) => {
        const raw = e.target.value;
        setDraft(raw);
        const n = Number(raw.replace(/[$,\s%×x]/gi, ''));
        if (raw.trim() !== '' && Number.isFinite(n)) {
          const v = clamp(n);
          if (v !== n) setDraft(String(v)); // show the value actually applied
          onChange(v);
        }
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur();
      }}
    />
  );
}

function Lever({
  id,
  label,
  unit,
  value,
  limit,
  disabled,
  integer,
  hint,
  onChange,
}: {
  id: string;
  label: string;
  unit: string;
  value: number;
  limit: Limit;
  disabled?: boolean;
  integer?: boolean;
  hint?: string;
  onChange: (v: number) => void;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  // the track fills tangerine up to the thumb (a bar length only; the number field shows the value)
  const shown = Math.min(value, limit.sliderMax);
  const fill = limit.sliderMax > limit.min ? ((shown - limit.min) / (limit.sliderMax - limit.min)) * 100 : 0;
  return (
    <div className={s.lever} data-disabled={disabled ? 'true' : undefined}>
      <div className={s.leverTop}>
        <label htmlFor={id} className={s.leverLabel}>
          {label}
        </label>
        <span className={s.field}>
          {unit === '$' && <span className={s.unit}>$</span>}
          <NumberField
            id={id}
            value={value}
            limit={limit}
            disabled={disabled}
            integer={integer}
            onChange={onChange}
            describedBy={hintId}
          />
          {unit !== '$' && <span className={s.unit}>{unit}</span>}
        </span>
      </div>
      <input
        type="range"
        className={s.range}
        aria-label={`${label} slider`}
        min={limit.min}
        max={limit.sliderMax}
        step={limit.step}
        value={shown}
        style={{ '--p': `${fill}%` } as CSSProperties}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {hint && (
        <p id={hintId} className={s.hint}>
          {hint}
        </p>
      )}
    </div>
  );
}

interface Props {
  levers: LeverValues;
  target: number;
  onLevers: (patch: Partial<LeverValues>) => void;
  onTarget: (n: number) => void;
  onReset: () => void;
}

export function Levers({ levers: l, target, onLevers, onTarget, onReset }: Props) {
  const byX = l.oneOffMode === 'x';
  return (
    <section className={s.panel} aria-labelledby="levers-title">
      <div className={s.head}>
        <h2 id="levers-title" className={s.title}>
          Twist levers
        </h2>
        <button type="button" className={s.reset} onClick={onReset}>
          ↺ Reset to card
        </button>
      </div>

      <Lever
        id="lever-income"
        label="Income kept"
        unit="%"
        value={l.incomePct}
        limit={LIMITS.incomePct}
        hint={l.jobLoss && l.incomePct < 100 ? 'EI pays 55% of usual money in' : undefined}
        onChange={(v) => onLevers({ incomePct: v })}
      />
      <label className={s.check} data-disabled={l.incomePct >= 100 ? 'true' : undefined}>
        <input
          type="checkbox"
          aria-label="This is a job loss on EI"
          checked={l.jobLoss}
          disabled={l.incomePct >= 100}
          onChange={(e) => onLevers({ jobLoss: e.target.checked })}
        />
        <span>
          This is a job loss on EI
          <span className={s.checkHint}>
            {l.incomePct >= 100
              ? 'Lower income kept to use this'
              : 'Off = a pay cut or fewer hours: no EI cap, waiting week or pension checks'}
          </span>
        </span>
      </label>

      <Lever
        id="lever-bills"
        label="Household bills up"
        unit="%"
        value={l.billsPct}
        limit={LIMITS.billsPct}
        hint="Rises with H, the household bills on record"
        onChange={(v) => onLevers({ billsPct: v })}
      />
      <Lever
        id="lever-extra"
        label="Extra monthly cost"
        unit="$"
        value={l.extra}
        limit={LIMITS.extra}
        hint="Rent up $X a month goes here: H is $0 on 1,225 accounts"
        onChange={(v) => onLevers({ extra: v })}
      />

      <fieldset className={s.oneoff}>
        <legend className={s.leverLabel}>One-off cost</legend>
        <div className={s.modes} role="radiogroup" aria-label="One-off cost as">
          <label className={s.mode} data-on={byX ? 'true' : undefined}>
            <input
              type="radio"
              name="oneoff-mode"
              checked={byX}
              onChange={() => onLevers({ oneOffMode: 'x' })}
            />
            × typical spending
          </label>
          <label className={s.mode} data-on={!byX ? 'true' : undefined}>
            <input
              type="radio"
              name="oneoff-mode"
              checked={!byX}
              onChange={() => onLevers({ oneOffMode: 'amt' })}
            />
            $ amount
          </label>
        </div>
        <Lever
          id="lever-oneoff-x"
          label="× S (typical spending)"
          unit="×"
          value={l.oneOffX}
          limit={LIMITS.oneOffX}
          disabled={!byX}
          onChange={(v) => onLevers({ oneOffX: v })}
        />
        <Lever
          id="lever-oneoff-amt"
          label="One-off amount"
          unit="$"
          value={l.oneOffAmt}
          limit={LIMITS.oneOffAmt}
          disabled={byX}
          onChange={(v) => onLevers({ oneOffAmt: v })}
        />
      </fieldset>

      <Lever
        id="lever-target"
        label="Must survive"
        unit="months"
        value={target}
        limit={LIMITS.target}
        integer
        onChange={(v) => onTarget(Math.round(v))}
      />
    </section>
  );
}
