import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { TooltipContentProps, XAxisTickContentProps } from 'recharts';
import { pyFixed } from '../engine';
import type { PortfolioFile } from '../engine';
import { COLORS } from '../lib/colors';
import { count, money, monthsOf, pct1, pctValue, rwText } from '../lib/format';
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
      <span>Median buffer: {r.median_buffer_months === null ? 'n/a' : pyFixed(r.median_buffer_months, 1)} months</span>
      <span className={s.tipHint}>Click to list these accounts</span>
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
  const P = data.portfolio;
  const hl = P.headlines;
  const n = hl.accounts;
  const rows = useMemo(() => portfolioRows(data.accounts), [data.accounts]);
  const live = useMemo(
    () => ({ ei: rows.filter((r) => failsSix(r.ei)).length, cap: rows.filter((r) => failsSix(r.cap)).length }),
    [rows],
  );
  const [band, setBand] = useState<number | null>(null);
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
    return (
      <g transform={`translate(${Number(x)},${Number(y)})`}>
        <text textAnchor="middle" dy={14} fill={COLORS.ink2} fontWeight={600}>
          {String(payload.value)}
        </text>
        <text textAnchor="middle" dy={30} fill={COLORS.muted}>
          buffer {months === null || months === undefined ? 'n/a' : pyFixed(months, 1)} mo
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

      <section className={s.panel} aria-labelledby="bands-title">
        <h2 id="bands-title" className={s.h2}>
          1 · The more money comes in, the thinner the cushion
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
            <BarChart data={P.income_bands} margin={{ top: 24, right: 8, bottom: 8, left: 0 }} barGap={8} barCategoryGap="18%">
              <CartesianGrid stroke={COLORS.grid} vertical={false} />
              <XAxis dataKey="income_band" tick={bandTick} tickLine={false} stroke={COLORS.axis} interval={0} height={48} />
              <YAxis
                domain={[0, 100]}
                ticks={[0, 25, 50, 75, 100]}
                tickFormatter={(v: number) => `${v}%`}
                tickLine={false}
                axisLine={false}
                width={44}
                tick={{ fill: COLORS.muted }}
              />
              <Tooltip content={BandTooltip} cursor={{ fill: 'rgba(15,23,42,0.05)' }} isAnimationActive={false} />
              <Bar
                dataKey="fail_6mo_ei55_pct"
                name="Judges' EI 55%"
                fill={COLORS.judges}
                radius={[4, 4, 0, 0]}
                maxBarSize={28}
                animationDuration={500}
                onClick={(_, i) => setBand(i)}
                style={{ cursor: 'pointer' }}
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
                animationDuration={500}
                onClick={(_, i) => setBand(i)}
                style={{ cursor: 'pointer' }}
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
          almost all of it fails. Spending scales with money in; the buffer doesn't.
        </p>

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
            2 · A typical month isn't a typical half-year
          </h2>
          <p className={s.caption}>
            Accounts the judges' formula calls safe, grouped by their judges' EI runway, re-run on each account's own
            typical half-year spending: share that still fail 6 months (reality check).
          </p>
          <div className={s.chart}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={P.s6_calibration} margin={{ top: 24, right: 8, bottom: 8, left: 0 }}>
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
                  width={44}
                  tick={{ fill: COLORS.muted }}
                />
                <Tooltip
                  content={(p: TooltipContentProps) => <SimpleTooltip {...p} unit="%" />}
                  cursor={{ fill: 'rgba(15,23,42,0.05)' }}
                  isAnimationActive={false}
                />
                <Bar dataKey="fail_6mo_on_S6_pct" fill={COLORS.reality} radius={[4, 4, 0, 0]} maxBarSize={28} animationDuration={500}>
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
            Spending peaks in January and June, which a median month never sees. The 6-8 band is the grey zone shown on
            the live twist.
          </p>
        </section>

        <section className={s.panel} aria-labelledby="cut-title">
          <h2 id="cut-title" className={s.h2}>
            3 · Most failing customers are one moderate change away
          </h2>
          <p className={s.caption}>
            Accounts that fail 6 months on the judges' EI 55%, by the monthly cut that gets them back to 6 months, as a
            share of their spending.
          </p>
          <div className={s.chart}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={P.cut_histogram} margin={{ top: 24, right: 8, bottom: 8, left: 0 }}>
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
                <YAxis tickLine={false} axisLine={false} width={44} tick={{ fill: COLORS.muted }} />
                <Tooltip
                  content={(p: TooltipContentProps) => <SimpleTooltip {...p} unit="accounts" />}
                  cursor={{ fill: 'rgba(15,23,42,0.05)' }}
                  isAnimationActive={false}
                />
                <Bar dataKey="accounts" fill={COLORS.judges} radius={[4, 4, 0, 0]} maxBarSize={28} animationDuration={500}>
                  <LabelList dataKey="accounts" position="top" fill={COLORS.ink2} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className={s.caption}>
            {count(cutEasy)} of {count(cutPositive)} failing customers with a positive buffer get back to 6 months by
            cutting a quarter of spending or less. "Overdrawn" accounts have no buffer to protect.
          </p>
        </section>
      </div>

      <section className={s.panel} aria-labelledby="preloan-title">
        <h2 id="preloan-title" className={s.h2}>
          4 · Overdrawn before the loan → default, every time (in this data)
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
          {pre('yes', 'defaulted (B/D)')} of {count(preYesTotal)} borrowers who were overdrawn before their loan
          defaulted; none of the {pre('no', 'repaid or on track (A/C)')} who repaid or are on track was overdrawn before
          it. Small sample, and loan status looks tied to overdraft by construction: a red flag on the customer card,
          not a rule.
        </p>
      </section>
    </div>
  );
}
