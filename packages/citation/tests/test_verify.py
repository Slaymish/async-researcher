from pathlib import Path

import pytest
from citation import Claim, Report, Section, verify_report
from retrieval import Chunk, DuckDBStore


class FakeClient:
    pass


def _store(tmp_path: Path) -> DuckDBStore:
    return DuckDBStore(tmp_path / "index.duckdb", embedding_dim=2)


@pytest.mark.asyncio
async def test_verify_report_passes_deterministic_checks(tmp_path: Path):
    store = _store(tmp_path)
    store.upsert_chunks(
        [
            Chunk(
                "ai-a",
                "note.md",
                "para",
                "Deterministic citation requires assembled markdown verification.",
                1,
                1,
                {},
                [1.0, 0.0],
            )
        ]
    )
    report = Report(
        title="Citations",
        summary="Overview.",
        sections=[
            Section(
                heading="Verification",
                claims=[
                    Claim(
                        text="The citation check verifies the assembled Markdown",
                        quote="assembled markdown verification",
                        block_id="ai-a",
                    )
                ],
            )
        ],
    )

    result = await verify_report(report, store, FakeClient(), skip_alignment=True)

    assert result.passed
    assert result.pass_rate == 1.0
    store.close()


@pytest.mark.asyncio
async def test_verify_report_flags_missing_rendered_citation(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    store.upsert_chunks(
        [
            Chunk(
                "ai-a",
                "note.md",
                "para",
                "The source contains the quoted text.",
                1,
                1,
                {},
                [1.0, 0.0],
            )
        ]
    )
    report = Report(
        title="Citations",
        summary="Overview.",
        sections=[
            Section(
                heading="Verification",
                claims=[
                    Claim(
                        text="The source contains the quoted text",
                        quote="quoted text",
                        block_id="ai-a",
                    )
                ],
            )
        ],
    )

    def broken_assemble(*_args, **_kwargs) -> str:
        return (
            "# Citations\n\nOverview.\n\n## Verification\n\n"
            "The source contains the quoted text.\n"
        )

    monkeypatch.setattr("citation.verify.assemble", broken_assemble)

    result = await verify_report(report, store, FakeClient(), skip_alignment=True)

    assert not result.passed
    assert result.failures[0].kind.value == "missing_citation"
    store.close()


@pytest.mark.asyncio
async def test_verify_report_flags_missing_block_and_bad_quote(tmp_path: Path):
    store = _store(tmp_path)
    store.upsert_chunks(
        [
            Chunk(
                "ai-a",
                "note.md",
                "para",
                "The source contains one true quote.",
                1,
                1,
                {},
                [1.0, 0.0],
            )
        ]
    )
    report = Report(
        title="Citations",
        summary="Overview.",
        sections=[
            Section(
                heading="Verification",
                claims=[
                    Claim(
                        text="The source contains one true quote",
                        quote="fabricated quote",
                        block_id="ai-a",
                    ),
                    Claim(
                        text="A missing block should fail",
                        quote="anything",
                        block_id="ai-missing",
                    ),
                ],
            )
        ],
    )

    result = await verify_report(report, store, FakeClient(), skip_alignment=True)

    kinds = {failure.kind.value for failure in result.failures}
    assert kinds == {"quote_not_in_source", "broken_link"}
    store.close()
