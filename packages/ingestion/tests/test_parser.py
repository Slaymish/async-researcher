from ingestion.parser import parse_markdown


def test_parses_basic_blocks():
    text = "# Heading\n\nA paragraph here.\n\n- bullet one\n- bullet two\n"
    doc = parse_markdown(text)
    kinds = [b.kind for b in doc.blocks]
    assert kinds == ["heading", "para", "list_item", "list_item"]
    assert doc.blocks[0].text.startswith("# ")
    assert doc.blocks[2].text.strip().startswith("- bullet one")


def test_frontmatter_separated_and_offset_correct():
    text = "---\ntitle: Foo\ntags: [x]\n---\n\n# H\n\nbody\n"
    doc = parse_markdown(text)
    assert doc.frontmatter == {"title": "Foo", "tags": ["x"]}
    assert doc.body.startswith("\n# H") or doc.body.startswith("# H")
    assert doc.body_line_offset == 4
    assert any(b.kind == "heading" for b in doc.blocks)


def test_existing_id_extracted_from_paragraph():
    text = "first paragraph here ^my-id\n\nsecond.\n"
    doc = parse_markdown(text)
    assert doc.blocks[0].existing_id == "my-id"
    assert "^" not in doc.blocks[0].text
    assert doc.blocks[1].existing_id is None


def test_existing_id_on_own_line_after_block():
    text = "# Heading\n\n^head-id\n\nbody\n"
    doc = parse_markdown(text)
    # The heading and the standalone ^id parse as separate blocks; either the heading or
    # the para before/after may carry the id depending on markdown-it's structuring.
    ids = [b.existing_id for b in doc.blocks if b.existing_id]
    assert "head-id" in ids


def test_fenced_code_block_not_split_by_id_pattern():
    text = "```python\n# fake heading\nx = 1  # ^not-an-id\n```\n"
    doc = parse_markdown(text)
    code_blocks = [b for b in doc.blocks if b.kind == "code"]
    assert len(code_blocks) == 1
    # Inline ^not-an-id sits inside the code block, so the trailing-id matcher should
    # leave it alone (it's not on the trailing line of the block snippet).
    assert "^not-an-id" in code_blocks[0].text
    assert code_blocks[0].existing_id is None


def test_table_block_recognised():
    text = "| a | b |\n| - | - |\n| 1 | 2 |\n"
    doc = parse_markdown(text)
    assert any(b.kind == "table" for b in doc.blocks)


def test_nested_list_emits_only_leaves():
    text = "- outer one\n\t- inner 1.1\n\t- inner 1.2\n- outer two\n"
    doc = parse_markdown(text)
    list_items = [b for b in doc.blocks if b.kind == "list_item"]
    # 'outer one' contains nested items so the parent is dropped; 'outer two' has no
    # nested items so it stays. Inner items always stay.
    texts = [b.text.strip() for b in list_items]
    assert "- inner 1.1" in " ".join(texts)
    assert "- inner 1.2" in " ".join(texts)
    # The outer-one parent (containing both inners) must not appear as its own block
    # — otherwise a trailing ^id on an inner row would be attributed to two blocks.
    for b in list_items:
        contains_another = any(
            other is not b
            and b.line_start <= other.line_start
            and other.line_end <= b.line_end
            and (b.line_start, b.line_end) != (other.line_start, other.line_end)
            for other in list_items
        )
        assert not contains_another, f"non-leaf list_item survived: {b}"
