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
import tempfile
import pytest

# Set BEFORE src.core.db is imported: the engine is built at import time.
#
# The suite deletes rows wholesale in its fixtures. Pointed at the real database that
# destroyed saved channel credentials and the post history, so tests now get a throwaway
# file. Set SMM_TEST_USE_REAL_DB=1 to opt out.
if not os.environ.get("SMM_TEST_USE_REAL_DB"):
    _test_db = os.path.join(tempfile.gettempdir(), "smm_test_suite.db")
    os.environ["SMM_DB_PATH"] = _test_db
    for _suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_test_db + _suffix)
        except OSError:
            pass

    # Create the schema now: modules that build singletons at import time query the
    # database before any test fixture gets a chance to run init_db().
    from src.core.db import init_db as _init_db
    _init_db()


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
