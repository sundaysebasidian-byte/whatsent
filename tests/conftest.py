from __future__ import annotations

import pytest

from whatsent.capture import UPSTREAM_VARS


@pytest.fixture(autouse=True)
def no_ambient_proxy(monkeypatch):
    """Runs must not depend on a proxy configured on the machine that runs the tests."""
    for var in UPSTREAM_VARS:
        monkeypatch.delenv(var, raising=False)
