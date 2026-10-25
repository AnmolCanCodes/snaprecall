import asyncio
import shutil

from app.db import connection
from app.services.pipeline import Outcome, process_image


def _row(image_id: int):
    with connection() as conn:
        return conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()


def _vector_count(image_id: int) -> int:
    with connection() as conn:
        return conn.execute(
            "SELECT count(*) FROM vec_images WHERE rowid = ?", (image_id,)
        ).fetchone()[0]


def test_full_indexing_writes_everything(add_image, fake_ollama, make_png, shots_dir) -> None:
    image = make_png(shots_dir / "a.png")
    image_id = add_image(str(image))
    assert asyncio.run(process_image(image_id)) is Outcome.DONE
    row = _row(image_id)
    assert row["status"] == "done"
    assert row["summary"].startswith("Payment")
    assert row["sha256"] and row["width"] == 48 and row["indexed_at"]
    assert _vector_count(image_id) == 1


def test_identical_file_is_deduplicated_without_model_calls(
    add_image, fake_ollama, make_png, shots_dir
) -> None:
    first = make_png(shots_dir / "a.png")
    second = shots_dir / "b.png"
    shutil.copyfile(first, second)
    id_a = add_image(str(first))
    id_b = add_image(str(second))

    assert asyncio.run(process_image(id_a)) is Outcome.DONE
    assert (fake_ollama.chat_calls, fake_ollama.embed_calls) == (1, 1)

    assert asyncio.run(process_image(id_b)) is Outcome.DONE
    assert (fake_ollama.chat_calls, fake_ollama.embed_calls) == (1, 1)
    assert _row(id_b)["summary"] == _row(id_a)["summary"]
    assert _row(id_b)["status"] == "done"
    assert _vector_count(id_b) == 1


def test_missing_file_deletes_row(add_image, fake_ollama, shots_dir) -> None:
    image_id = add_image(str(shots_dir / "gone.png"))
    assert asyncio.run(process_image(image_id)) is Outcome.MISSING
    assert _row(image_id) is None


def test_ollama_outage_requeues_without_counting_attempt(
    add_image, fake_ollama, make_png, shots_dir
) -> None:
    image_id = add_image(str(make_png(shots_dir / "a.png")))
    fake_ollama.unavailable = True
    assert asyncio.run(process_image(image_id)) is Outcome.OLLAMA_DOWN
    row = _row(image_id)
    assert (row["status"], row["attempts"]) == ("pending", 0)


def test_bad_output_retries_then_fails(add_image, fake_ollama, make_png, shots_dir) -> None:
    image_id = add_image(str(make_png(shots_dir / "a.png")))
    fake_ollama.chat_reply = "not json at all"
    assert asyncio.run(process_image(image_id)) is Outcome.ERROR
    row = _row(image_id)
    assert (row["status"], row["attempts"]) == ("pending", 1)
    assert row["error"]
    assert asyncio.run(process_image(image_id)) is Outcome.ERROR
    assert _row(image_id)["status"] == "failed"