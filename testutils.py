"""Shared test utilities for HexManager tests.

Kept outside the ``tests/`` package so that both ``tests/conftest.py`` and
individual test modules can import from here without relying on
``from tests.conftest import ...`` (which fails when pytest is invoked from
within ``tests/`` or when ``tests/`` is not a package on ``sys.path``).
"""

_sim_initialized = False


def ensure_sim_initialized():
    """Import ``sim.run`` exactly once to set up simulator shims.

    This must **not** be called at module level – only from inside fixtures
    or test functions – because ``sim/run.py`` replaces ``sys.meta_path``
    and would prevent pytest from finding ``faulthandler`` during its own
    ``pytest_configure`` phase.
    """
    global _sim_initialized
    if not _sim_initialized:
        import sim.run  # noqa: F401 – side effect: configures sys.path & fakes
        _sim_initialized = True
