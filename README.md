# FinanceResilienceEngine: Twin Runway

Sheridan Datathon 2026 · Tangerine track "Resilience Rewired".

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
cd web && npm install && npm test && npm run build && npm run preview   # http://localhost:4173 (npm run dev for :5173)
```

On Windows, use `.venv\Scripts\` instead of `.venv/bin/`. The web app's data files are committed, so it runs without Python.

More from the engine:

```bash
.venv/bin/python -m resilience 20143 --income 0.55 --bills 0.15   # one account, one twist, in the terminal
.venv/bin/python -m resilience.portfolio                          # chart tables -> artifacts/*.csv
.venv/bin/python -m resilience.warehouse local-parity             # the judges' numbers in SQL (DuckDB), offline
```

## Repo map

| Path | What it holds | Kind |
|---|---|---|
| `app.py` | the Streamlit app, Twin Runway: live twist, portfolio, method | app |
| `web/` | the React/TypeScript app: the same engine, ported to the browser ([web/README.md](web/README.md)) | app |
| `resilience/` | the engine: judges' numbers, shocks, reality checks, plans, early-warning light, 2025 backtest evidence, CLI | engine |
| `sql/` | the judges' numbers as plain SQL, run in Snowflake or DuckDB | SQL |
| `data/` | the track's CSV files | input |
| `artifacts/` | chart tables from `python -m resilience.portfolio`, `python -m resilience.warning` and `python -m resilience.evidence` | generated |
| `web/public/data/` | the engine's inputs for the web app, from `scripts/export_web_data.py` | generated |
| `web/test/vectors.json` | the Python engine's outputs the web app must match, from `scripts/export_web_data.py` | generated |
| `scripts/` | `export_web_data.py`, which writes the web app's data | tool |
| `tests/` | pytest: unit checks, real-data checks, docs and layout checks | tests |
| `docs/` | findings, method, model card, data dictionary, warehouse | docs |

## Docs

- [Findings](docs/findings.md): what the data says, and how each figure is computed
- [Method](docs/method.md): the judges' definitions, shocks and reality checks, plans, the early-warning light, CLI and Python examples
- [Model card](docs/model_card.md): intended use, what it is not for, data and limits, wording
- [Data dictionary](docs/data_dictionary.md): every column of `data/`, the engine and `artifacts/`
- [Warehouse](docs/warehouse.md): the Snowflake and DuckDB layer and its settings
- [Web app](web/README.md): running, testing and the TypeScript port

## Sources
- PKDD'99 Discovery Challenge Financial dataset, CTU Prague Relational Dataset Repository: https://relational.fel.cvut.cz/dataset/Financial (provided by Tangerine for the track)
- Government of Canada, EI benefit amount (55%, $729/week maximum in 2026): https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit/benefit-amount.html
