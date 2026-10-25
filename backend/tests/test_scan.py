import os
import shutil

from app.db import connection
from app.services.watcher import scan_folder


def _count() -> int:
    with connection() as conn:
        return conn.execute("SELECT count(*) FROM images").fetchone()[0]


def test_scan_adds_requeues_and_removes(db, shots_dir, make_png) -> None:
    first = make_png(shots_dir / "a.png")
    second = make_png(shots_dir / "b.jpg")
    make_png(shots_dir / ".hidden.png")
    make_png(shots_dir / "partial.png.tmp")
    (shots_dir / "notes.txt").write_text("x")
    make_png(shots_dir / "sub" / "deep.png")

    assert scan_folder().added == 2
    assert scan_folder().unchanged == 2

    with connection() as conn:
        conn.execute("UPDATE images SET status = 'done'")
    stat = first.stat()
    os.utime(first, (stat.st_atime, stat.st_mtime + 100))
    result = scan_folder()
    assert (result.requeued, result.unchanged) == (1, 1)
    with connection() as conn:
        statuses = {r["filename"]: r["status"] for r in conn.execute("SELECT * FROM images")}
    assert statuses == {"a.png": "pending", "b.jpg": "done"}

    second.unlink()
    assert scan_folder().removed == 1
    assert _count() == 1


def test_missing_folder_never_wipes_the_index(db, shots_dir, add_image) -> None:
    add_image(str(shots_dir / "a.png"), status="done")
    shutil.rmtree(shots_dir)
    result = scan_folder()
    assert result.model_dump() == {"added": 0, "requeued": 0, "removed": 0, "unchanged": 0}
    assert _count() == 1