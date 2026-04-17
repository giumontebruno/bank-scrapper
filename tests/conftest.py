from __future__ import annotations

import pytest

from core.config import reset_settings_cache
from query.repository import reset_repository_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    reset_settings_cache()
    reset_repository_cache()
    yield
    reset_settings_cache()
    reset_repository_cache()
