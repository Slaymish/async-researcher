import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.routes import research as research_route_module
from orchestrator.routes.research import router


def test_research_route_returns_504_on_inference_timeout(monkeypatch):
    async def _timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(research_route_module, "research", _timeout)
    app = FastAPI()
    app.state.store = object()
    app.state.client = object()
    app.include_router(router)

    response = TestClient(app).post("/research", json={"query": "x"})

    assert response.status_code == 504
    assert "local inference request timed out" in response.json()["detail"]
