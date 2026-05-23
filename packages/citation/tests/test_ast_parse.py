"""Tests for citation.ast_parse — pure-function AST parser over assembled Markdown."""

from citation.ast_parse import ParsedClaim, parse_report


def test_parse_report_extracts_title():
    md = "# My Report\n\nSummary text.\n\n## Section\n\nClaim. [[note#^ai-abc]]\n"
    result = parse_report(md)
    assert result.title == "My Report"


def test_parse_report_no_title_returns_none():
    md = "## Section\n\nClaim. [[note#^ai-abc]]\n"
    result = parse_report(md)
    assert result.title is None


def test_parse_vault_link_claim():
    md = "# T\n\nSummary.\n\n## Section\n\nThe system uses caching. [[notes/arch#^ai-abc123]]\n"
    result = parse_report(md)
    assert len(result.claims) == 1
    c = result.claims[0]
    assert c.block_id == "ai-abc123"
    assert c.url is None
    assert c.section_heading == "Section"
    assert "caching" in c.text


def test_parse_web_link_claim():
    md = "# T\n\nSummary.\n\n## Web\n\nCrawl4AI handles SPAs. [example.com](https://example.com/crawl)\n"
    result = parse_report(md)
    assert len(result.claims) == 1
    c = result.claims[0]
    assert c.url == "https://example.com/crawl"
    assert c.block_id is None
    assert c.section_heading == "Web"


def test_parse_summary_paragraph_not_a_claim():
    md = "# T\n\nThis is the orientation summary.\n\n## Section\n\nReal claim. [[x#^ai-001]]\n"
    result = parse_report(md)
    # Only the claim under ## Section should appear; summary is above any section.
    assert len(result.claims) == 1
    assert result.claims[0].block_id == "ai-001"


def test_paragraph_in_section_without_citation_is_captured_as_uncited():
    md = "# T\n\nSummary.\n\n## Section\n\nUncited paragraph.\n"
    result = parse_report(md)
    assert len(result.claims) == 1
    c = result.claims[0]
    assert c.block_id is None
    assert c.url is None
    assert c.section_heading == "Section"


def test_multiple_sections_assign_correct_headings():
    md = (
        "# T\n\nSummary.\n\n"
        "## Alpha\n\nFirst claim. [[a#^ai-a1]]\n\n"
        "## Beta\n\nSecond claim. [[b#^ai-b1]]\n"
    )
    result = parse_report(md)
    assert len(result.claims) == 2
    assert result.claims[0].section_heading == "Alpha"
    assert result.claims[0].block_id == "ai-a1"
    assert result.claims[1].section_heading == "Beta"
    assert result.claims[1].block_id == "ai-b1"


def test_multiple_claims_in_one_section():
    md = (
        "# T\n\nSummary.\n\n## Section\n\n"
        "Claim one. [[a#^ai-001]]\n\n"
        "Claim two. [[b#^ai-002]]\n"
    )
    result = parse_report(md)
    assert len(result.claims) == 2
    ids = [c.block_id for c in result.claims]
    assert ids == ["ai-001", "ai-002"]


def test_last_citation_wins_when_multiple_links_in_paragraph():
    # vault link comes after web link — vault link should win.
    md = (
        "# T\n\nSummary.\n\n## Section\n\n"
        "Claim [web.com](https://web.com) and also [[note#^ai-last]].\n"
    )
    result = parse_report(md)
    assert len(result.claims) == 1
    c = result.claims[0]
    assert c.block_id == "ai-last"
    assert c.url is None


def test_web_link_wins_when_it_comes_after_vault_link():
    md = (
        "# T\n\nSummary.\n\n## Section\n\n"
        "Claim [[note#^ai-first]] and also [web.com](https://web.com/page).\n"
    )
    result = parse_report(md)
    assert len(result.claims) == 1
    c = result.claims[0]
    assert c.url == "https://web.com/page"
    assert c.block_id is None


def test_empty_body_returns_empty_claims():
    result = parse_report("")
    assert result.title is None
    assert result.claims == []


def test_heading_only_returns_no_claims():
    md = "# Title\n"
    result = parse_report(md)
    assert result.title == "Title"
    assert result.claims == []


def test_line_no_is_one_indexed_and_nonzero():
    md = "# T\n\nSummary.\n\n## Section\n\nClaim. [[n#^ai-xyz]]\n"
    result = parse_report(md)
    assert len(result.claims) == 1
    assert result.claims[0].line_no >= 1


def test_broken_link_anchor_only_form_parsed_correctly():
    # assemble.py emits [[#^id]] when the chunk is missing; parse_report should
    # extract the block_id from the anchor-only form.
    md = "# T\n\nSummary.\n\n## Section\n\nClaim with broken link. [[#^ai-broken]]\n"
    result = parse_report(md)
    assert len(result.claims) == 1
    assert result.claims[0].block_id == "ai-broken"


def test_block_id_with_hyphens_and_underscores():
    md = "# T\n\nSummary.\n\n## Section\n\nClaim. [[folder/note#^ai-abc-def_ghi]]\n"
    result = parse_report(md)
    assert result.claims[0].block_id == "ai-abc-def_ghi"
