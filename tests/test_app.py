from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_home_and_health():
    assert client.get("/").status_code == 200
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_rejects_non_image_type():
    response = client.post(
        "/api/ask", data={"question": "O que aparece?"},
        files={"image": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415


def test_rejects_invalid_image_signature():
    response = client.post(
        "/api/ask", data={"question": "O que aparece?"},
        files={"image": ("photo.png", b"not actually a PNG", "image/png")},
    )
    assert response.status_code == 415


def test_rejects_blank_question():
    response = client.post(
        "/api/ask", data={"question": "   "},
        files={"image": ("photo.png", PNG, "image/png")},
    )
    assert response.status_code == 400


def test_rate_limit_returns_retry_after(monkeypatch):
    import src.main as main
    monkeypatch.setattr(main, "RATE_LIMIT_REQUESTS", 1)
    monkeypatch.setattr(main, "RATE_LIMIT_WINDOW_SECONDS", 60)
    main._request_history.clear()
    first = client.post(
        "/api/ask", data={"question": "   "},
        files={"image": ("photo.png", PNG, "image/png")},
    )
    second = client.post(
        "/api/ask", data={"question": "   "},
        files={"image": ("photo.png", PNG, "image/png")},
    )
    assert first.status_code == 400
    assert second.status_code == 429
    assert "Retry-After" in second.headers
    main._request_history.clear()
