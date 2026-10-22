"""Shared pytest configuration."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    # Starlette's test client warns about httpx vs httpx2; that is a library choice, not ours.
    config.addinivalue_line("filterwarnings", "ignore:Using `httpx` with `starlette.testclient`")
