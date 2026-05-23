from ingestion.id_injector import GENERATED_PREFIX, compute_id, inject_ids
from ingestion.parser import parse_markdown


def _ids(text: str, relpath: str = "note.md") -> tuple[str, list]:
    parsed = parse_markdown(text)
    return inject_ids(text, parsed, relpath)


def test_compute_id_is_deterministic():
    a = compute_id("a.md", 0, "hello world")
    b = compute_id("a.md", 0, "hello world")
    assert a == b
    assert a.startswith(GENERATED_PREFIX)


def test_compute_id_normalises_whitespace():
    a = compute_id("a.md", 0, "hello  world")
    b = compute_id("a.md", 0, "hello world")
    c = compute_id("a.md", 0, "hello\nworld")
    assert a == b == c


def test_inject_is_idempotent():
    text = "first para\n\nsecond para\n"
    new1, blocks1 = _ids(text)
    new2, blocks2 = _ids(new1)
    assert new1 == new2  # second pass writes nothing new
    assert [b.existing_id for b in blocks1] == [b.existing_id for b in blocks2]


def test_user_authored_ids_preserved():
    text = "first para ^mine\n\nsecond para\n"
    new, blocks = _ids(text)
    assert blocks[0].existing_id == "mine"
    assert blocks[1].existing_id is not None and blocks[1].existing_id.startswith(
        GENERATED_PREFIX
    )
    assert "^mine" in new


def test_collision_disambiguation():
    # Two identical paragraphs in the same file → same hash → disambiguated.
    text = "duplicate line\n\nduplicate line\n"
    _, blocks = _ids(text)
    ids = [b.existing_id for b in blocks]
    assert ids[0] != ids[1]
    assert ids[0] is not None and ids[1] is not None


def test_frontmatter_preserved_verbatim():
    text = "---\ntitle: Foo\n---\n\npara\n"
    new, _ = _ids(text)
    assert new.startswith("---\ntitle: Foo\n---\n")
