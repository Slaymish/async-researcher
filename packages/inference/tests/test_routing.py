import pytest
from inference import InferenceConfig, InferenceTask, model_for_task

CFG = InferenceConfig(
    base_url="http://localhost:11434/v1",
    api_key="x",
    synthesis_model="syn",
    embedding_model="emb",
    judge_model="jud",
)


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        (InferenceTask.EMBEDDING, "emb"),
        (InferenceTask.SYNTHESIS, "syn"),
        (InferenceTask.JUDGE, "jud"),
        ("embedding", "emb"),
        ("synthesis", "syn"),
        ("judge", "jud"),
    ],
)
def test_model_for_task(task: InferenceTask | str, expected: str):
    assert model_for_task(CFG, task) == expected


def test_model_for_task_rejects_unknown_task():
    with pytest.raises(ValueError):
        model_for_task(CFG, "reranker")
