"""Stage 1 of ADR-0013: constrained JSON synthesis.

Builds the synthesis prompt from the retrieved context and calls the inference
adapter with the `Report` Pydantic schema. JSON-mode + Pydantic validation +
bounded retry happens inside `inference.complete()`.

The prompt design is intentionally explicit about three things, in order of how
often each is broken in practice:
1. Every `block_id` MUST come from the supplied context. No invention.
2. Every `quote` MUST be a verbatim substring of the source it claims to be from.
3. Output MUST be JSON conforming to the schema. The system says so; JSON mode
   enforces it; Pydantic validates; the citation engine repairs on mismatch.
"""

from __future__ import annotations

from inference import InferenceClient, Message
from retrieval import ScoredChunk

from .prompts import build_synthesis_messages
from .schema import Report


def build_messages(query: str, chunks: list[ScoredChunk]) -> list[Message]:
    return build_synthesis_messages(query, chunks)


async def synthesise(
    query: str,
    chunks: list[ScoredChunk],
    client: InferenceClient,
    *,
    model: str | None = None,
    max_repair_attempts: int = 2,
) -> Report:
    """Run constrained generation and return a validated `Report`.

    Raises `pydantic.ValidationError` if the model can't produce a schema-valid
    output within the repair attempts allowed by `inference.complete()`. Callers
    can catch and surface to the user; the higher-level repair loop in `repair.py`
    handles semantic failures (broken links etc.), not schema failures.
    """
    messages = build_messages(query, chunks)
    return await client.complete(
        messages,
        response_model=Report,
        model=model,
        max_repair_attempts=max_repair_attempts,
    )
