import pytest

from app.services.search import MAX_QUERY_TOKENS, keyword_candidates, sanitize_fts_query

OPERATORS_EXPECTED = (
    '"foo"* OR "AND"* OR "bar"* OR "OR"* OR "baz"* OR "NOT"* OR "qux"*'
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("rahul payment", '"rahul"* OR "payment"*'),
        ('say "hello" world', '"say"* OR "hello"* OR "world"*'),
        ("foo AND bar OR (baz) NOT -qux*", OPERATORS_EXPECTED),
        ("नमस्ते दुनिया", '"नमस्ते"* OR "दुनिया"*'),
        ("rahul@gmail.com", '"rahul"* OR "gmail"* OR "com"*'),
        ("", ""),
        ("   ", ""),
        ('"""', ""),
        ("!!! ???", ""),
        ("^ * ( ) :", ""),
    ],
)
def test_sanitize(raw: str, expected: str) -> None:
    assert sanitize_fts_query(raw) == expected


def test_token_count_is_capped() -> None:
    query = sanitize_fts_query(" ".join(f"w{i}" for i in range(50)))
    assert query.count(" OR ") == MAX_QUERY_TOKENS - 1


@pytest.mark.parametrize("raw", ['"', "AND", "a OR", "(", "NEAR(a b)", "col:x", "-x", "*"])
def test_hostile_input_never_breaks_fts(add_image, raw: str) -> None:
    add_image("/s/a.png", status="done", summary="hello world")
    assert isinstance(keyword_candidates(sanitize_fts_query(raw), 10), list)


def test_devanagari_matches_in_fts(add_image) -> None:
    image_id = add_image("/s/h.png", status="done", ocr_text="नमस्ते दुनिया")
    hits = keyword_candidates(sanitize_fts_query("नमस्ते"), 10)
    assert [hit[0] for hit in hits] == [image_id]