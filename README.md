# FinanceResilienceEngine: Twin Runway

Sheridan Datathon 2026 · Tangerine track "Resilience Rewired".

**Live:** [twin-runway.vercel.app](https://twin-runway.vercel.app) (the landing page, with the web app at
[/app/](https://twin-runway.vercel.app/app/)).

For any of Tangerine's 4,500 accounts: **how many months does this customer last after a shock, and what should they do?**
The judges' runway comes first, computed exactly as the track brief defines it. Labelled reality checks sit beside it,
then a goal plan and a backup plan built from the customer's own numbers.

**Headline finding:** on the judges' own formula, **1,578 of 4,500 accounts (35.1%)** can't last 6 months on EI at 55%,
and the more money comes in, the thinner the cushion. Every finding, and the code that computes it, is in
[docs/findings.md](docs/findings.md).

## Quickstart

Needs Python 3.12, and Node 24 / npm 11 for the web app.

```bash
git clone https://github.com/JoaqAmado/FinanceResilienceEngine.git && cd FinanceResilienceEngine
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -e .
.venv/bin/pytest -rs                      # offline suite; the live Snowflake check is opt-in: .venv/bin/pytest -m live
.venv/bin/streamlit run app.py            # http://localhost:8501
(cd web && npm install && npm test && npm run build && npm run preview)   # http://localhost:4173 (npm run dev for :5173)
.venv/bin/python scripts/build_site.py && .venv/bin/python -m http.server 8000 --directory site_dist   # landing page + app
```

On Windows, use `.venv\Scripts\` instead of `.venv/bin/`. The web app's data files are committed, so it runs without Python.

More from the engine:

```bash
.venv/bin/python -m resilience 20143 --income 0.55 --bills 0.15   # one account, one twist, in the terminal
.venv/bin/python -m resilience.portfolio                          # chart tables -> data/derived/*.csv
.venv/bin/python -m resilience.warehouse local-parity             # the judges' numbers in SQL (DuckDB), offline
```

## Repo map

| Path | What it holds | Kind |
|---|---|---|
| `app.py` | the Streamlit app, Twin Runway: live twist, portfolio, method | app |
| `web/` | the React/TypeScript app: the same engine, ported to the browser ([web/README.md](web/README.md)) | app |
| `resilience/` | the engine: judges' numbers, shocks, reality checks, plans, early-warning light, 2025 backtest evidence, CLI | engine |
| `sql/` | the judges' numbers as plain SQL, run in Snowflake or DuckDB | SQL |
| `data/raw/` | the track's CSV files | input |
| `data/derived/` | chart tables from `python -m resilience.portfolio`, `python -m resilience.warning` and `python -m resilience.evidence`; the gradient-boosting benchmark from `python -m resilience.benchmark` | generated |
| `web/public/data/` | the engine's inputs for the web app, from `scripts/export_web_data.py` | generated |
| `web/test/vectors.json` | the Python engine's outputs the web app must match, from `scripts/export_web_data.py` | generated |
| `scripts/` | `export_web_data.py`, which writes the web app's data | tool |
| `site/` | the landing page judges open first: plain HTML and CSS, app screenshots in `site/img/` | site |
| `scripts/build_site.py` | builds `site/` and the web app into one static folder, `site_dist/`, with the app at `site_dist/app/` | tool |
| `tests/` | pytest: unit checks, real-data checks, docs and layout checks | tests |
| `docs/` | findings, method, model card, data dictionary, warehouse | docs |

## Docs

- [Findings](docs/findings.md): what the data says, and how each figure is computed
- [Method](docs/method.md): the judges' definitions, shocks and reality checks, plans, the early-warning light, CLI and Python examples
- [Model card](docs/model_card.md): at a glance (data, label, time-based split, base rate, limits), intended use,
  what it is not for, data and limits, wording
- [Data dictionary](docs/data_dictionary.md): every column of `data/raw/`, the engine and `data/derived/`
- [Warehouse](docs/warehouse.md): the Snowflake and DuckDB layer and its settings
- [Web app](web/README.md): running, testing and the TypeScript port

## Sources
- PKDD'99 Discovery Challenge Financial dataset, CTU Prague Relational Dataset Repository: https://relational.fel.cvut.cz/dataset/Financial (provided by Tangerine for the track; the page also notes the rule that separates good loans from bad)
- Government of Canada, EI benefit amount (55%, $729/week maximum in 2026): https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit/benefit-amount.html
- Government of Canada, temporary EI measures (waiting period waived for new claims until Oct 9, 2027): https://www.canada.ca/en/services/benefits/ei/temporary-measures-for-major-economic-conditions.html
- JPMorgan Chase Institute (2016), Recovering from Job Loss: https://ir.jpmorganchase.com/content/dam/jpmc/jpmorgan-chase-and-co/institute/pdf/jpmc-institute-unemployment-insurance-report.pdf
- Browning & Crossley, Unemployment insurance benefit levels and consumption changes (abstract): https://ideas.repec.org/p/kud/kuiedp/9611.html
- Miksovsky et al. (1999), Financial Data Challenge, and Pijls (1999), Discovery Challenge, Financial Data (PKDD'99 papers on the original data): https://web.archive.org/web/20070614032012/http://lisp.vse.cz/pkdd99/Challenge/miksovsp.zip · https://web.archive.org/web/20051026172811/http://lisp.vse.cz:80/pkdd99/Challenge/pijls.zip
