import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main

app = main.app


def test_health_endpoint_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.skipif(not hasattr(asyncio, "WindowsSelectorEventLoopPolicy"), reason="Windows-only policy")
def test_configure_windows_event_loop_policy_uses_selector_policy(monkeypatch) -> None:
    captured: dict[str, asyncio.AbstractEventLoopPolicy] = {}

    def _capture(policy):  # noqa: ANN001
        captured["policy"] = policy

    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.asyncio, "set_event_loop_policy", _capture)

    main.configure_windows_event_loop_policy()

    assert isinstance(captured["policy"], asyncio.WindowsSelectorEventLoopPolicy)
