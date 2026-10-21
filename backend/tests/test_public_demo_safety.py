"""The live demo is reached through a tunnel that connects to the API from 127.0.0.1, so "local only"
must look at the tunnel's headers too, and internet visitors are rate limited.

Requests here carry the headers cloudflared adds to every forwarded request.
"""

import pytest
from fastapi.testclient import TestClient

import app as api
import runs
from checker.feedback import FeedbackStore
from checker.pdf_work import InlinePdfWork
from checker.pipeline import ReviewPipeline
from monitoring import RateLimiter

THROUGH_TUNNEL = {"Cf-Connecting-Ip": "203.0.113.7", "Cf-Ray": "8d1f2a3b4c5d6e7f-BOM", "X-Forwarded-For": "203.0.113.7"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FeedbackStore(tmp_path / "feedback.json")
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(api, "feedback_store", store)
    monkeypatch.setattr(api, "pdf_work", InlinePdfWork())
    monkeypatch.setattr(api, "pipeline", ReviewPipeline(feedback=store, pdf=api.pdf_work))
    return TestClient(api.app)


def test_server_activity_is_not_visible_through_the_tunnel(client):
    """The request log holds other visitors' run ids (and so their artwork); the waiver list names their files."""
    assert client.get("/api/metrics/requests").status_code == 200  # on this machine
    assert client.get("/api/metrics/requests", headers=THROUGH_TUNNEL).status_code == 403
    assert client.get("/api/feedback").status_code == 200
    assert client.get("/api/feedback", headers=THROUGH_TUNNEL).status_code == 403
    # what the web app itself needs still works for visitors
    assert client.get("/api/health", headers=THROUGH_TUNNEL).status_code == 200


def test_one_visitor_cannot_flood_reviews(client, monkeypatch):
    monkeypatch.setattr(api.review_limit, "limit", 2)
    monkeypatch.setattr(api.review_limit, "_hits", {})
    offline = {"use_ai": "false", "use_samples": "true"}
    assert client.post("/api/review", data=offline, headers=THROUGH_TUNNEL).status_code == 200
    assert client.post("/api/review", data=offline, headers=THROUGH_TUNNEL).status_code == 200
    third = client.post("/api/review", data=offline, headers=THROUGH_TUNNEL)
    assert third.status_code == 429 and "try again in" in third.json()["detail"]
    other_visitor = {**THROUGH_TUNNEL, "Cf-Connecting-Ip": "198.51.100.9"}
    assert client.post("/api/review", data=offline, headers=other_visitor).status_code == 200
    assert client.post("/api/review", data=offline).status_code == 200  # this machine is never limited


def test_the_limit_window_slides(monkeypatch):
    import monitoring

    clock = [1000.0]
    monkeypatch.setattr(monitoring.time, "monotonic", lambda: clock[0])
    limiter = RateLimiter(limit=1, window=60, what="reviews")

    class Request:
        client = type("C", (), {"host": "127.0.0.1"})()
        headers = {"cf-connecting-ip": "203.0.113.7"}

    limiter(Request())
    with pytest.raises(Exception, match="Too many reviews"):
        limiter(Request())
    clock[0] += 61
    limiter(Request())  # the first one has left the window
