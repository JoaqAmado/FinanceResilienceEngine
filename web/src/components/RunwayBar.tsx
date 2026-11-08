import type { RunwayResult } from '../engine';
import { rwText } from '../lib/format';
import s from './RunwayBar.module.css';

/** The "Must survive" lever tops out at 12 months, so the bar runs 0 to 12. */
const SCALE = 12;
const TICKS = [0, 3, 6, 9, 12];

/** Bar length only (0..1). Every number a person reads still comes from the engine via rwText(). */
function share(r: RunwayResult): number {
  if (r.noShortfall) return 1;
  return Math.min(Math.max(r.months ?? 0, 0), SCALE) / SCALE;
}

interface Props {
  judge: RunwayResult;
  target: number;
  /** the runway with the selected reality checks; shown as a hatched orange marker only when a check is on */
  real?: RunwayResult | null;
  still?: boolean;
  /** the floating pill: the line for the must-survive target, without its label or the scale */
  compact?: boolean;
}

export function RunwayBar({ judge, target, real = null, still = false, compact = false }: Props) {
  const over = judge.noShortfall || (judge.months ?? 0) > SCALE;
  const edge = target >= 11 ? 'end' : target <= 1 ? 'start' : undefined;
  const a = share(judge);
  const b = real ? share(real) : a;
  const checks = real ? `, reality checks ${rwText(real)}` : '';
  return (
    <div
      className={s.bar}
      data-still={still ? 'true' : undefined}
      data-compact={compact ? 'true' : undefined}
      role="img"
      aria-label={`Judges' runway ${rwText(judge)}${checks}, against a must-survive line at ${target} months, on a 0 to 12 month scale`}
    >
      <div className={s.track}>
        <div className={s.fill} data-over={over ? 'true' : undefined} style={{ width: `${a * 100}%` }} />
        {real && (
          // orange = reality check, as in every chart: the stretch between the judges' runway and the checked one
          <div
            className={s.real}
            data-shorter={b < a ? 'true' : undefined}
            style={{ left: `${Math.min(a, b) * 100}%`, width: `${Math.abs(a - b) * 100}%` }}
          />
        )}
        <div className={s.flag} data-edge={edge} style={{ left: `${(target / SCALE) * 100}%` }}>
          <span>must survive {target}</span>
        </div>
      </div>
      <div className={s.ticks} aria-hidden="true">
        {TICKS.map((t) => (
          <span key={t} style={{ left: `${(t / SCALE) * 100}%` }}>
            {t === SCALE ? '12 mo' : t}
          </span>
        ))}
      </div>
    </div>
  );
}
