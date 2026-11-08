"""FastAPI backend: serves the resilience engine and the 90-day plan as JSON, plus the HTML page.

Run:  python app/main.py                     (local Python; opens on http://localhost:8001)
      docker compose up app                 (Docker; http://localhost:8000)
"""
from __future__ import annotations

import bisect
import sys
from pathlib import Path

# Make `app` and `tangerine` importable however this file is started (VS Code Run button, python app/main.py, uvicorn).
_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.plan90 import build_90_day_plan
from tangerine import engine
from tangerine.engine import PRESETS, Shock, UnknownAccount

STATIC = Path(__file__).parent / "static"

# Rehearsed accounts from reports/showcase.md, offered as quick picks in the page.
SHOWCASE = {
    "Pensioner": 61810,
    "Volatile cash earner": 56404,
    "Defaulter with a balance slide": 59243,
    "Comfortable saver": 72641,
    "Negative buffer": 66692,
}

app = FastAPI(title="Tangerine 90-day resilience plan", version="1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta() -> dict:
    """Presets (twist cards), showcase accounts and the number of accounts known."""
    return {
        "presets": {name: s.describe() for name, s in PRESETS.items()},
        "showcase": SHOWCASE,
        "account_count": len(engine.account_ids()),
    }


@app.get("/api/accounts")
def accounts() -> list[int]:
    """Every valid account_id (sorted). IDs are sparse (20111-99984), so the page offers these instead of guessing."""
    return engine.account_ids()


def nearest_accounts(account_id: int, n: int = 4) -> list[int]:
    """The n valid account_ids closest to a number that isn't one."""
    ids = engine.account_ids()
    i = bisect.bisect_left(ids, account_id)
    window = ids[max(0, i - n):i + n]
    return sorted(sorted(window, key=lambda a: abs(a - account_id))[:n])


@app.get("/api/plan/{account_id}")
def plan(
    account_id: int,
    preset: str | None = Query(None, description="A twist card name; overrides the sliders when given."),
    income_factor: float = Query(1.0, ge=0, le=1.5, description="Share of typical income still coming in."),
    duration_months: int | None = Query(None, ge=1, le=24, description="Months the income cut lasts."),
    bills_increase_pct: float = Query(0.0, ge=0, le=2, description="Household bills increase, 0.15 = +15%."),
    one_off_cost: float = Query(0.0, ge=0, le=1_000_000, description="One-off cost in dollars."),
    one_off_months_of_spending: float = Query(0.0, ge=0, le=12, description="One-off cost in months of spending."),
) -> dict:
    """Engine result (judge numbers + ours) and the 90-day plan for one account and one shock."""
    if preset is not None:
        if preset not in PRESETS:
            raise HTTPException(400, f"Unknown preset {preset!r}. Choose one of: {', '.join(PRESETS)}")
        shock: Shock | str = preset
    else:
        shock = Shock(
            income_factor=income_factor,
            duration_months=duration_months,
            bills_increase_pct=bills_increase_pct,
            one_off_cost=one_off_cost,
            one_off_months_of_spending=one_off_months_of_spending,
        )
    try:
        result = engine.run(account_id, shock)
    except UnknownAccount as e:
        raise HTTPException(404, {"message": str(e), "suggestions": nearest_accounts(account_id)}) from None
    result["ninety_day_plan"] = build_90_day_plan(result)
    return result


if __name__ == "__main__":
    import os

    import uvicorn

    port = int(os.environ.get("PORT", "8001"))  # 8000 is used by the Docker app service
    print(f"Open http://localhost:{port}")
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)
