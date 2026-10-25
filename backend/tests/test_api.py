import pytest

from app.services.worker import IndexWorker

PAYMENT = "2026-10-25T10:00:00.000Z"
ERROR = "2026-10-25T09:00:00.000Z"
HINDI = "2026-10-25T08:00:00.000Z"


@pytest.fixture
def indexed(add_image) -> dict[str, int]:
    return {
        "payment": add_image(
            "/s/pay.png",
            status="done",
            summary="Payment to Rahul 2500 rupees",
            ocr_text="Rahul 2500",
            tags=["payment", "upi"],
            app_type="payment",
            vector=[1, 0, 0, 0],
            indexed_at=PAYMENT,
        ),
        "error": add_image(
            "/s/err.png",
            status="done",
            summary="Docker permission denied error",
            app_type="error",
            vector=[0, 1, 0, 0],
            indexed_at=ERROR,
        ),
        "hindi": add_image(
            "/s/hi.png",
            status="done",
            summary="Greeting screen",
            ocr_text="नमस्ते दुनिया",
            vector=[0, 0, 0, 1],
            indexed_at=HINDI,
        ),
        "pending": add_image(
            "/s/pending.png", status="pending", summary="Rahul pending item", vector=[1, 0, 0, 0]
        ),
    }


def _ids(body: dict) -> list[int]:
    return [hit["image"]["id"] for hit in body["results"]]


def test_keyword_and_semantic_both_match(client, fake_ollama, indexed) -> None:
    body = client.get("/api/search", params={"q": "rahul"}).json()
    top = body["results"][0]
    assert top["image"]["id"] == indexed["payment"]
    assert top["matched_by"] == ["keyword", "semantic"]
    assert "[[" in top["snippet"]
    assert body["degraded"] is False
    assert indexed["pending"] not in _ids(body)


def test_semantic_only_match(client, fake_ollama, indexed) -> None:
    body = client.get("/api/search", params={"q": "money sent"}).json()
    top = body["results"][0]
    assert top["image"]["id"] == indexed["payment"]
    assert top["matched_by"] == ["semantic"]


def test_devanagari_query(client, fake_ollama, indexed) -> None:
    body = client.get("/api/search", params={"q": "नमस्ते"}).json()
    assert body["results"][0]["image"]["id"] == indexed["hindi"]
    assert "keyword" in body["results"][0]["matched_by"]


def test_degrades_to_keywords_when_ollama_is_down(client, fake_ollama, indexed) -> None:
    fake_ollama.unavailable = True
    body = client.get("/api/search", params={"q": "rahul"}).json()
    assert body["degraded"] is True
    assert _ids(body) == [indexed["payment"]]
    assert body["results"][0]["matched_by"] == ["keyword"]


def test_empty_query_returns_recent_done_images(client, fake_ollama, indexed) -> None:
    body = client.get("/api/search", params={"q": "  "}).json()
    assert _ids(body) == [indexed["payment"], indexed["error"], indexed["hindi"]]


def test_limit_is_validated_and_applied(client, fake_ollama, indexed) -> None:
    assert len(client.get("/api/search", params={"q": "rahul", "limit": 1}).json()["results"]) == 1
    for bad in (0, 101):
        response = client.get("/api/search", params={"q": "rahul", "limit": bad})
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)


def test_health_reports_ok_and_degraded(client, fake_ollama) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["vision_model"]["ok"] and body["embedding_model"]["ok"]
    assert body["provider_name"] == "ollama"
    assert body["provider"]["ok"] is True
    fake_ollama.unavailable = True
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["provider"]["ok"] is False


def test_metadata_and_unknown_id(client, add_image) -> None:
    image_id = add_image("/s/a.png", status="done", summary="hello", tags=["x"])
    body = client.get(f"/api/images/{image_id}").json()
    assert body["summary"] == "hello" and body["tags"] == ["x"]
    missing = client.get("/api/images/9999")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Image not found"}
    assert client.get("/api/images/abc/file").status_code == 422


def test_file_inside_screenshot_dir_is_served(client, add_image, make_png, shots_dir) -> None:
    image = make_png(shots_dir / "ok.png")
    image_id = add_image(str(image), status="done")
    response = client.get(f"/api/images/{image_id}/file")
    assert response.status_code == 200
    assert response.content == image.read_bytes()


def test_file_outside_screenshot_dir_is_rejected(client, add_image, make_png, tmp_path) -> None:
    secret = make_png(tmp_path / "secret.png")
    image_id = add_image(str(secret), status="done")
    response = client.get(f"/api/images/{image_id}/file")
    assert response.status_code == 403
    assert "detail" in response.json()


def test_dotdot_path_is_rejected(client, add_image, make_png, tmp_path, shots_dir) -> None:
    make_png(tmp_path / "secret.png")
    image_id = add_image(str(shots_dir / ".." / "secret.png"), status="done")
    assert client.get(f"/api/images/{image_id}/file").status_code == 403


def test_symlink_escape_is_rejected(client, add_image, make_png, tmp_path, shots_dir) -> None:
    secret = make_png(tmp_path / "secret.png")
    link = shots_dir / "link.png"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")
    image_id = add_image(str(link), status="done")
    assert client.get(f"/api/images/{image_id}/file").status_code == 403


def test_thumbnail_is_generated_lazily(client, add_image, make_png, shots_dir) -> None:
    image_id = add_image(str(make_png(shots_dir / "t.png")), status="done")
    response = client.get(f"/api/images/{image_id}/thumbnail")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_index_controls(client, make_png, shots_dir) -> None:
    assert client.get("/api/index/status").status_code == 503
    client.app.state.worker = IndexWorker()
    make_png(shots_dir / "one.png")
    assert client.post("/api/index/scan").json()["added"] == 1
    status = client.get("/api/index/status").json()
    assert (status["pending"], status["total"], status["paused"]) == (1, 1, False)
    assert status["provider_ok"] is True
    assert client.post("/api/index/pause").json()["paused"] is True
    assert client.post("/api/index/resume").json()["paused"] is False