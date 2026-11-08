import type { RunwayResult } from '../engine';
import { deltaSign, deltaText, pathText, rwText } from '../lib/format';
import type { CheckKey, CheckRow } from '../lib/live';
import s from './RealityPanel.module.css';

interface Props {
  judge: RunwayResult;
  real: RunwayResult;
  anyOn: boolean;
  activeNames: string[];
  checks: CheckRow[];
  jan: number;
  onToggle: (key: CheckKey, on: boolean) => void;
}

function Delta({ v, judge }: { v: RunwayResult | number; judge: RunwayResult }) {
  const sign = deltaSign(v, judge);
  const cls = sign < 0 ? s.down : sign > 0 ? s.up : s.same;
  const arrow = sign < 0 ? '▼' : sign > 0 ? '▲' : '=';
  return (
    <span className={`${s.delta} ${cls}`}>
      <span aria-hidden="true">{arrow}</span> {deltaText(v, judge)}
    </span>
  );
}

export function RealityPanel({ judge, real, anyOn, activeNames, checks, jan, onToggle }: Props) {
  return (
    <section className={s.panel} aria-labelledby="reality-title">
      <div className={s.head}>
        <h2 id="reality-title" className={s.eyebrow}>
          Reality checks
        </h2>
        <span className={s.labelled}>our labelled assumptions: the judges' number never changes</span>
      </div>

      <div className={s.combined}>
        <span className={s.combinedLabel}>Runway with the selected checks</span>
        <span className={s.combinedValue}>{rwText(real)}</span>
        <span className="visually-hidden" aria-live="polite">
          Runway with the selected checks: {rwText(real)}
        </span>
        {anyOn ? (
          <>
            <Delta v={real} judge={judge} />
            <span className={s.active}>{activeNames.join(' + ')}</span>
          </>
        ) : (
          <span className={s.active}>none selected: same as the judges' number</span>
        )}
      </div>

      <ul className={s.rows}>
        {checks.map((c) => (
          <li key={c.key} className={s.row} data-disabled={c.enabled ? undefined : 'true'}>
            <label className={s.toggle}>
              <input
                type="checkbox"
                role="switch"
                aria-label={c.label}
                checked={c.on}
                disabled={!c.enabled}
                aria-describedby={`check-${c.key}-help`}
                onChange={(e) => onToggle(c.key, e.target.checked)}
              />
              <span className={s.track} aria-hidden="true" />
              <span className={s.name}>
                {c.label}
                <span id={`check-${c.key}-help`} className={s.help}>
                  {c.enabled ? c.help : c.reason}
                </span>
              </span>
            </label>
            {c.enabled ? (
              <span className={s.values}>
                <span className={s.value}>{rwText(c.result)}</span>
                <Delta v={c.result} judge={judge} />
              </span>
            ) : (
              <span className={s.values}>
                <span className={s.na}>n/a</span>
              </span>
            )}
          </li>
        ))}
        <li className={`${s.row} ${s.janRow}`}>
          <span className={s.toggle}>
            <span className={s.dash} aria-hidden="true" />
            <span className={s.name}>
              Starting in January (month by month)
              <span className={s.help}>
                Each month costs this account's median spending for that calendar month. Dashed orange on the chart.
              </span>
            </span>
          </span>
          <span className={s.values}>
            <span className={s.value}>{pathText(jan)}</span>
            <Delta v={jan} judge={judge} />
          </span>
        </li>
      </ul>
    </section>
  );
}
