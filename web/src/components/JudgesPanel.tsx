import NumberFlow from '@number-flow/react';
import { pyFixed, survives } from '../engine';
import type { Account, RunwayResult, Shock } from '../engine';
import { money, rwText } from '../lib/format';
import s from './JudgesPanel.module.css';

interface Props {
  acct: Account;
  judge: RunwayResult;
  baseline: RunwayResult;
  shock: Shock;
  target: number;
  greyNote: string | null;
}

type Verdict = { kind: 'good' | 'bad'; icon: string; text: string };

/** app.py's badge, in the same order: survives, already overdrawn, buffer gone, runs out. */
function verdict(acct: Account, judge: RunwayResult, N: number): Verdict {
  if (survives(judge, N)) return { kind: 'good', icon: '✓', text: `SURVIVES ${N} MONTHS` };
  if (acct.B <= 0) {
    return {
      kind: 'bad',
      icon: '!',
      text: `ALREADY OVERDRAWN: the buffer was ${money(acct.B)} before any shock, so runway is 0`,
    };
  }
  if (judge.bufferLeft <= 0) {
    return { kind: 'bad', icon: '!', text: `BUFFER GONE: the one-off (${money(judge.oneOff)}) is more than the buffer` };
  }
  return { kind: 'bad', icon: '!', text: `RUNS OUT IN ${pyFixed(judge.months ?? 0, 1)} MONTHS (needs ${N})` };
}

/** The judges' formula with this account's numbers filled in (inputs shown to the dollar). */
function Formula({ acct, judge }: { acct: Account; judge: RunwayResult }) {
  const left = `(${money(acct.B)} − ${money(judge.oneOff)})`;
  const gap = `(${money(judge.spendingAfter)} − ${money(judge.incomeAfter)})`;
  let result: string;
  if (judge.bufferLeft <= 0) result = 'buffer left ≤ $0, so 0 months';
  else if (judge.gap <= 0) result = 'gap ≤ $0, so no shortfall (120+)';
  else result = judge.capped ? '120.0 months (the 120-month cap)' : `${pyFixed(judge.months ?? 0, 1)} months`;
  return (
    <div className={s.formula}>
      <div className={s.formulaRule}>(B − one-off) ÷ (spending after − income after)</div>
      <div className={s.formulaNums}>
        = {left} ÷ {gap} = <strong>{result}</strong>
      </div>
    </div>
  );
}

export function JudgesPanel({ acct, judge, baseline, shock, target, greyNote }: Props) {
  const v = verdict(acct, judge, target);
  const flow = judge.gap > 0 ? `gap ${money(judge.gap)}/mo` : `surplus ${money(Math.abs(judge.gap))}/mo`;
  const exact = rwText(judge);
  return (
    <section className={s.panel} aria-labelledby="judges-title">
      <div className={s.head}>
        <h2 id="judges-title" className={s.eyebrow}>
          Judges' formula
        </h2>
        <span className={s.official}>the official number</span>
      </div>

      <div className={s.hero}>
        <span className="visually-hidden" aria-live="polite">
          Judges' runway: {exact}
        </span>
        <span className={s.heroValue} aria-hidden="true">
          {judge.noShortfall ? (
            <span className={s.heroText}>No shortfall</span>
          ) : (
            <NumberFlow
              className={s.heroNum}
              value={judge.months ?? 0}
              locales="en-CA"
              format={{ minimumFractionDigits: 1, maximumFractionDigits: 1 }}
              transformTiming={{ duration: 450, easing: 'ease-out' }}
              spinTiming={{ duration: 450, easing: 'ease-out' }}
            />
          )}
        </span>
        <span className={s.heroUnit} aria-hidden="true">
          {judge.noShortfall ? '120+ months' : judge.capped ? 'months (cap)' : 'months of runway'}
        </span>
      </div>

      <div className={`${s.badge} ${v.kind === 'good' ? s.good : s.bad}`}>
        <span className={s.badgeIcon} aria-hidden="true">
          {v.icon}
        </span>
        <span>{v.text}</span>
      </div>

      <Formula acct={acct} judge={judge} />

      <p className={s.caption}>
        twist: <strong>{shock.name}</strong> · income after {money(judge.incomeAfter)}/mo · spending after{' '}
        {money(judge.spendingAfter)}/mo · {flow} · buffer left {money(judge.bufferLeft)}
      </p>
      <p className={s.before}>
        Before the twist: <strong>{rwText(baseline)}</strong> → with it: <strong>{exact}</strong>
      </p>

      {greyNote && (
        <div className={s.grey} role="note">
          <span aria-hidden="true">≈</span> {greyNote}
        </div>
      )}
    </section>
  );
}
