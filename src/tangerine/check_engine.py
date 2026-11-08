"""The check-engine light: F10's stress runway, turned into a red / amber / green zone with its evidence.

The zones are the stress-runway quartiles from the F10 loan test (marts.mart_default_drivers,
driver = 'stress_runway_with_loan'), read from the warehouse, so the light always matches
reports/findings.md:

    red   = shortest quarter          (Q1)
    amber = second quarter            (Q2)
    green = the longest half          (Q3 + Q4; many of those loans tie at 120 months)

A customer is placed by their stress runway with NO shock (what F10 tested: fragility before
anything happens). The evidence is about the 682 borrowers in the test, and is worded that way.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from tangerine import config

DRIVER = "stress_runway_with_loan"


@lru_cache(maxsize=1)
def zones() -> list[dict[str, Any]]:
    """Red, amber, green: each with its runway range and how many test borrowers in it defaulted."""
    from tangerine.engine import ensure_warehouse
    from tangerine.pipeline import connect

    ensure_warehouse()
    con = connect(read_only=True)
    try:
        q = con.execute(
            "select group_order, loans, defaults, min_value, max_value from marts.mart_default_drivers "
            "where driver = ? order by group_order", [DRIVER]).fetchall()
    finally:
        con.close()
    if len(q) != 4:
        raise RuntimeError(f"Expected 4 quartiles for {DRIVER}, found {len(q)}")
    (_, l1, d1, _, _), (_, l2, d2, cut1, _), (_, l3, d3, cut2, _), (_, l4, d4, _, _) = q
    cap = config.RUNWAY_CAP_MONTHS
    return [
        {"zone": "red", "label": "Red", "from_months": 0.0, "to_months": cut1,
         "loans": int(l1), "defaults": int(d1)},
        {"zone": "amber", "label": "Amber", "from_months": cut1, "to_months": cut2,
         "loans": int(l2), "defaults": int(d2)},
        {"zone": "green", "label": "Green", "from_months": cut2, "to_months": cap,
         "loans": int(l3 + l4), "defaults": int(d3 + d4)},
    ]


def light(stress_months: float | None) -> dict[str, Any]:
    """The zone for a no-shock stress runway (None = no shortfall, i.e. 120+), with its evidence."""
    zs = zones()
    months = config.RUNWAY_CAP_MONTHS if stress_months is None else stress_months
    z = next((z for z in zs if months < z["to_months"]), zs[-1])
    out = {**z, "stress_runway_months": stress_months, "default_rate": round(z["defaults"] / z["loans"], 3)}
    green = zs[-1]
    out["green_default_rate"] = round(green["defaults"] / green["loans"], 3)
    out["test_loans"] = sum(x["loans"] for x in zs)
    return out
