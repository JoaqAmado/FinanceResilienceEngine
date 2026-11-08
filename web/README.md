# Twin Runway: web app

The live-twist demo as a static, keyless page. The resilience engine is ported to TypeScript and runs in the
browser, so any twist card works instantly and offline. The judges' number always comes first; reality checks are
labelled extras beside it.

## Run it

Needs Node 24 / npm 11. From this folder (`web/`):

```bash
npm install
npm run dev        # dev server with hot reload: http://localhost:5173
npm test           # parity suite (TS engine vs Python engine) + UI checks
npm run build      # type-check, then build into dist/
npm run preview    # serve dist/: http://localhost:4173 (the stage setup)
```

For the demo, use `npm run build && npm run preview`. Opening `dist/index.html` straight from disk does **not**
work: Chrome blocks module scripts and `fetch()` on `file://`.

## What's on the page

- **Live twist**: type any `account_id` (type-ahead over all 4,500; five digits open it straight away), or click a
  rehearsal account or **Random account**. Pick a twist card (keys `1`–`4`); switching card or account resets the
  levers to that card. Levers: income kept %, "job loss on EI", bills up %, extra monthly cost, one-off as × spending
  or $, must-survive months.
  - **Judges' formula** first: the animated runway, the SURVIVES / RUNS OUT / ALREADY OVERDRAWN / BUFFER GONE badge,
    the formula with this account's numbers, and the caption. The grey-zone note shows only on the plain EI 55% card.
  - **Reality checks**: 2026 EI cap, waiting week, keep pension, half-year spending, bills by standing order. Each
    is enabled only where it applies and shows its own runway and the change against the judges' number. The
    January month-by-month path is always shown.
  - **Burn-down** chart: no shock, judges' twist, twist + backup plan, and the January path, months
    0..max(24, 2 × runway). It has a $0 line, the month the buffer hits $0, hover tooltips and a table view.
  - **Plans**: the job-loss-proof fund with a progress bar, the backup ladder, credit advice (none for loans in
    arrears or default), and the template story.
  - **Customer card**: I, S, F, H, P, B, pension, warning flags, the early-warning light (0–4 points from four
    transparent rules, with the 2025 backtest line for that many points; the rules and tier table open below it;
    it never changes the judges' runway), and the month history (loaded only when the account is opened).
- **Portfolio**: headline tiles (recomputed live and checked against the Python export), income bands (click a band
  to list its accounts, sort by runway, click one to open it in the live twist), half-year calibration, cut
  histogram, pre-loan 2×2.
- **Method & limits**: definitions, limits and sources.
- **Presenter mode** (header button) enlarges all type for the projector. **Copy link** copies a URL whose hash
  holds the whole scenario (account, card, levers, target, checks), so a reload keeps the twist.

Keys: `/` account box · `1`–`4` twist cards · `R` reset levers to the card · arrow keys nudge a focused slider.

## How the TypeScript engine stays identical to the Python one

`src/engine/` is a line-by-line port of `resilience/core.py`, `resilience/narrative.py` and
`resilience/warning.py`. Nothing in the UI recomputes a formula; it calls the engine.

1. `scripts/export_web_data.py` (in the repo root) runs the **Python** engine and writes:
   - `public/data/accounts.json`: every account's inputs at full float precision, with `null` for NaN/inf
     (including the early-warning light's 4 raw rule inputs, rows used, days below zero, and the window's
     median money out and last month)
   - `public/data/portfolio.json`: the headlines and chart tables, and the early-warning backtest tiers
   - `public/data/history/<id>.json`: each account's monthly history
   - `test/vectors.json`: the Python engine's outputs for every account under 13 shocks, plus plans, ladders,
     flags, calendar paths and stories on a sample; the early-warning light for every account today and at the
     2024-12 backtest snapshot (with each account's 2025 outcome, so the test rebuilds the tier table)
2. `test/parity.test.ts` runs the TypeScript engine on the same inputs and requires exact equality for every
   runway, flag, verdict, plan step and story string. Money values must match to within 1e-6, and in practice
   all of them are bit-for-bit identical. Rounding uses numpy's rule (`np.round` = `rint(x·10)/10`, ties to even),
   never `Math.round` or `toFixed`.
3. `test/ui.test.ts` covers what the UI adds on top:
   - each twist card's levers produce exactly the engine's preset
   - twist labels match `app.py`
   - the January balance series crosses $0 where `calendarPath()` says, for every account
   - the hero number's `Intl` formatting prints the same digits as Python's `:.1f`
   - the portfolio bands reproduce `resilience/portfolio.py`
   - the pitch script's rehearsal numbers come out right
   - the URL hash round-trips
   - the early-warning light renders on the customer card with the same sentence as `app.py`

When the Python engine changes, regenerate and re-test:

```bash
cd ..                                       # repo root
.venv/bin/python scripts/export_web_data.py
cd web && npm test
```

## Stack

React 19.3.1, Vite 8.3.6, TypeScript 7.0.2, Recharts 3.10.1 (charts), @number-flow/react 0.6.2 (the animated
runway number), and Vitest 5.1.0 (node environment). All are pinned exactly. Styling is CSS Modules plus
`src/styles/tokens.css`. Chart series keep one meaning across the app: blue for the judges' formula, orange for
reality checks, aqua for the plan, slate for no shock. Each series also has its own line pattern, so no series is
told apart by colour alone.
