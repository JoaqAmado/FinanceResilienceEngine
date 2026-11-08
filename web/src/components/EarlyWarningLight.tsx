import { backtestCaption, pyFixed, tierRateText } from '../engine';
import type { Backtest, Light } from '../engine';
import card from './CustomerCard.module.css';
import s from './EarlyWarningLight.module.css';

/**
 * The early-warning light on the customer card: one flag-style line beside the warning flags, and the
 * 4 rules plus the backtest tiers behind a disclosure. A watch flag, not a credit score; it never
 * changes the judges' runway. Every string comes from the engine (src/engine/warning.ts).
 */
export function EarlyWarningLight({ light, backtest }: { light: Light; backtest: Backtest }) {
  // app.py: st.warning at 2+ points, st.info otherwise
  const warn = light.points !== null && light.points >= 2;
  return (
    <div className={s.light}>
      <p className={`${card.flag} ${warn ? '' : card.infoFlag}`} data-testid="early-warning-line">
        <span className={card.flagIcon} aria-hidden="true">
          {light.points ?? 'i'}
        </span>
        {light.points !== null ? (
          <span>
            <strong>{light.badge}:</strong> {light.why}. {light.backtestLine}
          </span>
        ) : (
          <span>
            <strong>Early-warning light:</strong> {light.backtestLine}
          </span>
        )}
      </p>
      <details className={s.details}>
        <summary>Early-warning light · the 4 rules (a watch flag beside the runway, not a credit score)</summary>
        <div className={s.body}>
          {light.rules.length > 0 && (
            <div className={s.scroll}>
              <table>
                <thead>
                  <tr>
                    <th scope="col">Rule</th>
                    <th scope="col">This account</th>
                    <th scope="col">Fires when</th>
                    <th scope="col">Fired</th>
                  </tr>
                </thead>
                <tbody>
                  {light.rules.map((r) => (
                    <tr key={r.rule.code}>
                      <th scope="row">{r.rule.label}</th>
                      <td>{r.valueText}</td>
                      <td>{r.rule.firesWhen}</td>
                      <td className={r.fired ? s.fired : s.notFired}>{r.fired ? '! fired' : 'not fired'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {light.spendingNote && (
            <p className={s.caption} data-testid="early-warning-spending">
              {light.spendingNote}
            </p>
          )}
          <div className={s.scroll}>
            <table>
              <thead>
                <tr>
                  <th scope="col">Points</th>
                  <th scope="col">Accounts</th>
                  <th scope="col">Went overdrawn in {backtest.labelYear}</th>
                  <th scope="col">Share</th>
                </tr>
              </thead>
              <tbody>
                {backtest.tiers.map((t) => {
                  const mine = light.tier?.points === t.points;
                  return (
                    <tr key={t.points} className={mine ? s.mine : undefined} aria-current={mine ? 'true' : undefined}>
                      <th scope="row">
                        {t.points}
                        {mine && <span className={s.mineTag}> this account</span>}
                      </th>
                      <td>{pyFixed(t.accounts, 0, true)}</td>
                      <td>{pyFixed(t.wentOverdrawn, 0, true)}</td>
                      <td>{tierRateText(t)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className={s.caption}>{backtestCaption(backtest)}</p>
        </div>
      </details>
    </div>
  );
}
