from __future__ import annotations

from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_home_page_and_static(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "MeetingMaster3" in r.text
    assert client.get("/static/app.css").status_code == 200


def test_foreign_host_rejected(client: TestClient) -> None:
    r = client.get("/healthz", headers={"Host": "evil.com"})
    assert r.status_code == 400


def test_configured_host_allowed() -> None:
    s = Settings()
    s.server.allowed_hosts = ["mm3.lan"]
    c = TestClient(create_app(s), base_url="http://mm3.lan")
    assert c.get("/healthz").status_code == 200


def test_security_headers(client: TestClient) -> None:
    h = client.get("/healthz").headers
    assert "default-src 'self'" in h["content-security-policy"]
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"


def test_csrf_cookie_is_samesite_strict(client: TestClient) -> None:
    r = client.get("/healthz")
    cookie = r.headers["set-cookie"].lower()
    assert "mm3_csrf=" in cookie and "samesite=strict" in cookie


def test_post_without_token_rejected(client: TestClient) -> None:
    r = client.post("/anything")
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_failed"


def test_post_with_wrong_token_rejected(client: TestClient) -> None:
    client.get("/")
    assert client.post("/anything", headers={"X-CSRF-Token": "nope"}).status_code == 403


def test_post_with_token_passes_csrf(client: TestClient) -> None:
    client.get("/")
    token = client.cookies["mm3_csrf"]
    r = client.post("/anything", headers={"X-CSRF-Token": token})
    assert r.status_code == 404  # CSRF passed; no such route


def test_post_with_foreign_origin_rejected(client: TestClient) -> None:
    client.get("/")
    token = client.cookies["mm3_csrf"]
    r = client.post("/anything", headers={"X-CSRF-Token": token, "Origin": "http://evil.com"})
    assert r.status_code == 403


def test_mm3_error_json_and_html() -> None:
    app = create_app(Settings())

    @app.get("/boom")
    async def boom() -> None:
        raise MM3Error("demo", "Something <b>broke</b>", "Try again")

    c = TestClient(app, base_url="http://localhost")
    j = c.get("/boom", headers={"Accept": "application/json"})
    assert j.status_code == 400 and j.json() == {
        "code": "demo",
        "message": "Something <b>broke</b>",
        "hint": "Try again",
    }
    h = c.get("/boom", headers={"Accept": "text/html"})
    assert "&lt;b&gt;" in h.text and "<b>broke" not in h.text
