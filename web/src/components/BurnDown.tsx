import { useMemo } from 'react';
import { usePrefersReducedMotion } from '@number-flow/react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { TooltipContentProps } from 'recharts';
import { balancePath, loanInTrouble, makeShock, planPath, pyFixed } from '../engine';
import type { Account, Ladder, RunwayResult, Shock } from '../engine';
import { COLORS, DASH } from '../lib/colors';
import { axisMoney, money } from '../lib/format';
import { burnDownHorizon, calendarBalancePath } from '../lib/paths';
import s from './BurnDown.module.css';

interface Props {
  acct: Account;
  judgeShock: Shock;
  judge: RunwayResult;
  planShock: Shock;
  ladder: Ladder;
  target: number;
  activeNames: string[];
  /** a slider is being dragged: skip the chart animation so it tracks the pointer */
  dragging: boolean;
}

interface Row {
  t: number;
  base: number;
  judges: number;
  plan: number;
  jan: number;
}

const SERIES = [
  { key: 'judges', label: "Judges' twist", color: COLORS.judges, dash: DASH.judges },
  { key: 'plan', label: 'Twist + backup plan', color: COLORS.plan, dash: DASH.plan },
  { key: 'jan', label: 'Starting in January (month by month)', color: COLORS.reality, dash: DASH.reality },
  { key: 'base', label: 'No shock', color: COLORS.base, dash: DASH.base },
] as const;

function Swatch({ color, dash }: { color: string; dash: string }) {
  return (
    <svg width="30" height="10" aria-hidden="true" className={s.swatch}>
      <line x1="1" y1="5" x2="29" y2="5" stroke={color} strokeWidth="3" strokeDasharray={dash || undefined} />
    </svg>
  );
}

function ChartTooltip({ active, payload }: TooltipContentProps) {
  const row = payload?.[0]?.payload as Row | undefined;
  if (!active || !row) return null;
  return (
    <div className={s.tooltip}>
      <div className={s.tipTitle}>Month {row.t}</div>
      {SERIES.map((x) => (
        <div key={x.key} className={s.tipRow}>
          <Swatch color={x.color} dash={x.dash} />
          <span className={s.tipLabel}>{x.label}</span>
          <span className={s.tipValue}>{money(row[x.key])}</span>
        </div>
      ))}
    </div>
  );
}

function tickStep(h: number): number {
  if (h <= 30) return 3;
  if (h <= 72) return 6;
  if (h <= 150) return 12;
  return 24;
}

export function BurnDown({ acct, judgeShock, judge, planShock, ladder, target, activeNames, dragging }: Props) {
  // months 0..max(24, 2x the judges' runway)
  const horizon = burnDownHorizon(judge);
  const rows = useMemo<Row[]>(() => {
    const base = balancePath(acct, makeShock(), horizon);
    const judges = balancePath(acct, judgeShock, horizon);
    // a loan already in arrears or default gets no new credit: draw the plan with cuts only
    const planLadder = loanInTrouble(acct) ? { ...ladder, cashOrCreditNeeded: 0 } : ladder;
    const plan = planPath(acct, planShock, planLadder, horizon);
    const jan = calendarBalancePath(acct, judgeShock, horizon);
    return judges.map((v, t) => ({ t, base: base[t], judges: v, plan: plan[t], jan: jan[t] }));
  }, [acct, judgeShock, planShock, ladder, horizon]);

  const step = tickStep(horizon);
  const ticks = Array.from({ length: Math.floor(horizon / step) + 1 }, (_, i) => i * step);
  const wiped = judge.bufferLeft <= 0;
  // the month the judges' balance line crosses $0 (not when the buffer is gone from the start, or at the cap)
  const zeroAt = !wiped && !judge.noShortfall && !judge.capped && judge.months !== null ? judge.months : null;
  const reduced = usePrefersReducedMotion();
  const anim = !dragging && !reduced;
  const planNote = ladder.alreadySafe
    ? 'no plan needed: it already survives'
    : ladder.firstSufficient !== null
      ? `plan: ${ladder.rungs[ladder.firstSufficient].step.replace(/^\+ /, '')}`
      : ladder.cashOrCreditNeeded
        ? loanInTrouble(acct)
          ? `plan: cuts only; a ${money(ladder.cashOrCreditNeeded)} hole remains (no new credit: loan in arrears or default)`
          : `plan: ${money(ladder.cashOrCreditNeeded)} of cash or credit${ladder.rungs.length ? ' after every cut' : ''}`
        : ladder.verdict;

  return (
    <section className={s.panel} aria-labelledby="burn-title">
      <div className={s.head}>
        <div>
          <h2 id="burn-title" className={s.eyebrow}>
            Burn-down: balance month by month
          </h2>
          <p className={s.sub}>
            Judges' constant-gap model: B − one-off − gap × month.{' '}
            {zeroAt !== null && (
              <>
                The buffer hits $0 at month <strong>{pyFixed(zeroAt, 1)}</strong>.
              </>
            )}
            {wiped && (
              <>
                The buffer is gone from month 0 (buffer left <strong>{money(judge.bufferLeft)}</strong>), so the judges'
                runway is 0.
              </>
            )}
            {!wiped && judge.noShortfall && <>No shortfall: the balance never falls.</>}
            {judge.capped && <>Runway is at the 120-month cap.</>}
          </p>
        </div>
        <ul className={s.legend} aria-label="Chart legend">
          {SERIES.map((x) => (
            <li key={x.key}>
              <Swatch color={x.color} dash={x.dash} />
              {x.label}
              {x.key === 'plan' && <span className={s.legendNote}> ({planNote})</span>}
              {x.key === 'plan' && activeNames.length > 0 && (
                <span className={s.legendNote}> with {activeNames.join(', ')}</span>
              )}
            </li>
          ))}
        </ul>
      </div>

      <div className={s.chart}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 22, right: 18, bottom: 6, left: 6 }}
            title="Burn-down: balance month by month after the twist"
            desc="One line per path in the legend. The left and right arrow keys step through the months."
          >
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={[0, horizon]}
              ticks={ticks}
              tickLine={false}
              stroke={COLORS.axis}
              tick={{ fill: COLORS.muted }}
              label={{ value: 'months after the shock', position: 'insideBottomRight', offset: -2, fill: COLORS.muted }}
              height={40}
            />
            <YAxis
              tickFormatter={axisMoney}
              width="auto"
              tickLine={false}
              axisLine={false}
              tick={{ fill: COLORS.muted }}
            />
            <Tooltip content={ChartTooltip} cursor={{ stroke: COLORS.axis, strokeWidth: 1 }} isAnimationActive={false} />
            <ReferenceLine y={0} stroke={COLORS.ink2} strokeWidth={1.5} />
            {target <= horizon && (
              <ReferenceLine
                x={target}
                stroke={COLORS.axis}
                strokeDasharray="3 3"
                label={{ value: `must survive ${target} mo`, position: 'insideTopLeft', fill: COLORS.muted }}
              />
            )}
            <Area
              type="linear"
              dataKey="judges"
              name="Judges' twist"
              stroke={COLORS.judges}
              strokeWidth={3}
              fill={COLORS.judges}
              fillOpacity={0.1}
              baseValue={0}
              dot={false}
              activeDot={{ r: 5, stroke: COLORS.surface, strokeWidth: 2 }}
              isAnimationActive={anim}
              animationDuration={350}
            />
            <Line
              type="linear"
              dataKey="plan"
              name="Twist + backup plan"
              stroke={COLORS.plan}
              strokeWidth={2.5}
              strokeDasharray={DASH.plan}
              dot={false}
              activeDot={{ r: 5, stroke: COLORS.surface, strokeWidth: 2 }}
              isAnimationActive={anim}
              animationDuration={350}
            />
            <Line
              type="linear"
              dataKey="jan"
              name="Starting in January"
              stroke={COLORS.reality}
              strokeWidth={2.5}
              strokeDasharray={DASH.reality}
              dot={false}
              activeDot={{ r: 5, stroke: COLORS.surface, strokeWidth: 2 }}
              isAnimationActive={anim}
              animationDuration={350}
            />
            <Line
              type="linear"
              dataKey="base"
              name="No shock"
              stroke={COLORS.base}
              strokeWidth={2}
              strokeDasharray={DASH.base}
              dot={false}
              activeDot={{ r: 4, stroke: COLORS.surface, strokeWidth: 2 }}
              isAnimationActive={anim}
              animationDuration={350}
            />
            {zeroAt !== null && (
              <ReferenceLine
                x={zeroAt}
                stroke={COLORS.judges}
                strokeDasharray="4 3"
                label={{ value: `$0 at month ${pyFixed(zeroAt, 1)}`, position: 'top', fill: COLORS.ink }}
              />
            )}
            {zeroAt !== null && (
              <ReferenceDot x={zeroAt} y={0} r={6} fill={COLORS.judges} stroke={COLORS.surface} strokeWidth={2} />
            )}
            {wiped && (
              <ReferenceDot
                x={0}
                y={judge.bufferLeft}
                r={6}
                fill={COLORS.judges}
                stroke={COLORS.surface}
                strokeWidth={2}
                label={{ value: `buffer gone: ${money(judge.bufferLeft)}`, position: 'right', fill: COLORS.ink, offset: 10 }}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <details className={s.table}>
        <summary>Show the numbers</summary>
        <div className={s.tableScroll}>
          <table>
            <thead>
              <tr>
                <th scope="col">Month</th>
                {SERIES.map((x) => (
                  <th key={x.key} scope="col">
                    {x.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.t}>
                  <th scope="row">{r.t}</th>
                  {SERIES.map((x) => (
                    <td key={x.key}>{money(r[x.key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
