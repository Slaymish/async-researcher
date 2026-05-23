import httpx
import pytest
import respx
from inference import InferenceClient, InferenceConfig
from pydantic import BaseModel, ValidationError

CFG = InferenceConfig(
    base_url="http://localhost:11434/v1",
    api_key="x",
    synthesis_model="syn",
    embedding_model="emb",
    judge_model="jud",
    embed_batch_size=2,
)


@pytest.mark.asyncio
@respx.mock
async def test_embed_returns_vectors_in_input_order():
    route = respx.post("http://localhost:11434/v1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.2, 0.2]},
                    {"index": 0, "embedding": [0.1, 0.1]},
                ]
            },
        )
    )
    async with InferenceClient(CFG) as c:
        out = await c.embed(["a", "b"])
    assert route.called
    assert out == [[0.1, 0.1], [0.2, 0.2]]


@pytest.mark.asyncio
@respx.mock
async def test_embed_batches_at_batch_size():
    respx.post("http://localhost:11434/v1/embeddings").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 0, "embedding": [0.0]},
                        {"index": 1, "embedding": [0.1]},
                    ]
                },
            ),
            httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [0.2]}]},
            ),
        ]
    )
    async with InferenceClient(CFG) as c:
        out = await c.embed(["a", "b", "c"])
    assert out == [[0.0], [0.1], [0.2]]


@pytest.mark.asyncio
async def test_embed_empty_list_is_noop():
    async with InferenceClient(CFG) as c:
        assert await c.embed([]) == []


@pytest.mark.asyncio
@respx.mock
async def test_embed_falls_back_to_per_item_on_400_then_skips_oversized():
    # First call (batch of 2) hits a context-length 400. Client retries per-item:
    # item 0 succeeds, item 1 (oversized) returns 400 → embedding=None.
    respx.post("http://localhost:11434/v1/embeddings").mock(
        side_effect=[
            httpx.Response(400, json={"error": {"message": "context length"}}),
            httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [0.9, 0.9]}]}
            ),
            httpx.Response(400, json={"error": {"message": "context length"}}),
        ]
    )
    async with InferenceClient(CFG) as c:
        out = await c.embed(["short", "way-too-long"])
    assert out == [[0.9, 0.9], None]


class _Person(BaseModel):
    name: str
    age: int


def _chat_resp(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


@pytest.mark.asyncio
@respx.mock
async def test_complete_text_returns_assistant_content():
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=_chat_resp("hello"),
    )
    async with InferenceClient(CFG) as c:
        out = await c.complete_text(
            [{"role": "user", "content": "hi"}],
        )
    assert out == "hello"


@pytest.mark.asyncio
@respx.mock
async def test_complete_structured_validates_with_pydantic():
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=_chat_resp('{"name":"Ada","age":36}'),
    )
    async with InferenceClient(CFG) as c:
        out = await c.complete(
            [{"role": "user", "content": "x"}],
            response_model=_Person,
        )
    assert out == _Person(name="Ada", age=36)


@pytest.mark.asyncio
@respx.mock
async def test_complete_retries_on_validation_failure_then_succeeds():
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        side_effect=[
            _chat_resp('{"name":"Ada"}'),  # missing age
            _chat_resp('{"name":"Ada","age":36}'),
        ]
    )
    async with InferenceClient(CFG) as c:
        out = await c.complete(
            [{"role": "user", "content": "x"}],
            response_model=_Person,
            max_repair_attempts=2,
        )
    assert out.age == 36


@pytest.mark.asyncio
@respx.mock
async def test_complete_raises_after_exhausting_retries():
    respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=_chat_resp('{"name":"Ada"}'),  # never produces valid output
    )
    async with InferenceClient(CFG) as c:
        with pytest.raises(ValidationError):
            await c.complete(
                [{"role": "user", "content": "x"}],
                response_model=_Person,
                max_repair_attempts=1,
            )


@pytest.mark.asyncio
@respx.mock
async def test_embed_non_400_errors_still_raise():
    respx.post("http://localhost:11434/v1/embeddings").mock(
        return_value=httpx.Response(500, json={"error": "boom"}),
    )
    with pytest.raises(httpx.HTTPStatusError):
        async with InferenceClient(CFG) as c:
            await c.embed(["a"])
