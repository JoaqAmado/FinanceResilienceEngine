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
```

```python
from resilience import baseline_metrics, load_monthly, load_loans, apply_shock, backup_plan, goal_plan, Shock
m = baseline_metrics(load_monthly(), load_loans())          # one row per account_id
apply_shock(m.loc[20143], Shock(income_multiplier=0.55))    # RunwayResult(months=2.2, ...)
```

Data credit: PKDD'99 Discovery Challenge Financial dataset (CTU Prague Relational Dataset Repository), provided by Tangerine for the track.
