"""Shared test setup: make `tangerine` importable and make sure the warehouse exists."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tangerine import config, pipeline  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def warehouse():
    """Build the warehouse once if it is missing (e.g. a fresh clone)."""
    if not config.WAREHOUSE_PATH.exists():
        assert pipeline.build(), "pipeline build failed"
    return config.WAREHOUSE_PATH


@pytest.fixture(scope="session")
def con(warehouse):
    c = pipeline.connect(read_only=True)
    yield c
    c.close()
