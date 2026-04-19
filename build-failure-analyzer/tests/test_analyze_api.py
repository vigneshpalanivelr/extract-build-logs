import json
import hashlib

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def error_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------
# SME CACHE PATH
# ---------------------------------------------------------
def test_analyze_uses_sme_cache(mocker, client, auth_header):
    err = "gcc failed"
    h = error_hash(err)

    # SME cache hit
    mocker.patch(
        "analyzer_service.r.get",
        return_value=json.dumps({"fix_text": "SME FIX"})
    )

    dm_spy = mocker.patch("analyzer_service.send_dev_dm_fix")
    resolver_spy = mocker.patch("analyzer_service.resolver.resolve")

    payload = {
        "repo": "repo1",
        "branch": "main",
        "commit": "abc",
        "job_name": "build-job",
        "pipeline_id": "p1",
        "triggered_by": "dev@internal.com",
        "failed_steps": [
            {"step_name": "build", "error_lines": [err]}
        ]
    }

    resp = client.post("/api/analyze", json=payload, headers=auth_header)
    assert resp.status_code == 200

    resolver_spy.assert_not_called()
    dm_spy.assert_called_once()

    assert dm_spy.call_args.kwargs["source"] == "sme_cache"


# ---------------------------------------------------------
# AI CACHE PATH
# ---------------------------------------------------------
def test_analyze_uses_ai_cache(mocker, client, auth_header):
    err = "mvn test failed"

    # First get() call -> SME cache miss
    # Second get() call -> AI cache hit
    mocker.patch(
        "analyzer_service.r.get",
        side_effect=[None, json.dumps({"fix_text": "AI CACHED FIX"})]
    )

    dm_spy = mocker.patch("analyzer_service.send_dev_dm_fix")
    resolver_spy = mocker.patch("analyzer_service.resolver.resolve")

    payload = {
        "repo": "repo2",
        "branch": "dev",
        "commit": "def",
        "job_name": "build-job",
        "pipeline_id": "p2",
        "triggered_by": "dev@internal.com",
        "failed_steps": [
            {"step_name": "test", "error_lines": [err]}
        ]
    }

    resp = client.post("/api/analyze", json=payload, headers=auth_header)
    assert resp.status_code == 200

    resolver_spy.assert_not_called()
    dm_spy.assert_called_once()
    assert dm_spy.call_args.kwargs["source"] == "ai_cache"


# ---------------------------------------------------------
# VECTOR DB REUSE PATH
# ---------------------------------------------------------
def test_analyze_uses_vector_db_fix(mocker, client, auth_header):
    err = "npm install failed"

    mocker.patch("analyzer_service.r.get", return_value=None)

    mocker.patch(
        "analyzer_service.resolver.resolve",
        return_value={
            "source": "vector_db",
            "fix_text": "Known SME fix"
        }
    )

    dm_spy = mocker.patch("analyzer_service.send_dev_dm_fix")
    slack_spy = mocker.patch("analyzer_service.send_error_message")

    payload = {
        "repo": "repo3",
        "branch": "feature",
        "commit": "ghi",
        "job_name": "build-job",
        "pipeline_id": "p3",
        "triggered_by": "dev@internal.com",
        "failed_steps": [
            {"step_name": "deps", "error_lines": [err]}
        ]
    }

    resp = client.post("/api/analyze", json=payload, headers=auth_header)
    assert resp.status_code == 200

    slack_spy.assert_not_called()
    dm_spy.assert_called_once()
    assert dm_spy.call_args.kwargs["source"] == "vector_db"


# ---------------------------------------------------------
# AI GENERATED (COLD PATH)
# ---------------------------------------------------------
def test_analyze_ai_generated_flow(mocker, client, auth_header):
    err = "clang error: missing header"

    mocker.patch("analyzer_service.r.get", return_value=None)

    mocker.patch(
        "analyzer_service.resolver.resolve",
        return_value={
            "source": "ai_generated",
            "fix_text": "Install missing package"
        }
    )

    dm_spy = mocker.patch("analyzer_service.send_dev_dm_fix")
    slack_spy = mocker.patch("analyzer_service.send_error_message")
    store_fix_spy = mocker.patch("analyzer_service.store_fix")
    redis_setex = mocker.patch("analyzer_service.r.setex")

    payload = {
        "repo": "repo4",
        "branch": "main",
        "commit": "xyz",
        "job_name": "build-job",
        "pipeline_id": "p4",
        "triggered_by": "dev@internal.com",
        "failed_steps": [
            {"step_name": "compile", "error_lines": [err]}
        ]
    }

    resp = client.post("/api/analyze", json=payload, headers=auth_header)
    assert resp.status_code == 200

    slack_spy.assert_called_once()
    dm_spy.assert_called_once()
    store_fix_spy.assert_called_once()
    redis_setex.assert_called_once()

    assert dm_spy.call_args.kwargs["source"] == "ai_generated"


# ---------------------------------------------------------
# MULTIPLE FAILED STEPS
# ---------------------------------------------------------
def test_analyze_multiple_failures(mocker, client, auth_header):
    mocker.patch("analyzer_service.r.get", return_value=None)

    mocker.patch(
        "analyzer_service.resolver.resolve",
        side_effect=[
            {"source": "ai_generated", "fix_text": "Fix 1"},
            {"source": "ai_generated", "fix_text": "Fix 2"},
        ]
    )

    dm_spy = mocker.patch("analyzer_service.send_dev_dm_fix")
    slack_spy = mocker.patch("analyzer_service.send_error_message")

    payload = {
        "repo": "repo5",
        "branch": "main",
        "commit": "zzz",
        "job_name": "build-job",
        "pipeline_id": "p5",
        "triggered_by": "dev@internal.com",
        "failed_steps": [
            {"step_name": "build", "error_lines": ["err1"]},
            {"step_name": "test", "error_lines": ["err2"]},
        ]
    }

    resp = client.post("/api/analyze", json=payload, headers=auth_header)
    assert resp.status_code == 200

    assert dm_spy.call_count == 2
    assert slack_spy.call_count == 2