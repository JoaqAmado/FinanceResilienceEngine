# FinanceResilienceEngine

Sheridan Datathon 2026 · Tangerine track "Resilience Rewired".

## Engine (`resilience/`)

Deterministic core: every number comes from `data/` using the judges' definitions
(I, F, S, B, H, P and the runway formula from the track brief). No LLM in the core.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                      # unit + real-data checks
.venv/bin/python -m resilience 20143               # baseline + the 3 README twists
.venv/bin/python -m resilience 20143 --income 0.55 --bills 0.15 --one-off-x-s 1 --target 6
.venv/bin/python -m resilience 98952 --income 0.55 --pension-aware --cap --waiting-week
.venv/bin/python -m resilience.portfolio               # chart tables -> artifacts/*.csv
```

The judges' number always comes first. Reality checks sit next to it, each a labelled option on `Shock`:
2026 EI cap ($729/week, canada.ca), the one-week EI waiting period, pension-aware job loss,
typical half-year spending (`S6`), a month-by-month path that starts in January, and household
bills paid by standing order. Plans: an EI-proof emergency-fund goal (`goal_plan(..., target_kind="ei_proof")`)
and a minimum-pain backup ladder (`backup_ladder`: fees, non-fixed spending -10%/-25%, pause other
standing orders, defer the running loan, -50%, else credit).

```python
from resilience import build_metrics, apply_shock, backup_ladder, goal_plan, Shock, LAID_OFF_EI
m = build_metrics()                                         # one row per account_id
apply_shock(m.loc[20143], Shock(income_multiplier=0.55))    # RunwayResult(months=2.2, ...)
```

Data credit: PKDD'99 Discovery Challenge Financial dataset (CTU Prague Relational Dataset Repository), provided by Tangerine for the track.
