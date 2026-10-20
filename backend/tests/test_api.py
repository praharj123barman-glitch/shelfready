"""The HTTP API end to end: review, images, feedback, compare, and every error path.

Runs offline (use_ai off) against a temporary runs folder and feedback file,
so it never touches real review history.
"""

import pytest
from fastapi.testclient import TestClient

import app as api
import runs
from checker.feedback import FeedbackStore
from checker.pdf_work import InlinePdfWork
from checker.pipeline import ReviewPipeline

OFFLINE = {"use_ai": "false"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FeedbackStore(tmp_path / "feedback.json")
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(api, "feedback_store", store)
    monkeypatch.setattr(api, "pdf_work", InlinePdfWork())  # the process mode has its own test below
    monkeypatch.setattr(api, "pipeline", ReviewPipeline(feedback=store, pdf=api.pdf_work))
    return TestClient(api.app)


@pytest.fixture
def sample_run(client):
    response = client.post("/api/review", data={**OFFLINE, "use_samples": "true", "market": "US"})
    assert response.status_code == 200
    return response.json()


def finding(run, check):
    return next(f for f in run["result"]["report"]["findings"] if f["check"] == check)


def test_sample_review_is_stored_with_both_renders(client, sample_run):
    run_id = sample_run["run_id"]
    assert sample_run["result"]["report"]["summary"]["definite"] > 0
    assert client.get(f"/api/runs/{run_id}/artwork.png").status_code == 200
    assert client.get(sample_run["print_image_url"]).status_code == 200
    assert sample_run["panels"]["front"]


def test_false_alarm_is_recorded_and_can_be_undone(client, sample_run):
    run_id = sample_run["run_id"]
    target = finding(sample_run, "gmo_wording")
    out = client.post(f"/api/runs/{run_id}/feedback",
                      json={"finding_id": target["id"], "decision": "false_alarm", "reason": "approved"}).json()
    assert client.get("/api/feedback").json()["waivers"][0]["id"] == out["waiver"]["id"]
    assert client.delete(f"/api/waivers/{out['waiver']['id']}").json() == {"removed": True}
    assert client.delete(f"/api/waivers/{out['waiver']['id']}").status_code == 404


def test_a_passed_check_cannot_be_a_false_alarm(client, sample_run):
    passed = next(f for f in sample_run["result"]["report"]["findings"] if f["verdict"] == "pass")
    response = client.post(f"/api/runs/{sample_run['run_id']}/feedback",
                           json={"finding_id": passed["id"], "decision": "false_alarm"})
    assert response.status_code == 400


def test_compare_reviews_the_new_proof_with_the_old_inputs(client, sample_run):
    response = client.post(f"/api/runs/{sample_run['run_id']}/compare", data={**OFFLINE, "use_sample_v2": "true"})
    body = response.json()
    assert response.status_code == 200
    assert len(body["comparison"]["text_changes"]) == 4
    assert body["previous_image_url"] == f"/api/runs/{sample_run['run_id']}/artwork.png"


def test_a_run_can_be_reopened_with_current_waivers(client, sample_run):
    run_id = sample_run["run_id"]
    reopened = client.get(f"/api/runs/{run_id}").json()
    assert reopened == sample_run  # same response as when it was made

    target = finding(sample_run, "gmo_wording")
    waiver = client.post(f"/api/runs/{run_id}/feedback",
                         json={"finding_id": target["id"], "decision": "false_alarm", "reason": "ok"}).json()["waiver"]
    assert finding(client.get(f"/api/runs/{run_id}").json(), "gmo_wording")["waiver"]["id"] == waiver["id"]
    client.delete(f"/api/waivers/{waiver['id']}")
    assert finding(client.get(f"/api/runs/{run_id}").json(), "gmo_wording")["waiver"] is None  # undo shows too


def test_a_compare_run_reopens_with_its_comparison(client, sample_run):
    new = client.post(f"/api/runs/{sample_run['run_id']}/compare", data={**OFFLINE, "use_sample_v2": "true"}).json()
    again = client.get(f"/api/runs/{new['run_id']}").json()
    assert again["comparison"] == new["comparison"] and again["previous_image_url"] == new["previous_image_url"]


def test_a_run_saved_before_view_json_still_opens(client, sample_run):
    (runs.RUNS_DIR / sample_run["run_id"] / "view.json").unlink()
    again = client.get(f"/api/runs/{sample_run['run_id']}").json()
    assert again["page_width"] == sample_run["page_width"] and again["panels"] == sample_run["panels"]


def test_unknown_and_malformed_runs(client):
    assert client.get("/api/runs/nope123").status_code == 404
    assert client.get("/api/runs/bad..id").status_code == 400
    assert client.get("/api/runs/nope123/artwork.png").status_code == 404
    assert client.get("/api/runs/..x/artwork.png").status_code == 400


def test_bad_uploads_are_rejected_and_leave_nothing_behind(client):
    assert client.post("/api/review", data=OFFLINE).status_code == 400  # no artwork
    wrong_type = client.post("/api/review", data=OFFLINE, files={"artwork": ("a.png", b"x", "image/png")})
    assert wrong_type.status_code == 400
    empty = client.post("/api/review", data=OFFLINE, files={"artwork": ("a.pdf", b"", "application/pdf")})
    assert empty.status_code == 400
    damaged = client.post("/api/review", data=OFFLINE, files={"artwork": ("a.pdf", b"not a pdf", "application/pdf")})
    assert damaged.status_code == 422 and "damaged or not a PDF" in damaged.json()["detail"]
    assert not any(runs.RUNS_DIR.iterdir())  # every failed run folder was removed
