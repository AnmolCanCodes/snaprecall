from app.db import connection, init_db, transaction, upsert_vector


def test_init_db_is_idempotent(db) -> None:
    init_db()
    init_db()
    with connection() as conn:
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert {"images", "images_fts", "vec_images", "images_ai", "images_ad", "images_au"} <= names


def test_processing_rows_reset_on_startup(add_image) -> None:
    stuck = add_image("/s/a.png", status="processing")
    done = add_image("/s/b.png", status="done")
    init_db()
    with connection() as conn:
        statuses = {
            row["id"]: row["status"] for row in conn.execute("SELECT id, status FROM images")
        }
    assert statuses[stuck] == "pending"
    assert statuses[done] == "done"


def test_deleting_image_removes_vector_and_fts(add_image) -> None:
    image_id = add_image("/s/a.png", status="done", summary="payment", vector=[1, 0, 0, 0])
    with connection() as conn:
        assert conn.execute("SELECT count(*) FROM vec_images").fetchone()[0] == 1
        conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
        assert conn.execute("SELECT count(*) FROM vec_images").fetchone()[0] == 0
        hits = conn.execute("SELECT rowid FROM images_fts WHERE images_fts MATCH 'payment'")
        assert hits.fetchall() == []


def test_transaction_rolls_back_on_error(add_image) -> None:
    image_id = add_image("/s/a.png")
    try:
        with connection() as conn, transaction(conn):
            upsert_vector(conn, image_id, [1, 0, 0, 0])
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with connection() as conn:
        assert conn.execute("SELECT count(*) FROM vec_images").fetchone()[0] == 0