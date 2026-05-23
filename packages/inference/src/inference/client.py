"""OpenAI-compatible inference adapter (ADR-0009).

Single chokepoint for every LLM call originated by this system. Per ADR-0005, the only
endpoints this is permitted to talk to are local (Ollama, LM Studio, llama-swap). The
config layer is the enforcement point — this module just speaks the protocol.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .routing import InferenceTask, model_for_task
from .types import Message

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class InferenceConfig:
    base_url: str
    api_key: str
    synthesis_model: str
    embedding_model: str
    judge_model: str
    embed_batch_size: int = 64
    timeout_s: float = 60.0


class InferenceClient:
    def __init__(self, config: InferenceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=config.timeout_s,
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> InferenceClient:
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def embed(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float] | None]:
        """Return one embedding per input string, in order.

        Inputs that exceed the embedding model's context window get `None` rather than
        crashing the run: the chunk still lands in the index (recoverable by lexical
        retrieval later) and the rest of the batch proceeds. Other HTTP errors still
        raise.
        """
        if not texts:
            return []
        model_name = model or model_for_task(self.config, InferenceTask.EMBEDDING)
        out: list[list[float] | None] = []
        batch = self.config.embed_batch_size
        for i in range(0, len(texts), batch):
            chunk = texts[i : i + batch]
            out.extend(await self._embed_batch(chunk, model_name))
        return out

    async def _embed_batch(
        self, chunk: list[str], model_name: str
    ) -> list[list[float] | None]:
        try:
            return await self._embed_request(chunk, model_name)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 400 or len(chunk) == 1:
                # Single-item 400 → can't shrink further; record as failure.
                if len(chunk) == 1 and e.response.status_code == 400:
                    return [None]
                raise
            # Batch hit a context-length cap on some item; fall back to per-item.
            result: list[list[float] | None] = []
            for item in chunk:
                try:
                    result.extend(await self._embed_request([item], model_name))
                except httpx.HTTPStatusError as inner:
                    if inner.response.status_code == 400:
                        result.append(None)
                    else:
                        raise
            return result

    async def _embed_request(
        self, chunk: list[str], model_name: str
    ) -> list[list[float]]:
        resp = await self._client.post(
            "/embeddings",
            json={"model": model_name, "input": chunk},
        )
        resp.raise_for_status()
        payload = resp.json()
        data = sorted(payload["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    async def complete_text(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Plain text completion. Returns the assistant message content."""
        model_name = model or model_for_task(self.config, InferenceTask.SYNTHESIS)
        payload = {
            "model": model_name,
            "messages": list(messages),
            "temperature": temperature,
        }
        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def complete(
        self,
        messages: list[Message],
        *,
        response_model: type[T],
        model: str | None = None,
        temperature: float = 0.0,
        max_repair_attempts: int = 2,
    ) -> T:
        """Structured completion. Requests JSON-mode output and validates against
        `response_model`. On `ValidationError`, retries up to `max_repair_attempts`
        with the raw output + error message appended to the conversation so the model
        can correct itself. Raises `ValidationError` if all attempts fail.
        """
        model_name = model or model_for_task(self.config, InferenceTask.SYNTHESIS)
        convo: list[Message] = list(messages)
        last_err: ValidationError | None = None
        for attempt in range(max_repair_attempts + 1):
            payload = {
                "model": model_name,
                "messages": convo,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            try:
                return response_model.model_validate_json(content)
            except ValidationError as e:
                last_err = e
                if attempt == max_repair_attempts:
                    break
                log.warning(
                    "complete() validation failed on attempt %d/%d; retrying",
                    attempt + 1,
                    max_repair_attempts + 1,
                )
                convo = [
                    *convo,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "Your previous response failed schema validation:\n"
                            f"{e}\n\nReturn ONLY a JSON document matching the "
                            "requested schema. No prose, no markdown fences."
                        ),
                    },
                ]
        assert last_err is not None  # loop only exits via break or return
        raise last_err
