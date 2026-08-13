"""
Shared test configuration.

Tests must not depend on a local model being installed and running, and must not spend
the operator's Tavily credits. Both are disabled for the whole session, which exercises
the deterministic extraction path - the behaviour that has to hold up when no provider
is reachable.

Run against the live providers deliberately with:
    SMM_TEST_LIVE=1 python -m pytest tests/ -q
"""
import os
import pytest


@pytest.fixture(autouse=True, scope="session")
def offline_providers():
    if os.environ.get("SMM_TEST_LIVE"):
        yield
        return

    previous = {
        "SMM_DISABLE_LLM": os.environ.get("SMM_DISABLE_LLM"),
        "SMM_DISABLE_TAVILY": os.environ.get("SMM_DISABLE_TAVILY"),
    }
    os.environ["SMM_DISABLE_LLM"] = "1"
    # Checked ahead of the stored key, so a credential saved in the dashboard cannot
    # cause billed searches during a test run.
    os.environ["SMM_DISABLE_TAVILY"] = "1"

    yield

    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
