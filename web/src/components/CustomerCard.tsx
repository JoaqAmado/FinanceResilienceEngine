import { useMemo } from 'react';
import { Bar, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TooltipContentProps } from 'recharts';
import { accountFlags, pyFixed, runwayLabel } from '../engine';
import type { Account, RunwayResult } from '../engine';
import { COLORS } from '../lib/colors';
import { axisMoney, money } from '../lib/format';
import { useHistory } from '../lib/load';
import s from './CustomerCard.module.css';
import ui from './ui.module.css';

const FLAG_TITLE: Record<string, string> = {
  overdrawn: 'Overdrawn',
  no_income: 'No income',
  no_spending: 'No spending',
  bills_by_standing_order: 'Bills by standing order',
  no_bills: 'No bills recorded',
  stale: 'Stale account',
  short_history: 'Short history',
  minor_owner: 'Owner under 18',
  pension: 'Pension',
  loan_trouble: 'Loan in arrears or default',
  pre_loan_overdraft: 'Overdrawn before the loan',
  been_negative: 'Has been negative',
};

const SERIOUS = new Set(['overdrawn', 'loan_trouble', 'pre_loan_overdraft']);

interface HistRow {
  month: string;
  moneyIn: number;
  moneyOut: number;
  balance: number;
}

function HistTooltip({ active, payload }: TooltipContentProps) {
  const r = payload?.[0]?.payload as HistRow | undefined;
  if (!active || !r) return null;
  return (
    <div className={s.tooltip}>
      <strong>{r.month}</strong>
      <span>Money in {money(r.moneyIn)}</span>
      <span>Money out {money(-r.moneyOut)}</span>
      <span>Month-end balance {money(r.balance)}</span>
    </div>
  );
}

function HistoryChart({ id }: { id: number }) {
  const { history, error } = useHistory(id);
  const rows = useMemo<HistRow[]>(
    () =>
      history
        ? history.month.map((m, i) => ({
            month: m,
            moneyIn: history.money_in[i],
            moneyOut: -history.money_out[i],
            balance: history.month_end_balance[i],
          }))
        : [],
    [history],
  );
  if (error) return <p className={s.histMsg}>Month history unavailable ({error}).</p>;
  if (!history) return <div className={`${s.histChart} ${ui.skeleton}`} aria-busy="true" aria-label="Loading month history" />;
  const years = rows.filter((r) => r.month.endsWith('-01')).map((r) => r.month);
  return (
    <figure className={s.hist}>
      <figcaption className={s.histCap}>
        <span>
          <svg width="12" height="10" aria-hidden="true">
            <rect width="12" height="10" rx="2" fill={COLORS.histIn} />
          </svg>{' '}
          money in
        </span>
        <span>
          <svg width="12" height="10" aria-hidden="true">
            <rect width="12" height="10" rx="2" fill={COLORS.histOut} />
          </svg>{' '}
          money out
        </span>
        <span>
          <svg width="18" height="10" aria-hidden="true">
            <line x1="1" y1="5" x2="17" y2="5" stroke={COLORS.histBalance} strokeWidth="2.5" />
          </svg>{' '}
          month-end balance
        </span>
      </figcaption>
      <div className={s.histChart}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} stackOffset="sign" margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <XAxis
              dataKey="month"
              ticks={years}
              tickFormatter={(m: string) => m.slice(0, 4)}
              tickLine={false}
              stroke={COLORS.axis}
              tick={{ fill: COLORS.muted }}
              interval={0}
              height={22}
            />
            <YAxis tickFormatter={axisMoney} width={54} tickLine={false} axisLine={false} tick={{ fill: COLORS.muted }} />
            <Tooltip content={HistTooltip} isAnimationActive={false} />
            <Bar dataKey="moneyIn" stackId="flow" fill={COLORS.histIn} isAnimationActive={false} />
            <Bar dataKey="moneyOut" stackId="flow" fill={COLORS.histOut} isAnimationActive={false} />
            <Line
              type="linear"
              dataKey="balance"
              stroke={COLORS.histBalance}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className={s.metric}>
      <span className={s.mLabel}>{label}</span>
      <span className={s.mValue}>{value}</span>
      {sub && <span className={s.mSub}>{sub}</span>}
    </div>
  );
}

export function CustomerCard({ acct, baseline }: { acct: Account; baseline: RunwayResult }) {
  const flags = accountFlags(acct);
  const bufferMonths = acct.S > 0 ? `${pyFixed(acct.B / acct.S, 1)} months of spending` : undefined;
  const owner =
    acct.owner_age !== null ? `owner ${pyFixed(acct.owner_age, 0)}, ${acct.owner_gender ?? '?'}` : 'owner unknown';
  return (
    <section className={s.panel} aria-labelledby="customer-title">
      <div className={s.head}>
        <h2 id="customer-title" className={s.eyebrow}>
          Know the customer · account {acct.id}
        </h2>
        <span className={s.meta}>
          {acct.months_of_data} months of history ({acct.first_month} to {acct.last_month}) · {owner} · loan:{' '}
          {acct.loan_status ?? 'none'}
        </span>
      </div>
      <div className={s.metrics}>
        <Metric label="Money in (I) / mo" value={money(acct.I)} />
        <Metric label="Spending (S) / mo" value={money(acct.S)} />
        <Metric label="Buffer (B)" value={money(acct.B)} sub={bufferMonths} />
        <Metric
          label="Runway today (months)"
          value={baseline.noShortfall ? '120+' : runwayLabel(baseline)}
          sub={baseline.noShortfall ? 'no shortfall' : undefined}
        />
        <Metric label="Fixed costs (F) / mo" value={money(acct.F)} />
        <Metric label="Household bills (H) / mo" value={money(acct.H)} />
        <Metric label="Loan payment (P) / mo" value={money(acct.P)} />
        <Metric label="Pension (median) / mo" value={money(acct.Pn)} />
      </div>
      {flags.length > 0 && (
        <ul className={s.flags} aria-label="Read these first">
          {flags.map(([code, text]) => (
            <li key={code} className={`${s.flag} ${SERIOUS.has(code) ? s.serious : code === 'pension' ? s.infoFlag : ''}`}>
              <span className={s.flagIcon} aria-hidden="true">
                {code === 'pension' ? 'i' : '!'}
              </span>
              <span>
                <strong>{FLAG_TITLE[code] ?? code}.</strong> {text}
              </span>
            </li>
          ))}
        </ul>
      )}
      <HistoryChart id={acct.id} />
    </section>
  );
}
