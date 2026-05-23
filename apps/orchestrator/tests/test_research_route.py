"""Tests for POST /research and POST /research/stream routes."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from citation import VerificationReport
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.flows.roma import AtomizerVerdict
from orchestrator.flows.research_flow import ResearchResult
from orchestrator.routes import research as research_route_module
from orchestrator.routes.research import router


def _app() -> FastAPI:
    app = FastAPI()
    app.state.store = object()
    app.state.client = object()
    app.include_router(router)
    return app


def _fake_result(query: str = "q") -> ResearchResult:
    from citation import Report
    from citation.schema import Claim, Section

    fake_report = Report(
        title="Test",
        summary="Test summary.",
        sections=[Section(heading="S", claims=[
            Claim(text="Fact.", quote="Quote.", block_id="abc123"),
        ])],
    )
    return ResearchResult(
        query=query,
        report=fake_report,
        markdown="# Report\n\nContent.",
        attempts=1,
        k=20,
        verification=VerificationReport(total_claims=1, failures=[]),
        sub_reports=(),
        atomizer_verdict=AtomizerVerdict(decompose=False, rationale="atomic"),
    )


# --- POST /research ----------------------------------------------------------


def test_research_route_returns_504_on_inference_timeout(monkeypatch):
    async def _timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(research_route_module, "research", _timeout)
    response = TestClient(_app()).post("/research", json={"query": "x"})

    assert response.status_code == 504
    assert "local inference request timed out" in response.json()["detail"]


def test_research_route_returns_200_on_success(monkeypatch):
    async def _ok(*_args, **_kwargs):
        return _fake_result("hello")

    monkeypatch.setattr(research_route_module, "research", _ok)
    response = TestClient(_app()).post("/research", json={"query": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "hello"
    assert "markdown" in body
    assert "pass_rate" in body
    assert body["pass_rate"] == 1.0


def test_research_route_returns_503_when_store_not_ready():
    app = FastAPI()
    # No state.store / state.client set.
    app.include_router(router)
    response = TestClient(app).post("/research", json={"query": "x"})
    assert response.status_code == 503


def test_research_route_serialises_atomizer_verdict(monkeypatch):
    async def _ok(*_args, **_kwargs):
        return _fake_result()

    monkeypatch.setattr(research_route_module, "research", _ok)
    response = TestClient(_app()).post("/research", json={"query": "q"})

    body = response.json()
    assert body["atomizer"] is not None
    assert body["atomizer"]["decompose"] is False
    assert "rationale" in body["atomizer"]


def test_research_route_serialises_executions(monkeypatch):
    async def _ok(*_args, **_kwargs):
        return _fake_result()

    monkeypatch.setattr(research_route_module, "research", _ok)
    response = TestClient(_app()).post("/research", json={"query": "q"})

    body = response.json()
    assert "executions" in body
    assert isinstance(body["executions"], list)


def test_research_route_rejects_empty_query():
    response = TestClient(_app()).post("/research", json={"query": ""})
    assert response.status_code == 422


def test_research_route_rejects_k_out_of_range():
    response = TestClient(_app()).post("/research", json={"query": "x", "k": 0})
    assert response.status_code == 422

    response = TestClient(_app()).post("/research", json={"query": "x", "k": 101})
    assert response.status_code == 422


def test_research_route_accepts_decompose_true(monkeypatch):
    received: list[dict] = []

    async def _capture(*_args, **kwargs):
        received.append(kwargs)
        return _fake_result()

    monkeypatch.setattr(research_route_module, "research", _capture)
    response = TestClient(_app()).post("/research", json={"query": "x", "decompose": True})

    assert response.status_code == 200
    assert received[0]["decompose"] is True


def test_research_route_accepts_decompose_false(monkeypatch):
    received: list[dict] = []

    async def _capture(*_args, **kwargs):
        received.append(kwargs)
        return _fake_result()

    monkeypatch.setattr(research_route_module, "research", _capture)
    response = TestClient(_app()).post("/research", json={"query": "x", "decompose": False})

    assert response.status_code == 200
    assert received[0]["decompose"] is False


def test_research_route_passes_skip_alignment_to_flow(monkeypatch):
    received: list[dict] = []

    async def _capture(*_args, **kwargs):
        received.append(kwargs)
        return _fake_result()

    monkeypatch.setattr(research_route_module, "research", _capture)
    TestClient(_app()).post("/research", json={"query": "x", "skip_alignment": True})

    assert received[0]["skip_alignment"] is True


# --- POST /research/stream ---------------------------------------------------


def test_research_stream_returns_sse_content_type(monkeypatch):
    async def _ok(*_args, **_kwargs):
        return _fake_result("streaming")

    monkeypatch.setattr(research_route_module, "research", _ok)
    response = TestClient(_app()).post("/research/stream", json={"query": "streaming"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]


def test_research_stream_emits_result_event(monkeypatch):
    async def _ok(*_args, **_kwargs):
        return _fake_result("s")

    monkeypatch.setattr(research_route_module, "research", _ok)
    response = TestClient(_app()).post("/research/stream", json={"query": "s"})

    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    result_events = [e for e in events if e.get("type") == "result"]
    assert len(result_events) == 1
    assert result_events[0]["data"]["query"] == "s"


def test_research_stream_emits_error_event_on_timeout(monkeypatch):
    async def _timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(research_route_module, "research", _timeout)
    response = TestClient(_app()).post("/research/stream", json={"query": "x"})

    assert response.status_code == 200
    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    error_events = [e for e in events if e.get("type") == "error"]
    assert len(error_events) == 1
    assert "timed out" in error_events[0]["message"].lower()


def test_research_stream_returns_503_when_not_ready():
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post("/research/stream", json={"query": "x"})
    assert response.status_code == 503


def test_research_stream_emits_progress_events(monkeypatch):
    async def _with_progress(*_args, on_progress=None, **_kwargs):
        if on_progress:
            on_progress("step one")
            on_progress("step two")
        return _fake_result("p")

    monkeypatch.setattr(research_route_module, "research", _with_progress)
    response = TestClient(_app()).post("/research/stream", json={"query": "p"})

    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    progress = [e for e in events if e.get("type") == "progress"]
    assert len(progress) == 2
    messages = [e["message"] for e in progress]
    assert "step one" in messages
    assert "step two" in messages
