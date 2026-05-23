import pytest
from citation import Claim, Report, Section
from retrieval import Chunk


@pytest.fixture
def sample_report() -> Report:
    return Report(
        title="Migration Decisions Across Major Refactors",
        summary="A short orientation paragraph that should not be parsed as a claim.",
        sections=[
            Section(
                heading="Auth rewrite",
                claims=[
                    Claim(
                        text="The team chose Mem0 for session memory",
                        quote="we picked Mem0 for cross-session memory",
                        block_id="ai-aaaa1111",
                    ),
                    Claim(
                        text="Adversarial review is required before contradiction detection",
                        quote=(
                            "contradiction detection requires "
                            "Composer/Corroborator/Critic underneath"
                        ),
                        block_id="ai-bbbb2222",
                    ),
                ],
            ),
            Section(
                heading="Web sources",
                claims=[
                    Claim(
                        text="Crawl4AI handles Single Page Applications",
                        quote="Crawl4AI is optimized for SPAs via Playwright",
                        block_id="ai-cccc3333",
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def matching_chunks() -> dict[str, Chunk]:
    return {
        "ai-aaaa1111": Chunk(
            block_id="ai-aaaa1111",
            relpath="ADRs/auth.md",
            kind="para",
            text="After the audit we picked Mem0 for cross-session memory; "
                 "it ships tri-signal retrieval out of the box.",
            line_start=0,
            line_end=1,
        ),
        "ai-bbbb2222": Chunk(
            block_id="ai-bbbb2222",
            relpath="ADRs/review.md",
            kind="para",
            text="Per the roadmap, contradiction detection requires "
                 "Composer/Corroborator/Critic underneath; v0.3 unblocks it.",
            line_start=0,
            line_end=1,
        ),
        "ai-cccc3333": Chunk(
            block_id="ai-cccc3333",
            relpath="web://example.com/crawl",
            kind="para",
            text="Crawl4AI is optimized for SPAs via Playwright with stealth flags.",
            line_start=0,
            line_end=1,
        ),
    }
