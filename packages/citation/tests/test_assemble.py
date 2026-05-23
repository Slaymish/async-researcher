from citation import assemble, parse_report


def test_assemble_renders_h1_h2_and_claims(sample_report, matching_chunks):
    md = assemble(sample_report, matching_chunks)
    assert "# Migration Decisions Across Major Refactors" in md
    assert "## Auth rewrite" in md
    assert "## Web sources" in md
    assert "[[ADRs/auth#^ai-aaaa1111]]" in md
    # Web chunk should render as a markdown link, not a wiki link.
    assert "[example.com](https://example.com/crawl)" in md
    assert "[[example.com" not in md


def test_assemble_broken_link_fallback_when_chunk_missing(sample_report):
    md = assemble(sample_report, chunks_by_id={})
    # Anchor-only fallback so verifier catches it as broken link.
    assert "[[#^ai-aaaa1111]]" in md


def test_assemble_summary_appears_before_first_section(sample_report, matching_chunks):
    md = assemble(sample_report, matching_chunks)
    title_idx = md.index("# Migration")
    summary_idx = md.index("A short orientation paragraph")
    section_idx = md.index("## Auth rewrite")
    assert title_idx < summary_idx < section_idx


def test_assemble_then_parse_roundtrip(sample_report, matching_chunks):
    md = assemble(sample_report, matching_chunks)
    parsed = parse_report(md)
    # Expect three claims (summary should NOT count).
    assert len(parsed.claims) == 3
    block_ids = [c.block_id for c in parsed.claims if c.block_id]
    assert "ai-aaaa1111" in block_ids
    assert "ai-bbbb2222" in block_ids
    # Web claim has url, not block_id.
    web_claim = next(c for c in parsed.claims if c.url is not None)
    assert web_claim.url == "https://example.com/crawl"
    # Title is captured.
    assert parsed.title == "Migration Decisions Across Major Refactors"
    # Section headings propagate to claims.
    sections = {c.section_heading for c in parsed.claims}
    assert sections == {"Auth rewrite", "Web sources"}
