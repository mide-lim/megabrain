from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize("path", ("/docs", "/redoc", "/docs/oauth2-redirect", "/openapi.json"))
def test_fastapi_default_documentation_routes_are_not_http_routes(path: str) -> None:
    response = TestClient(app).get(path)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}


def test_internal_openapi_describes_owner_cookie_and_runtime_security_contracts() -> None:
    schema = app.openapi()

    assert schema["openapi"]
    assert schema["components"]["securitySchemes"]["OwnerSessionCookie"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "__Host-mb_session",
        "description": "Opaque local single-owner session cookie.",
    }

    owner_protected_operations = (
        ("/api/auth/csrf", "get"),
        ("/api/reels", "get"),
        ("/api/reels/{reel_id}", "get"),
        ("/api/reels/{reel_id}/video", "get"),
        ("/api/reels/{reel_id}/categories", "post"),
        ("/api/reels/{reel_id}/categories/new", "post"),
        ("/api/reels/{reel_id}/categories/{category_id}", "delete"),
    )
    for path, method in owner_protected_operations:
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"OwnerSessionCookie": []}]
        assert operation["responses"]["401"]["description"] == "Authentication required"

    for path, method in (
        ("/api/reels/{reel_id}/categories", "post"),
        ("/api/reels/{reel_id}/categories/new", "post"),
        ("/api/reels/{reel_id}/categories/{category_id}", "delete"),
    ):
        operation = schema["paths"][path][method]
        csrf_headers = [
            parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "header" and parameter["name"] == "X-CSRF-Token"
        ]
        assert csrf_headers == [
            {
                "name": "X-CSRF-Token",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "title": "X-Csrf-Token"},
            }
        ]
        assert operation["responses"]["403"]["description"] == "CSRF token validation failed"

    for path in ("/auth/login", "/auth/callback"):
        assert "security" not in schema["paths"][path]["get"]
