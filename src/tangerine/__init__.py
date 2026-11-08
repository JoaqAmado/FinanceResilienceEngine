"""Tangerine "Resilience Rewired" — financial resilience engine (Sheridan Datathon 2026).

Modules
-------
config           paths, constants and thresholds
pipeline         builds warehouse/tangerine.duckdb from the raw CSVs (python -m tangerine.pipeline)
engine           profile / shock / judge runway / simulation / plan for one account
judge_reference  independent pandas re-implementation of the judge formulas (test oracle)
findings         headline numbers, charts and showcase accounts (python -m tangerine.findings)
"""

__version__ = "1.0.0"
