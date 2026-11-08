"""FastAPI backend: serves the resilience engine and the resilience plan (look back + next 12 months) as JSON,
plus the HTML page.

Run:  python app/main.py                     (local Python; http://localhost:8000, or the next free port)
      docker compose up app                 (Docker; http://localhost:8000)
"""
from __future__ import annotations

import bisect
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Make `app` and `tangerine` importable however this file is started (VS Code Run button, python app/main.py, uvicorn).
_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.plan import build_look_back, build_next_12_months
from tangerine import engine, history
from tangerine.engine import PRESETS, Shock, UnknownAccount

STATIC = Path(__file__).parent / "static"

# Quick-pick cards shown in the app. Bills and repairs are typed in as numbers instead (bills as % of H, which is
# the judges' rule, or $/month; repair in $). All presets stay in the engine for the findings and tests.
APP_PRESETS = ["no_shock", "job_loss_ei55"]
HORIZON_MONTHS = 12

# Rehearsed accounts from reports/showcase.md, offered as quick picks in the page.
SHOWCASE = {
    "Pensioner": 61810,
    "Volatile cash earner": 56404,
    "Defaulter with a balance slide": 59243,
    "Comfortable saver": 72641,
    "Negative buffer": 66692,
}

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Load (and on a fresh clone, first build) the warehouse before serving, so no request waits or races on it.
    engine.account_ids()
    history.recent_months(engine.account_ids()[0])
    yield


app = FastAPI(
    title="Tangerine resilience plan",
    version="1.0",
    lifespan=lifespan,
    description="Know the customer, take a shock, make a plan. Interactive docs at /docs. Any front end (React, "
                "mobile, a notebook) can call these endpoints; judge numbers are returned unchanged beside ours.",
)
# Let other UIs (e.g. the React app in web/ on http://localhost:5173) call the API from the browser.
# Read-only GET API with no cookies or logins, so any origin is allowed; restrict with CORS_ORIGINS if deployed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")],
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta() -> dict:
    """Presets (twist cards), showcase accounts and the number of accounts known."""
    return {
        "presets": {name: PRESETS[name].describe() for name in APP_PRESETS},
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
    bills_increase_amount: float = Query(0.0, ge=0, le=100_000, description="Bills increase in dollars per month."),
    one_off_cost: float = Query(0.0, ge=0, le=1_000_000, description="One-off cost in dollars."),
    one_off_months_of_spending: float = Query(0.0, ge=0, le=12, description="One-off cost in months of spending."),
) -> dict:
    """Engine result (judge numbers + ours), the 6-month look back and the 12-month plan for one account and shock."""
    if preset is not None:
        if preset not in PRESETS:
            raise HTTPException(400, f"Unknown preset {preset!r}. Choose one of: {', '.join(PRESETS)}")
        shock: Shock | str = preset
    else:
        shock = Shock(
            income_factor=income_factor,
            duration_months=duration_months,
            bills_increase_pct=bills_increase_pct,
            bills_increase_amount=bills_increase_amount,
            one_off_cost=one_off_cost,
            one_off_months_of_spending=one_off_months_of_spending,
        )
    try:
        result = engine.run(account_id, shock, horizon=HORIZON_MONTHS)
    except UnknownAccount as e:
        raise HTTPException(404, {"message": str(e), "suggestions": nearest_accounts(account_id)}) from None
    look_back = build_look_back(result, history.recent_months(account_id))
    result["resilience_plan"] = {"look_back": look_back, "next_12_months": build_next_12_months(result, look_back)}
    return result


if __name__ == "__main__":
    import socket

    import uvicorn

    def _free(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", p)) != 0

    if "PORT" in os.environ:
        port = int(os.environ["PORT"])
    else:  # 8000 if free; otherwise (e.g. the Docker app is running there) the next free port
        port = next(p for p in range(8000, 8011) if _free(p))
        if port != 8000:
            print("Port 8000 is busy (is the Docker app running? That copy is at http://localhost:8000).")
    print(f"Open http://localhost:{port}")
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)
