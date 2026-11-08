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

export function RunwayBar({ judge, target, still = false }: { judge: RunwayResult; target: number; still?: boolean }) {
  const over = judge.noShortfall || (judge.months ?? 0) > SCALE;
  const edge = target >= 11 ? 'end' : target <= 1 ? 'start' : undefined;
  return (
    <div
      className={s.bar}
      data-still={still ? 'true' : undefined}
      role="img"
      aria-label={`Judges' runway ${rwText(judge)}, against a must-survive line at ${target} months, on a 0 to 12 month scale`}
    >
      <div className={s.track}>
        <div className={s.fill} data-over={over ? 'true' : undefined} style={{ width: `${share(judge) * 100}%` }} />
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
