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

## Chat twists

On the Live twist tab the twist is typed, not dialled: "Job loss on EI and bills up 15%", "income drops to $2,000 a
month", "make it 20% instead". The chat only sets the levers (the same session state the Fine-tune sliders show);
the engine computes every number, and code writes every sentence.

**What it reads.** Job loss on EI (55% unless another EI percent is named) · pay cut or reduced hours (not a job
loss) · income drops by X% or to $N a month · a partner's job (half the money in, stated as an assumption) ·
household bills, utilities or rent up X% · rent up $N or rent goes to $N · new monthly costs ($N a month: baby, car
payment, insurance) · a $N one-off or N months of spending · cutting non-fixed spending X% · "for / survive N months"
· "account 12345" · the reality checks by name (2026 EI cap, waiting week, keep pension, half-year spending, bills by
standing order). Edits work on the current shock: "make it 20% instead" (the last percent lever), "add a $2,000
repair", "remove the bills increase", "no job loss", "reset". Anything a message doesn't mention keeps its value.
Numbers can be written "15", "15%", "fifteen percent", "0.15", "$2,500", "2.5k" or "$2500/mo".

**Resolution order** (`resilience/shock_parser.py`): golden table (`resilience/golden_twists.json`, exact match after
lowercasing and stripping punctuation) → cache (`resilience/llm_cache_frozen.json`, committed, then
`.cache/shock_intents.json`, local) → LLM (`resilience/shock_llm.py`: Gemini with `GEMINI_API_KEY`, or Snowflake
Cortex with `SNOWFLAKE_PAT` and `SHOCK_LLM=cortex`; `SHOCK_LLM=off` turns it off) → offline rules. Every backend
returns the same intent (what was said), and one function, `validate_and_build`, turns it into a `Shock`. The LLM
gets the message and the current shock only, never account data.

**Determinism guarantees.**
- Golden phrases and cached inputs give byte-identical results every time, with no network.
- A new input costs one LLM call (pinned model version, temperature 0, JSON-schema output, canonicalized); from then
  on it is cached and identical. The cache key is the normalized message, the current shock, the prompt version,
  the model ID and the intent-schema version.
- Offline, an uncached input falls back to the rules. That is the only way the same text can parse differently,
  and the source badge on the reply says which backend answered. `warm` removes this case for every rehearsed
  phrasing.

**Account-relative amounts** are resolved in code against the selected customer, and the reply shows the
arithmetic: "income drops to $N a month" → N ÷ I (kept at 100% if N is more than I; left unchanged if I is $0);
"rent goes to $N" → N − H when the account has household bills, else all of N, with a warning (1,225 accounts have
H = $0); "a month of spending" → 1 × S. Values out of range are clamped with a warning, reality checks that can't
apply (an EI cap without a job loss, "keep pension" with no pension) are turned off with a warning, and anything
unreadable gets a question back with the state left unchanged.

**Consistency checks** (`resilience/consistency.py`), run on every rerun: the shock the engine ran is the one the
levers and the chat describe; the customer card equals a recomputation from `data/raw/` with the judges'
definitions; the judges' runway equals the published formula and its verdict box agrees; the January path matches
a month-by-month rerun; the backup-ladder rung marked as reaching the target does (and the one before it doesn't);
the goal's buffer passes; each reality-check runway is the engine with only that check on; every number in the
summary is in the computed facts; each flag on the card is true in the data. The app shows "All numbers consistent"
or lists exactly which check failed. The tests also check that the portfolio tiles, `data/derived/*.csv` and the
figures quoted above agree.

**Before a demo**, with a key set, run the rehearsed phrasings through the LLM once and freeze them:

```bash
.venv/bin/python -m resilience.shock_parser warm      # hint chips, golden and practice phrasings, one call each
.venv/bin/python -m resilience.shock_parser freeze    # copy them into resilience/llm_cache_frozen.json, then commit
```

## Repo map

| Path | What it holds | Kind |
|---|---|---|
| `app.py` | the Streamlit app, Twin Runway: live twist, portfolio, method | app |
| `web/` | the React/TypeScript app: the same engine, ported to the browser ([web/README.md](web/README.md)) | app |
| `resilience/` | the engine: judges' numbers, shocks, reality checks, plans, early-warning light, 2025 backtest evidence, CLI | engine |
| `resilience/shock_parser.py` | the chat: free-text twists to a `Shock` (golden → cache → LLM → rules), deterministic | engine |
| `resilience/consistency.py` | the checks that every number on screen agrees with the others and with the data | engine |
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
