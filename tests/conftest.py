import pytest

from temporallib.worker import worker as worker_module


@pytest.fixture(autouse=True)
def _neutralize_force_exit_timer(monkeypatch):
    """The fatal-error force-exit timer calls os._exit; make sure no test can kill the
    pytest process, and reset the one-shot timer between tests."""
    monkeypatch.setattr(worker_module, "_force_exit", lambda: None)
    monkeypatch.setattr(worker_module, "_force_exit_timer", None)
    yield
    timer = worker_module._force_exit_timer
    if timer is not None:
        timer.cancel()
