"""T-207: внешний URL и запрет в demo."""

from app.ingest.sources import is_external_url


def test_mock_feed_is_not_external() -> None:
    assert is_external_url("http://127.0.0.1:8000/api/public/mock-social-feed") is False
    assert is_external_url("https://example.com/feed") is True
    assert is_external_url(None) is False
