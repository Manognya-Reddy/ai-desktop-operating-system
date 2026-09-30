import httpx
from app.config import settings
from app.services.workspace import misinfo_check


class FakeFactCheckResponse:
    def __init__(self, claims):
        self.claims = claims

    def raise_for_status(self):
        pass

    def json(self):
        return {"claims": self.claims}


def test_static_domain_list_catches_known_bad_domain():
    result = misinfo_check.check_url("https://infowars.com/some-article")
    assert result is not None


def test_static_domain_list_ignores_clean_domain():
    result = misinfo_check.check_url("https://github.com/torvalds/linux")
    assert result is None


def test_factcheck_api_not_called_without_key(monkeypatch):
    monkeypatch.setattr(settings, "FACTCHECK_API_KEY", "")
    called = []
    monkeypatch.setattr(httpx, "get", lambda *a, **k: called.append(1))
    result = misinfo_check.check_url("https://some-clean-blog.com/x", title="Some headline")
    assert result is None
    assert called == []


def test_factcheck_api_flags_false_rated_claim(monkeypatch):
    monkeypatch.setattr(settings, "FACTCHECK_API_KEY", "fake-key")
    claims = [{
        "text": "Vaccines contain microchips",
        "claimReview": [{
            "publisher": {"name": "PolitiFact"},
            "textualRating": "Pants on Fire",
        }],
    }]
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeFactCheckResponse(claims))
    result = misinfo_check.check_url(
        "https://some-clean-looking-blog.com/article",
        title="Vaccines contain microchips, doctor claims",
    )
    assert result is not None
    assert "PolitiFact" in result


def test_factcheck_api_ignores_true_rated_claim(monkeypatch):
    monkeypatch.setattr(settings, "FACTCHECK_API_KEY", "fake-key")
    claims = [{
        "text": "The sky is blue",
        "claimReview": [{
            "publisher": {"name": "Reuters"},
            "textualRating": "True",
        }],
    }]
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeFactCheckResponse(claims))
    result = misinfo_check.check_url("https://reuters.com/article", title="The sky is blue")
    assert result is None


def test_factcheck_api_failure_falls_back_to_none(monkeypatch):
    monkeypatch.setattr(settings, "FACTCHECK_API_KEY", "fake-key")

    def raise_error(*a, **k):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "get", raise_error)
    result = misinfo_check.check_url("https://some-clean-blog.com/x", title="Some headline")
    assert result is None


def test_known_bad_domain_skips_api_call(monkeypatch):
    monkeypatch.setattr(settings, "FACTCHECK_API_KEY", "fake-key")
    called = []
    monkeypatch.setattr(httpx, "get", lambda *a, **k: called.append(1))
    result = misinfo_check.check_url("https://infowars.com/x", title="something")
    assert result is not None
    assert called == []
