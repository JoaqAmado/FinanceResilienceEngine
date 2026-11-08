# Warehouse: Snowflake and DuckDB

The judges' numbers also exist as plain SQL in `sql/`: `JUDGE_METRICS` (I, F, S, H, B, P per account),
`EI55_RUNWAY` and `PORTFOLIO_SUMMARY`. The same files run unchanged in Snowflake and, offline, in DuckDB.
The Python engine stays the source of every number in the app; the warehouse is a check on it.

```bash
.venv/bin/python -m resilience.warehouse local-parity   # DuckDB over data/*.csv, no account needed
.venv/bin/python -m resilience.warehouse load           # upload 8 tables (not transactions) and create the views
.venv/bin/python -m resilience.warehouse verify         # Snowflake vs the engine on every account, counts only
```

`local-parity` matches the engine on all 4,500 accounts and gives the same 1,578 under 6 months (`tests/test_warehouse.py`).
`load` creates the database and schema if they are missing and replaces the tables; add `--with-transactions` for
the 100 MB transactions file. The SQL files run in name order (`sql/*.sql`), and each one follows the portability
rules at the top of `sql/10_judge_metrics.sql`.

## Settings

Settings come from the environment or `.env`, which is gitignored. Only the names are listed here; the CLI prints
counts only, and error text is scrubbed of every value.

| Variable | |
|---|---|
| `SNOWFLAKE_ACCOUNT` | required |
| `SNOWFLAKE_USER` | required |
| `SNOWFLAKE_PRIVATE_KEY_FILE` | path to a private key for key-pair login (preferred), kept outside the repo |
| `SNOWFLAKE_PASSWORD` | used when no key file is set |
| `SNOWFLAKE_WAREHOUSE` | optional, default `COMPUTE_WH` |
| `SNOWFLAKE_DATABASE` | optional, default `TANGERINE` |
| `SNOWFLAKE_SCHEMA` | optional, default `PUBLIC` |
| `SNOWFLAKE_ROLE` | optional |

With them set, the app's Method tab shows the `verify` result under "Computed in Snowflake". Without them, the app
never touches the network.

## Tests

The DuckDB parity tests run in the normal suite. The live Snowflake check is opt-in, because it needs the settings
above and one `load`:

```bash
.venv/bin/pytest -m live
```
