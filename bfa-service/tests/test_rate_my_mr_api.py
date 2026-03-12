import pytest


# -----------------------------
# Helpers
# -----------------------------

@pytest.fixture
def payload():
    return {
        "repo": "repo1",
        "branch": "main",
        "author": "dev.example.com",
        "commit": "abc123",
        "prompt": "Please review this MR diff",
        "mr_url": "https://git.example.com/mr/1"
    }


# -----------------------------
# Tests
# -----------------------------

def test_rate_my_mr_success(mocker, client, auth_header, payload):
    # Mock LLM response
    mocker.patch(
        "llm_openwebui_client.analyze_with_llm",
        return_value={
            "quality_score": 8,
            "security_score": 9,
            "maintainability_score": 7,
            "overall_summary": "Looks good",
            "potential_vulnerabilities": [],
            "recommended_improvements": ["Add tests"]
        }
    )

    # Mock Slack user lookup
    mocker.patch(
        "analyzer_service.client.users_lookupByEmail",
        return_value={"user": {"id": "U123"}}
    )

    # Mock Slack DM
    chat_spy = mocker.patch("analyzer_service.client.chat_postMessage")

    resp = client.post("/api/rate-my-mr", json=payload, headers=auth_header)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    chat_spy.assert_called_once()


def test_rate_my_mr_user_not_found(mocker, client, auth_header, payload):
    mocker.patch(
        "llm_openwebui_client.analyze_with_llm",
        return_value={"summary_text": "Looks fine"}
    )

    # Slack lookup fails
    mocker.patch(
        "analyzer_service.client.users_lookupByEmail",
        side_effect=Exception("user_not_found")
    )

    chat_spy = mocker.patch("analyzer_service.client.chat_postMessage")

    resp = client.post("/api/rate-my-mr", json=payload, headers=auth_header)

    assert resp.status_code == 200
    chat_spy.assert_not_called()


def test_rate_my_mr_empty_prompt(client, auth_header, payload):
    payload["prompt"] = ""

    resp = client.post("/api/rate-my-mr", json=payload, headers=auth_header)

    assert resp.status_code == 400
    assert "prompt cannot be empty" in resp.text


def test_rate_my_mr_llm_failure(mocker, client, auth_header, payload):
    mocker.patch(
        "llm_openwebui_client.analyze_with_llm",
        side_effect=RuntimeError("LLM failed")
    )

    resp = client.post("/api/rate-my-mr", json=payload, headers=auth_header)

    assert resp.status_code == 500
