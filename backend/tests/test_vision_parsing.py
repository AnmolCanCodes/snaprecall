import pytest

from app.services.llm_client import ProviderResponseError
from app.services.vision import parse_vision_response

FULL = (
    '{"summary": "A chat about rent", "tags": ["WhatsApp", "#Chat", "rent"], '
    '"app_type": "Chat", "visible_text": "Rahul: rent bhej diya"}'
)


def test_plain_json() -> None:
    result = parse_vision_response(FULL)
    assert result.app_type == "chat"
    assert result.tags == ["whatsapp", "chat", "rent"]
    assert result.visible_text == "Rahul: rent bhej diya"


def test_fenced_json_with_prose() -> None:
    result = parse_vision_response(f"Sure, here you go:\n```json\n{FULL}\n```\nHope it helps")
    assert result.summary == "A chat about rent"


def test_partial_json_falls_back_to_defaults() -> None:
    result = parse_vision_response('{"summary": "Only a summary"}')
    assert result.summary == "Only a summary"
    assert result.tags == []
    assert result.app_type == "other"
    assert result.visible_text == ""


def test_bad_field_types_are_coerced() -> None:
    result = parse_vision_response('{"summary": null, "tags": "a, B, a", "app_type": "gaming"}')
    assert result.summary == ""
    assert result.tags == ["a", "b"]
    assert result.app_type == "other"


def test_tags_and_text_are_capped() -> None:
    tags = ", ".join(f"tag{i}" for i in range(20))
    long_text = "x" * 2000
    result = parse_vision_response(
        f'{{"tags": "{tags}", "visible_text": "{long_text}"}}'
    )
    assert len(result.tags) == 8
    assert len(result.visible_text) == 1500


@pytest.mark.parametrize(
    "raw",
    ["I cannot describe this image.", "", "[1, 2, 3]", '{"summary": "cut off', "```json\n```"],
)
def test_irrecoverable_output_raises(raw: str) -> None:
    with pytest.raises(ProviderResponseError):
        parse_vision_response(raw)