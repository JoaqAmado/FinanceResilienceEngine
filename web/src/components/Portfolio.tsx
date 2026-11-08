import { useMemo, useState } from 'react';
import type { SyntheticEvent } from 'react';
import { usePrefersReducedMotion } from '@number-flow/react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ErrorBar,
  LabelList,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { TooltipContentProps, XAxisTickContentProps } from 'recharts';
import { RULES, WINDOW_ROWS, evidenceLines, pyFixed } from '../engine';
import type { IrregularRow, LiftRow, PortfolioFile } from '../engine';
import { COLORS, DASH } from '../lib/colors';
import { count, kMoney, money, monthsOf, pct1, pctValue, rwText } from '../lib/format';
import type { AppData } from '../lib/load';
import { INCOME_LABELS, failsSix, portfolioRows } from '../lib/portfolio';
import type { AccountRow } from '../lib/portfolio';
import type { CardId } from '../lib/scenario';
import s from './Portfolio.module.css';

interface Props {
  data: AppData;
  onOpen: (id: number, card?: CardId) => void;
}

type SortKey = 'id' | 'I' | 'B' | 'buf' | 'ei' | 'cap';

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'id', label: 'account_id' },
  { key: 'I', label: 'Money in / mo' },
  { key: 'B', label: 'Buffer' },
  { key: 'buf', label: 'Buffer (months of S)' },
  { key: 'ei', label: "Judges' EI 55%" },
  { key: 'cap', label: '2026 EI cap' },
];

function sortValue(r: AccountRow, k: SortKey): number {
  switch (k) {
    case 'id':
      return r.id;
    case 'I':
      return r.I;
    case 'B':
      return r.B;
    case 'buf':
      return r.bufferMonths ?? Infinity;
    case 'ei':
      return monthsOf(r.ei);
    case 'cap':
      return monthsOf(r.cap);
  }
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className={s.tile}>
      <span className={s.tileLabel}>{label}</span>
      <span className={s.tileValue}>{value}</span>
      {sub && <span className={s.tileSub}>{sub}</span>}
    </div>
  );
}

function BandTooltip({ active, payload }: TooltipContentProps) {
  const r = payload?.[0]?.payload as PortfolioFile['income_bands'][number] | undefined;
  if (!active || !r) return null;
  return (
    <div className={s.tooltip}>
      <strong>Money in {r.income_band}</strong>
      <span>{count(r.accounts)} accounts</span>
      <span>
        <i className={s.key} style={{ background: COLORS.judges }} /> Judges' EI 55%: {pctValue(r.fail_6mo_ei55_pct)} fail 6
        months
      </span>
      <span>
        <i className={s.key} style={{ background: COLORS.reality }} /> Real 2026 EI cap: {pctValue(r.fail_6mo_ei55_cap2026_pct)}
      </span>
      <span>
        Median buffer: {r.median_B === null ? 'n/a' : money(r.median_B)} (
        {r.median_buffer_months === null ? 'n/a' : pyFixed(r.median_buffer_months, 1)} months)
      </span>
      <span>Median spending: {r.median_S === null ? 'n/a' : `${money(r.median_S)}/mo`}</span>
      <span className={s.tipHint}>Click to list these accounts</span>
    </div>
  );
}

/** The lift chart's three rankings: the light is the lead line; the judges' runway keeps its blue. */
const LIFT_SERIES = [
  { key: 'light', label: 'Early-warning light: most points, then lowest balance', color: COLORS.accent, dash: '', width: 3 },
  { key: 'ei55_runway', label: "Judges' EI 55% runway, shortest first", color: COLORS.judges, dash: DASH.reality, width: 2 },
  { key: 'buffer_months', label: 'Buffer months, fewest first', color: COLORS.plan, dash: DASH.base, width: 2 },
] as const;

function LiftTooltip({ active, payload }: TooltipContentProps) {
  const r = payload?.[0]?.payload as LiftRow | undefined;
  if (!active || !r) return null;
  return (
    <div className={s.tooltip}>
      <strong>
        {r.list_pct}% watch-list · {count(r.list_accounts)} accounts
      </strong>
      {LIFT_SERIES.map((x) => (
        <span key={x.key}>
          <i className={s.key} style={{ background: x.color }} /> {x.label}: {count(r[x.key])} of {count(r.events)}
        </span>
      ))}
    </div>
  );
}

interface CellBar {
  label: string;
  long: string;
  pct: number | null;
  err: [number, number];
  row: IrregularRow;
  compared: boolean;
}

function cellBars(rows: readonly IrregularRow[]): CellBar[] {
  return rows.map((r) => {
    const who = r.irregular_money_in === 'yes' ? 'Irregular' : 'Steady';
    const pct = r.rate === null ? null : r.rate * 100;
    const err: [number, number] =
      r.rate === null || r.ci_low === null || r.ci_high === null
        ? [0, 0]
        : [(r.rate - r.ci_low) * 100, (r.ci_high - r.rate) * 100];
    return {
      label: `${who} · ${r.judges_ei55}`,
      long: `${who} money in, ${r.judges_ei55} the judges' EI 55% test`,
      pct,
      err,
      row: r,
      compared: (r.irregular_money_in === 'yes') === (r.judges_ei55 === 'passes'),
    };
  });
}

function CellTooltip({ active, payload }: TooltipContentProps) {
  const b = payload?.[0]?.payload as CellBar | undefined;
  if (!active || !b) return null;
  const r = b.row;
  return (
    <div className={s.tooltip}>
      <strong>{b.long}</strong>
      <span>
        {count(r.went_overdrawn)} of {count(r.accounts)} went overdrawn
        {r.rate === null ? '' : ` (${pctValue(r.rate * 100)})`}
      </span>
      {r.ci_low !== null && r.ci_high !== null && (
        <span>
          95% interval {pyFixed(r.ci_low * 100, 1)}–{pctValue(r.ci_high * 100)}
        </span>
      )}
    </div>
  );
}

function SimpleTooltip({ active, payload, unit }: TooltipContentProps & { unit: string }) {
  const p = payload?.[0];
  if (!active || !p) return null;
  const row = p.payload as Record<string, string | number | null>;
  const label = String(Object.values(row)[0]);
  return (
    <div className={s.tooltip}>
      <strong>{label}</strong>
      <span>
        {typeof p.value === 'number' ? (unit === '%' ? pctValue(p.value) : count(p.value)) : 'n/a'}
        {unit === '%' ? '' : ` ${unit}`}
      </span>
      {'accounts' in row && unit === '%' && <span>of {count(Number(row.accounts))} accounts</span>}
    </div>
  );
}

export function Portfolio({ data, onOpen }: Props) {
  const reduced = usePrefersReducedMotion();
  const P = data.portfolio;
  const hl = P.headlines;
  const n = hl.accounts;
  const rows = useMemo(() => portfolioRows(data.accounts), [data.accounts]);
  const live = useMemo(
    () => ({ ei: rows.filter((r) => failsSix(r.ei)).length, cap: rows.filter((r) => failsSix(r.cap)).length }),
    [rows],
  );
  const [band, setBand] = useState<number | null>(null);
  const toggleBand = (i: number) => setBand(band === i ? null : i);
  // a click anywhere in a money-in band's column toggles that band's list. A bar handles its own click, so
  // the chart skips those; the column comes from where the click landed on the plot, because the hovered
  // index lags a tap behind on touch screens.
  const onBandColumn = (_st: unknown, e?: SyntheticEvent) => {
    if (!e || !(e.target instanceof Element) || e.target.closest('.recharts-bar-rectangle')) return;
    const plot = e.target.closest('.recharts-wrapper')?.querySelector('.recharts-cartesian-grid');
    const n = P.income_bands.length;
    const x = (e.nativeEvent as MouseEvent).clientX;
    if (!plot || !n || typeof x !== 'number') return;
    const r = plot.getBoundingClientRect();
    if (r.width <= 0 || x < r.left || x > r.right) return;
    toggleBand(Math.min(n - 1, Math.floor(((x - r.left) / r.width) * n)));
  };
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'ei', dir: 1 });

  const bandRows = useMemo(() => {
    if (band === null) return [];
    return rows
      .filter((r) => r.band === band)
      .sort((a, b) => {
        const d = sortValue(a, sort.key) - sortValue(b, sort.key);
        return (Number.isNaN(d) ? 0 : d) * sort.dir || a.id - b.id;
      });
  }, [rows, band, sort]);

  const bandTick = ({ x, y, payload }: XAxisTickContentProps) => {
    const i = INCOME_LABELS.indexOf(payload.value as (typeof INCOME_LABELS)[number]);
    const months = P.income_bands[i]?.median_buffer_months;
    const dollars = P.income_bands[i]?.median_B;
    return (
      <g transform={`translate(${Number(x)},${Number(y)})`}>
        <text textAnchor="middle" dy="1.12em" fill={COLORS.ink2} fontWeight={600}>
          {String(payload.value)}
        </text>
        <text textAnchor="middle" dy="2.4em" fill={COLORS.muted}>
          buffer {months === null || months === undefined ? 'n/a' : pyFixed(months, 1)} mo
        </text>
        <text textAnchor="middle" dy="3.69em" fill={COLORS.muted}>
          {dollars === null || dollars === undefined ? 'n/a' : kMoney(dollars)}
        </text>
      </g>
    );
  };

  const matches = live.ei === hl.fail_6mo_ei55 && live.cap === hl.fail_6mo_ei55_cap2026;
  const bands = P.income_bands;
  const lo = bands[0]?.fail_6mo_ei55_pct;
  const hi = bands[bands.length - 1]?.fail_6mo_ei55_pct;
  const ratio = lo && hi ? pyFixed(hi / lo, 0) : 'n/a';
  const cutRows = P.cut_histogram.filter((r) => !r.cut_as_share_of_spending.startsWith('already'));
  const cutPositive = cutRows.reduce((a, r) => a + r.accounts, 0);
  const cutEasy = cutRows
    .filter((r) => r.cut_as_share_of_spending === '<= 10%' || r.cut_as_share_of_spending === '10-25%')
    .reduce((a, r) => a + r.accounts, 0);
  const preloan = P.preloan_overdraft;
  const pre = (yes: string, col: string) => {
    const r = preloan.find((x) => x.overdrawn_before_loan === yes);
    const v = r?.[col];
    return typeof v === 'number' ? count(v) : '0';
  };
  const yesRow = preloan.find((x) => x.overdrawn_before_loan === 'yes');
  const preYesTotal = yesRow
    ? Object.values(yesRow).reduce<number>((a, v) => a + (typeof v === 'number' ? v : 0), 0)
    : 0;
  const E = P.evidence;
  const lines = evidenceLines(E);
  const lastLift = E.lift.length - 1;
  const head = E.lift.find((r) => r.list_pct === E.headline_list_pct);
  const liftStep = E.went_overdrawn <= 100 ? 25 : Math.ceil(E.went_overdrawn / 100) * 25;
  const liftTicks = Array.from({ length: Math.floor(E.went_overdrawn / liftStep) + 1 }, (_, i) => i * liftStep);
  if (liftTicks[liftTicks.length - 1] !== E.went_overdrawn) liftTicks.push(E.went_overdrawn);
  const cellTick = ({ x, y, payload }: XAxisTickContentProps) => {
    const [who, test] = String(payload.value).split(' · ');
    return (
      <g transform={`translate(${Number(x)},${Number(y)})`}>
        <text textAnchor="middle" dy="1.12em" fill={COLORS.ink2} fontWeight={600}>
          {who}
        </text>
        <text textAnchor="middle" dy="2.4em" fill={COLORS.muted}>
          {test} EI 55%
        </text>
      </g>
    );
  };
  const bars = cellBars(E.irregular);
  const irrRule = RULES.find((r) => r.code === 'inc_cv');
  const cellText = (irr: 'yes' | 'no', judges: 'passes' | 'fails') => {
    const r = E.irregular.find((x) => x.irregular_money_in === irr && x.judges_ei55 === judges);
    if (!r) return 'n/a';
    const share = r.rate === null ? '' : ` · ${pctValue(r.rate * 100)}`;
    const ci = r.ci_low === null || r.ci_high === null ? '' : ` (${pyFixed(r.ci_low * 100, 1)}–${pctValue(r.ci_high * 100)})`;
    return `${count(r.went_overdrawn)} of ${count(r.accounts)}${share}${ci}`;
  };

  return (
    <div className={s.portfolio}>
      <section className={s.tiles} aria-label="Headline numbers">
        <Tile
          label="Fail 6 months on EI 55%, judges' formula"
          value={pct1(hl.fail_6mo_ei55 / n)}
          sub={`${count(hl.fail_6mo_ei55)} of ${count(n)} accounts`}
        />
        <Tile
          label={`… with the real 2026 EI cap ($${count(hl.ei_cap_monthly_2026)}/mo)`}
          value={pct1(hl.fail_6mo_ei55_cap2026 / n)}
          sub={`${count(hl.fail_6mo_ei55_cap2026)} accounts · reality check`}
        />
        <Tile
          label="… on typical half-year spending"
          value={pct1(hl.fail_6mo_ei55_S6 / n)}
          sub={`${count(hl.fail_6mo_ei55_S6)} accounts · reality check`}
        />
        <Tile
          label="Median cut that rescues a failing customer"
          value={`${money(hl.median_min_cut_failing)}/mo`}
          sub="back to 6 months under the judges' EI twist"
        />
      </section>
      <p className={s.recheck} data-ok={matches ? 'true' : 'false'}>
        {matches ? '✓' : '!'} Recomputed in this browser by the TypeScript engine: {count(live.ei)} fail on the judges' EI 55%,{' '}
        {count(live.cap)} with the 2026 cap{matches ? ', the same as the Python engine.' : ': does NOT match the Python export.'}{' '}
        Other twists (judges' formula): Furnace dies {count(hl.fail_6mo_furnace)} · Job loss + bills +15%{' '}
        {count(hl.fail_6mo_double_whammy)}. Reality checks on EI 55%: pension kept {count(hl.fail_6mo_ei55_pension_aware)} · starting
        in January {count(hl.fail_6mo_ei55_january_path)}.
      </p>

      <section className={s.panel} aria-labelledby="lift-title">
        <h2 id="lift-title" className={s.h2}>
          1 · The judges' test misses people: who went overdrawn in {E.label_year}
        </h2>
        <p className={s.caption}>
          Every account rated at the {E.snapshot} snapshot and still active in {E.label_year} ({count(E.accounts)}), ranked
          by each score as it stood then. For a watch-list of each size: how many of the {count(E.went_overdrawn)} who
          went overdrawn in {E.label_year} it holds.
        </p>
        <ul className={s.legend} aria-label="Legend">
          {LIFT_SERIES.map((x) => (
            <li key={x.key}>
              <svg width="22" height="10" aria-hidden="true">
                <line x1="1" y1="5" x2="21" y2="5" stroke={x.color} strokeWidth={x.width} strokeDasharray={x.dash} />
              </svg>
              {x.label}
            </li>
          ))}
        </ul>
        <div className={s.chartTall}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={E.lift}
              margin={{ top: 16, right: 36, bottom: 8, left: 0 }}
              title={`Accounts that went overdrawn in ${E.label_year} caught by each watch-list size`}
              desc="One line per ranking in the legend. The left and right arrow keys step through the list sizes."
            >
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis
                dataKey="list_pct"
                type="number"
                domain={[E.lift[0]?.list_pct ?? 1, E.lift[lastLift]?.list_pct ?? 30]}
                ticks={[1, 5, 10, 15, 20, 25, 30]}
                tickFormatter={(v: number) => `${v}%`}
                tickLine={false}
                stroke={COLORS.axis}
                tick={{ fill: COLORS.muted }}
                label={{ value: 'watch-list size, % of the backtest accounts', position: 'insideBottom', offset: -4, fill: COLORS.muted }}
                height={44}
              />
              <YAxis
                domain={[0, E.went_overdrawn]}
                ticks={liftTicks}
                tickLine={false}
                axisLine={false}
                width="auto"
                tick={{ fill: COLORS.muted }}
              />
              <Tooltip content={LiftTooltip} cursor={{ stroke: COLORS.axis, strokeWidth: 1 }} isAnimationActive={false} />
              <ReferenceLine
                x={E.headline_list_pct}
                stroke={COLORS.axis}
                strokeDasharray="3 3"
                label={{ value: `${E.headline_list_pct}% list`, position: 'insideTopLeft', fill: COLORS.muted }}
              />
              {LIFT_SERIES.map((x) => (
                <Line
                  key={x.key}
                  type="linear"
                  dataKey={x.key}
                  name={x.label}
                  stroke={x.color}
                  strokeWidth={x.width}
                  strokeDasharray={x.dash}
                  dot={false}
                  activeDot={{ r: 5, stroke: COLORS.surface, strokeWidth: 2 }}
                  isAnimationActive={!reduced}
                  animationDuration={500}
                />
              ))}
              {head &&
                LIFT_SERIES.map((x) => (
                  <ReferenceDot
                    key={x.key}
                    x={head.list_pct}
                    y={head[x.key]}
                    r={4}
                    fill={x.color}
                    stroke={COLORS.surface}
                    strokeWidth={2}
                    label={{ value: count(head[x.key]), position: 'left', fill: COLORS.ink, fontWeight: 700 }}
                  />
                ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className={s.caption}>
          <strong>{lines.passed}</strong> {lines.lift} Every score reads the same full months as the light; the light is a
          watch flag beside the runway, not a credit score.
        </p>
        <details className={s.numbers}>
          <summary>Show the numbers</summary>
          <div className={s.tableScroll}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th scope="col">Watch-list</th>
                  <th scope="col" className={s.r}>
                    Accounts
                  </th>
                  {LIFT_SERIES.map((x) => (
                    <th key={x.key} scope="col" className={s.r}>
                      {x.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {E.lift.map((r) => (
                  <tr key={r.list_pct}>
                    <th scope="row">{r.list_pct}%</th>
                    <td className={s.r}>{count(r.list_accounts)}</td>
                    {LIFT_SERIES.map((x) => (
                      <td key={x.key} className={s.r}>
                        {count(r[x.key])} of {count(r.events)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section className={s.panel} aria-labelledby="irregular-title">
        <h2 id="irregular-title" className={s.h2}>
          2 · A second finding: irregular money in
        </h2>
        <p className={s.caption}>
          Share that went overdrawn in {E.label_year}, by irregular money in (the light's rule
          {irrRule ? `: ${irrRule.firesWhen}` : ''}, over its {WINDOW_ROWS} months) and the judges' EI 55% test at the
          snapshot, with 95% intervals.
        </p>
        <div className={s.chart}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={bars}
              margin={{ top: 16, right: 8, bottom: 8, left: 0 }}
              title={`Share that went overdrawn in ${E.label_year}, by irregular money in and the judges' EI 55% test`}
              desc="One bar per group, with its 95% interval. The left and right arrow keys step through the groups."
            >
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis dataKey="label" tickLine={false} stroke={COLORS.axis} tick={cellTick} interval={0} height={48} />
              <YAxis
                tickFormatter={(v: number) => `${v}%`}
                tickLine={false}
                axisLine={false}
                width="auto"
                tick={{ fill: COLORS.muted }}
              />
              <Tooltip content={CellTooltip} cursor={{ fill: COLORS.cursor }} isAnimationActive={false} />
              <Bar dataKey="pct" radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={!reduced} animationDuration={500}>
                {bars.map((b) => (
                  <Cell key={b.label} fill={b.compared ? COLORS.accent : COLORS.histIn} />
                ))}
                <ErrorBar dataKey="err" width={8} strokeWidth={1.5} stroke={COLORS.ink2} direction="y" />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className={s.twoByTwo}>
          <table className={s.table}>
            <thead>
              <tr>
                <th scope="col">Money in</th>
                <th scope="col" className={s.r}>
                  Passes EI 55%
                </th>
                <th scope="col" className={s.r}>
                  Fails EI 55%
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Irregular</th>
                <td className={s.r}>
                  <strong>{cellText('yes', 'passes')}</strong>
                </td>
                <td className={s.r}>{cellText('yes', 'fails')}</td>
              </tr>
              <tr>
                <th scope="row">Steady</th>
                <td className={s.r}>{cellText('no', 'passes')}</td>
                <td className={s.r}>
                  <strong>{cellText('no', 'fails')}</strong>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className={s.caption}>
          {lines.irregular} {lines.irregular_caveat}
        </p>
      </section>

      <section className={s.panel} aria-labelledby="bands-title">
        <h2 id="bands-title" className={s.h2}>
          3 · The more money comes in, the thinner the cushion
        </h2>
        <p className={s.caption}>
          Share of each monthly money-in band that can't last 6 months. Click a band (or use the buttons) to list its
          accounts.
        </p>
        <ul className={s.legend} aria-label="Legend">
          <li>
            <i className={s.key} style={{ background: COLORS.judges }} /> Judges' EI 55%
          </li>
          <li>
            <i className={s.key} style={{ background: COLORS.reality }} /> Real 2026 EI cap (reality check)
          </li>
        </ul>
        <div className={s.chartTall}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={P.income_bands}
              margin={{ top: 24, right: 8, bottom: 8, left: 0 }}
              barGap={14}
              barCategoryGap="18%"
              style={{ cursor: 'pointer' }}
              onClick={onBandColumn}
              title="Share of each monthly money-in band that can't last 6 months"
              desc="Two bars per band: the judges' EI 55% and the real 2026 EI cap. The left and right arrow keys step through the bands."
            >
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis dataKey="income_band" tick={bandTick} tickLine={false} stroke={COLORS.axis} interval={0} height={68} />
              <YAxis
                domain={[0, 100]}
                ticks={[0, 25, 50, 75, 100]}
                tickFormatter={(v: number) => `${v}%`}
                tickLine={false}
                axisLine={false}
                width="auto"
                tick={{ fill: COLORS.muted }}
              />
              <Tooltip content={BandTooltip} cursor={{ fill: COLORS.cursor }} isAnimationActive={false} />
              <Bar
                dataKey="fail_6mo_ei55_pct"
                name="Judges' EI 55%"
                fill={COLORS.judges}
                radius={[4, 4, 0, 0]}
                maxBarSize={28}
                isAnimationActive={!reduced}
                animationDuration={500}
                onClick={(_, i) => toggleBand(i)}
              >
                {P.income_bands.map((b, i) => (
                  <Cell key={b.income_band} fillOpacity={band === null || band === i ? 1 : 0.35} />
                ))}
                <LabelList
                  dataKey="fail_6mo_ei55_pct"
                  position="top"
                  fill={COLORS.ink2}
                  formatter={(v) => (typeof v === 'number' ? pctValue(v) : '')}
                />
              </Bar>
              <Bar
                dataKey="fail_6mo_ei55_cap2026_pct"
                name="Real 2026 EI cap"
                fill={COLORS.reality}
                radius={[4, 4, 0, 0]}
                maxBarSize={28}
                isAnimationActive={!reduced}
                animationDuration={500}
                onClick={(_, i) => toggleBand(i)}
              >
                {P.income_bands.map((b, i) => (
                  <Cell key={b.income_band} fillOpacity={band === null || band === i ? 1 : 0.35} />
                ))}
                <LabelList
                  dataKey="fail_6mo_ei55_cap2026_pct"
                  position="top"
                  fill={COLORS.ink2}
                  formatter={(v) => (typeof v === 'number' ? pctValue(v) : '')}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className={s.bandButtons} role="group" aria-label="List the accounts in a band">
          {P.income_bands.map((b, i) => (
            <button
              key={b.income_band}
              type="button"
              className={s.bandBtn}
              aria-pressed={band === i}
              onClick={() => setBand(band === i ? null : i)}
            >
              {b.income_band} <span className={s.bandCount}>{count(b.accounts)}</span>
            </button>
          ))}
        </div>
        <p className={s.caption}>
          Under the judges' own EI twist the top band fails {ratio}× as often as the bottom; under the real 2026 cap
          almost all of it fails. {P.lines.cushion}
        </p>
        <details className={s.numbers}>
          <summary>Show the numbers</summary>
          <div className={s.tableScroll}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th scope="col">Money in / mo</th>
                  <th scope="col" className={s.r}>
                    Accounts
                  </th>
                  <th scope="col" className={s.r}>
                    Fail, judges' EI 55%
                  </th>
                  <th scope="col" className={s.r}>
                    Fail, 2026 EI cap
                  </th>
                  <th scope="col" className={s.r}>
                    Median buffer
                  </th>
                  <th scope="col" className={s.r}>
                    Median spending / mo
                  </th>
                  <th scope="col" className={s.r}>
                    Buffer (months)
                  </th>
                </tr>
              </thead>
              <tbody>
                {bands.map((b) => (
                  <tr key={b.income_band}>
                    <th scope="row">{b.income_band}</th>
                    <td className={s.r}>{count(b.accounts)}</td>
                    <td className={s.r}>{pctValue(b.fail_6mo_ei55_pct)}</td>
                    <td className={s.r}>{pctValue(b.fail_6mo_ei55_cap2026_pct)}</td>
                    <td className={s.r}>{b.median_B === null ? 'n/a' : money(b.median_B)}</td>
                    <td className={s.r}>{b.median_S === null ? 'n/a' : money(b.median_S)}</td>
                    <td className={s.r}>{b.median_buffer_months === null ? 'n/a' : pyFixed(b.median_buffer_months, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>

        {band !== null && (
          <div className={s.drill}>
            <div className={s.drillHead}>
              <h3 className={s.h3}>
                Money in {INCOME_LABELS[band]}: {count(bandRows.length)} accounts
              </h3>
              <span className={s.caption}>Click an account to open it in the live twist on the Laid off: EI 55% card.</span>
              <button type="button" className={s.close} onClick={() => setBand(null)}>
                Close list
              </button>
            </div>
            <div className={s.tableScroll}>
              <table className={s.table}>
                <thead>
                  <tr>
                    {COLUMNS.map((c) => (
                      <th
                        key={c.key}
                        scope="col"
                        aria-sort={sort.key === c.key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}
                        className={c.key === 'id' ? undefined : s.r}
                      >
                        <button
                          type="button"
                          className={s.sortBtn}
                          onClick={() =>
                            setSort((cur) => ({ key: c.key, dir: cur.key === c.key ? ((cur.dir * -1) as 1 | -1) : 1 }))
                          }
                        >
                          {c.label}
                          <span aria-hidden="true">{sort.key === c.key ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''}</span>
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {bandRows.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <button type="button" className={s.openBtn} onClick={() => onOpen(r.id, 'ei')}>
                          {r.id}
                        </button>
                      </td>
                      <td className={s.r}>{money(r.I)}</td>
                      <td className={s.r}>{money(r.B)}</td>
                      <td className={s.r}>{r.bufferMonths === null ? 'n/a' : pyFixed(r.bufferMonths, 1)}</td>
                      <td className={s.r} data-fail={failsSix(r.ei) ? 'true' : undefined}>
                        {rwText(r.ei)}
                      </td>
                      <td className={s.r} data-fail={failsSix(r.cap) ? 'true' : undefined}>
                        {rwText(r.cap)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className={s.caption}>Bold red = under 6 months.</p>
          </div>
        )}
      </section>

      <div className={s.twoUp}>
        <section className={s.panel} aria-labelledby="s6-title">
          <h2 id="s6-title" className={s.h2}>
            4 · A typical month isn't a typical half-year
          </h2>
          <p className={s.caption}>
            Accounts the judges' formula calls safe, grouped by their judges' EI runway, re-run on each account's own
            typical half-year spending: share that still fail 6 months (reality check).
          </p>
          <div className={s.chart}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={P.s6_calibration}
                margin={{ top: 24, right: 8, bottom: 8, left: 0 }}
                title="Accounts the judges call safe that still fail 6 months on typical half-year spending"
                desc="One bar per judges' EI runway group. The left and right arrow keys step through the groups."
              >
                <CartesianGrid stroke={COLORS.grid} vertical={false} />
                <XAxis
                  dataKey="judge_runway_months"
                  tickLine={false}
                  stroke={COLORS.axis}
                  tick={{ fill: COLORS.ink2 }}
                  interval={0}
                  tickFormatter={(v: string) => (v.startsWith('no shortfall') ? '120+' : v)}
                  label={{ value: "judges' EI runway (months)", position: 'insideBottom', offset: -4, fill: COLORS.muted }}
                  height={44}
                />
                <YAxis
                  domain={[0, 100]}
                  ticks={[0, 25, 50, 75, 100]}
                  tickFormatter={(v: number) => `${v}%`}
                  tickLine={false}
                  axisLine={false}
                  width="auto"
                  tick={{ fill: COLORS.muted }}
                />
                <Tooltip
                  content={(p: TooltipContentProps) => <SimpleTooltip {...p} unit="%" />}
                  cursor={{ fill: COLORS.cursor }}
                  isAnimationActive={false}
                />
                <Bar dataKey="fail_6mo_on_S6_pct" fill={COLORS.reality} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={!reduced} animationDuration={500}>
                  <LabelList
                    dataKey="fail_6mo_on_S6_pct"
                    position="top"
                    fill={COLORS.ink2}
                    formatter={(v) => (typeof v === 'number' ? pctValue(v) : '')}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className={s.caption}>
            Spending is lumpy: a few costly months a year that a median month never sees. The 6-8 band is the grey zone
            shown on the live twist.
          </p>
          <p className={s.caption}>
            Calendar caveat: here spending peaks in January and June, a pattern already in the original PKDD'99 Czech
            data before it was re-dated, so it says nothing about Canadian seasons.
          </p>
          <p className={s.caption}>{lines.s6}</p>
        </section>

        <section className={s.panel} aria-labelledby="cut-title">
          <h2 id="cut-title" className={s.h2}>
            5 · Most failing customers are one moderate change away
          </h2>
          <p className={s.caption}>
            Accounts that fail 6 months on the judges' EI 55%, by the monthly cut that gets them back to 6 months, as a
            share of their spending.
          </p>
          <div className={s.chart}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={P.cut_histogram}
                margin={{ top: 24, right: 8, bottom: 8, left: 0 }}
                title="Failing accounts by the monthly cut that gets them back to 6 months"
                desc="One bar per cut size, as a share of spending. The left and right arrow keys step through the cut sizes."
              >
                <CartesianGrid stroke={COLORS.grid} vertical={false} />
                <XAxis
                  dataKey="cut_as_share_of_spending"
                  tickLine={false}
                  stroke={COLORS.axis}
                  tick={{ fill: COLORS.ink2 }}
                  interval={0}
                  tickFormatter={(v: string) => (v.startsWith('already') ? 'overdrawn' : v)}
                  label={{ value: 'cut needed, % of spending', position: 'insideBottom', offset: -4, fill: COLORS.muted }}
                  height={44}
                />
                <YAxis tickLine={false} axisLine={false} width="auto" tick={{ fill: COLORS.muted }} />
                <Tooltip
                  content={(p: TooltipContentProps) => <SimpleTooltip {...p} unit="accounts" />}
                  cursor={{ fill: COLORS.cursor }}
                  isAnimationActive={false}
                />
                <Bar dataKey="accounts" fill={COLORS.judges} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={!reduced} animationDuration={500}>
                  <LabelList dataKey="accounts" position="top" fill={COLORS.ink2} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className={s.caption}>
            {count(cutEasy)} of {count(cutPositive)} failing customers with a positive buffer get back to 6 months by
            cutting a quarter of spending or less. {P.lines.realistic_cuts} "Overdrawn" accounts have no buffer to
            protect.
          </p>
        </section>
      </div>

      <section className={s.panel} aria-labelledby="preloan-title">
        <h2 id="preloan-title" className={s.h2}>
          6 · Overdrawn before the loan: a red flag, built into the loan labels
        </h2>
        <div className={s.twoByTwo}>
          <table className={s.table}>
            <thead>
              <tr>
                <th scope="col">Overdrawn before the loan</th>
                <th scope="col" className={s.r}>
                  Defaulted (B/D)
                </th>
                <th scope="col" className={s.r}>
                  Repaid or on track (A/C)
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">No</th>
                <td className={s.r}>{pre('no', 'defaulted (B/D)')}</td>
                <td className={s.r}>{pre('no', 'repaid or on track (A/C)')}</td>
              </tr>
              <tr>
                <th scope="row">Yes</th>
                <td className={`${s.r} ${s.hot}`}>{pre('yes', 'defaulted (B/D)')}</td>
                <td className={s.r}>{pre('yes', 'repaid or on track (A/C)')}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className={s.caption}>
          {pre('yes', 'defaulted (B/D)')} of {count(preYesTotal)} borrowers who were overdrawn before their loan are
          labelled defaulted; none of the {pre('no', 'repaid or on track (A/C)')} who repaid or are on track was
          overdrawn before it. That is built into how this dataset labels loans (CTU's published rule: if
          min(trans.balance) &gt;= 0 then good else bad), so it is a red flag on the customer card, not evidence.
        </p>
      </section>
    </div>
  );
}
