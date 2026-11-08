import s from './Method.module.css';

/** Definitions, limits and sources: docs/model_card.md ("Data and limits"), the README's "Sources", and app.py's method tab. */
export function Method() {
  return (
    <div className={s.method}>
      <section className={s.panel} aria-labelledby="m-judges">
        <h2 id="m-judges" className={s.h2}>
          The judges' numbers
        </h2>
        <p>
          Every number comes from <code>monthly_summary.csv</code> using the track brief's definitions:
        </p>
        <dl className={s.defs}>
          <dt>I</dt>
          <dd>typical monthly money in: median of money in</dd>
          <dt>F</dt>
          <dd>typical fixed costs: median of household bills + insurance + loan payments</dd>
          <dt>S</dt>
          <dd>typical monthly spending: median of money out</dd>
          <dt>B</dt>
          <dd>buffer: mean average daily balance over the last 6 months</dd>
          <dt>H</dt>
          <dd>household bills: median of household bills</dd>
          <dt>P</dt>
          <dd>loan payment, if the loan is still running at the end of 2025</dd>
        </dl>
        <div className={s.formula}>
          Runway = (B − one-off) ÷ (spending after − income after)
          <ul>
            <li>0 if the buffer is gone (B − one-off ≤ 0)</li>
            <li>"no shortfall (120+)" if there is no gap</li>
            <li>capped at 120 months and rounded to 1 decimal, exactly as numpy rounds (ties to even)</li>
          </ul>
        </div>
        <p>
          Twist cards: EI 55% → income = 0.55 × I · bills +15% → spending = S + 0.15 × H · furnace → one-off = 1 × S.
          Custom starts from no shock, so only the levers you set change anything.
        </p>
      </section>

      <section className={s.panel} aria-labelledby="m-reality">
        <h2 id="m-reality" className={s.h2}>
          Reality checks (labelled, never replacing the judges' number)
        </h2>
        <ul className={s.list}>
          <li>2026 EI maximum: $729/week ≈ $3,159/month (canada.ca)</li>
          <li>the one-week EI waiting period</li>
          <li>pensions kept on a job loss</li>
          <li>typical half-year spending (median 6-month spend ÷ 6)</li>
          <li>a month-by-month path from January, using each account's own calendar-month spending</li>
          <li>household bills paid by standing order</li>
        </ul>
        <p>
          Plans: a job-loss-proof emergency fund (the buffer that passes the shock under the judges' formula) and a
          minimum-pain backup ladder: drop bank fees, cut non-fixed spending 10% then 25%, pause other standing orders,
          defer the running loan, cut 50%, else credit. Loans already in arrears or default get no credit advice.
        </p>
      </section>

      <section className={s.panel} aria-labelledby="m-limits">
        <h2 id="m-limits" className={s.h2}>
          Data and limits
        </h2>
        <ul className={s.list}>
          <li>
            <strong>Checks:</strong> the monthly components add up exactly to money in and money out, on all 185,326
            rows.
          </li>
          <li>
            <strong>Provenance:</strong> PKDD'99 Czech bank data, re-dated to 2020–2025 and expressed in CAD. That's why
            the EI-cap view is a stress test, not a forecast.
          </li>
          <li>
            <strong>What the columns hold:</strong> "money in" is all inflows (74.9% cash deposits), and 76.4% of
            spending is cash withdrawals of unknown purpose, so the plans call it <em>non-fixed</em>, not{' '}
            <em>discretionary</em>.
          </li>
          <li>
            <strong>Edge cases are flagged on the customer card, not hidden:</strong> negative buffer (23 accounts), zero
            median income (14), zero median spending (77), no recorded household bills (1,225), accounts that stop
            before Dec 2025 (76).
          </li>
        </ul>
      </section>

      <section className={s.panel} aria-labelledby="m-web">
        <h2 id="m-web" className={s.h2}>
          How this page computes
        </h2>
        <p>
          The engine runs in your browser: a TypeScript port of the Python engine (<code>resilience/core.py</code> and{' '}
          <code>narrative.py</code>), so any twist card works live and offline. A parity test checks the port against
          about 1.26 million outputs exported from the Python engine (every account's runway under 13 shocks, plus
          plans and stories on a sample of accounts), and every runway, flag, plan step and story string must match
          exactly. The page loads one data file of the 4,500 accounts' inputs at full precision, and
          each account's month history only when it is opened. No keys, no network calls beyond this page's own files.
        </p>
      </section>

      <section className={s.panel} aria-labelledby="m-sources">
        <h2 id="m-sources" className={s.h2}>
          Sources
        </h2>
        <ul className={s.list}>
          <li>
            PKDD'99 Discovery Challenge Financial dataset, CTU Prague Relational Dataset Repository:{' '}
            <a href="https://relational.fel.cvut.cz/dataset/Financial" target="_blank" rel="noreferrer">
              relational.fel.cvut.cz/dataset/Financial
            </a>{' '}
            (provided by Tangerine for the track)
          </li>
          <li>
            Government of Canada, EI benefit amount (55%, $729/week maximum in 2026):{' '}
            <a
              href="https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit/benefit-amount.html"
              target="_blank"
              rel="noreferrer"
            >
              canada.ca/en/services/benefits/ei/ei-regular-benefit/benefit-amount.html
            </a>
          </li>
        </ul>
      </section>
    </div>
  );
}
