from __future__ import annotations

from app.auth.routes import InvalidReturnPath, validate_local_return_path


def test_local_return_paths_accept_root_and_local_pathnames() -> None:
    assert validate_local_return_path("/") == "/"
    assert validate_local_return_path("/library") == "/library"
    assert validate_local_return_path("/reels/123") == "/reels/123"
    assert validate_local_return_path("/reels/123/details") == "/reels/123/details"


def test_local_return_paths_reject_external_and_ambiguous_forms() -> None:
    invalid_paths = (
        "https://evil.example",
        "http://evil.example",
        "//evil.example",
        "///evil.example",
        r"/\evil.example",
        r"\evil.example",
        "javascript:alert(1)",
        "/javascript:alert(1)",
        "/path?next=https://evil.example",
        "/path#fragment",
        "/library\x00",
        "/library\nnext",
        "/%2f%2fevil.example",
        "/%5cevil.example",
        "/%255cevil.example",
        "relative/path",
        "",
    )

    for path in invalid_paths:
        try:
            validate_local_return_path(path)
        except InvalidReturnPath:
            continue
        raise AssertionError(f"accepted invalid return path: {path!r}")
