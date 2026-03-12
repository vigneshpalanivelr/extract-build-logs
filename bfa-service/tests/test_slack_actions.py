import json
import pytest
from fastapi.testclient import TestClient

import analyzer_service


@pytest.fixture
def client():
    return TestClient(analyzer_service.app)


@pytest.fixture(autouse=True)
def mock_slack_signature(mocker):
    """
    Slack signature validation always passes
    """
    mocker.patch.object(
        analyzer_service.sig_verifier,
        "is_valid_request",
        return_value=True,
    )


@pytest.fixture
def slack_mocks(mocker):
    """
    Common Slack + Redis mocks
    """
    mocker.patch.object(analyzer_service.client, "chat_postMessage")
    mocker.patch.object(analyzer_service.client, "chat_update")
    mocker.patch.object(analyzer_service, "send_dev_dm_fix")
    mocker.patch.object(analyzer_service, "store_fix")
    mocker.patch.object(analyzer_service.db, "save_fix_to_db")

    # Redis helpers
    mocker.patch.object(analyzer_service.redis_conn, "set")
    mocker.patch.object(analyzer_service.redis_conn, "get")
    mocker.patch.object(analyzer_service.redis_conn, "delete")
    mocker.patch.object(analyzer_service.redis_conn, "keys", return_value=[])


# -------------------------------------------------------------------
# Slack ACTIONS tests
# -------------------------------------------------------------------

def _build_action_payload(action_id="approve_err123"):
    return {
        "type": "block_actions",
        "user": {"id": "U123"},
        "actions": [
            {
                "action_id": action_id,
                "value": "err123",
            }
        ],
        "channel": {"id": "C123"},
        "message": {
            "ts": "111.222",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "Error"}},
                {"block_id": "actions_block", "type": "actions"},
            ],
        },
    }


def test_slack_action_approve_fix(client, slack_mocks, mocker):
    mocker.patch(
        "analyzer_service.get_fix",
        return_value={
            "error": "gcc failed",
            "fix": "Install gcc",
            "message_ts": "111.222",
            "triggered_by": "dev.example.com",
            "metadata": {},
        },
    )
    mocker.patch("analyzer_service.get_user_display_name", return_value="SME User")

    resp = client.post(
        "/bfa/slack/actions",
        data={"payload": json.dumps(_build_action_payload("approve_err123"))},
    )

    assert resp.status_code == 200
    analyzer_service.db.save_fix_to_db.assert_called_once()
    analyzer_service.store_fix.assert_called_once()
    analyzer_service.send_dev_dm_fix.assert_called_once()


def test_slack_action_edit_fix(client, slack_mocks, mocker):
    mocker.patch(
        "analyzer_service.get_fix",
        return_value={
            "error": "npm install failed",
            "fix": "Clear cache",
            "message_ts": "222.333",
        },
    )
    mocker.patch("analyzer_service.get_user_display_name", return_value="SME User")

    resp = client.post(
        "/bfa/slack/actions",
        data={"payload": json.dumps(_build_action_payload("edit_err123"))},
    )

    assert resp.status_code == 200
    analyzer_service.redis_conn.set.assert_called_once()
    analyzer_service.client.chat_postMessage.assert_called_once()


def test_slack_action_discard_fix(client, slack_mocks, mocker):
    mocker.patch(
        "analyzer_service.get_fix",
        return_value={
            "error": "timeout",
            "fix": "Increase timeout",
        },
    )
    mocker.patch("analyzer_service.get_user_display_name", return_value="SME User")

    resp = client.post(
        "/bfa/slack/actions",
        data={"payload": json.dumps(_build_action_payload("discard_err123"))},
    )

    assert resp.status_code == 200
    analyzer_service.redis_conn.delete.assert_called_once()


def test_slack_action_missing_fix(client, slack_mocks, mocker):
    mocker.patch("analyzer_service.get_fix", return_value={})
    mocker.patch("analyzer_service.get_user_display_name", return_value="SME User")

    resp = client.post(
        "/bfa/slack/actions",
        data={"payload": json.dumps(_build_action_payload("approve_err123"))},
    )

    assert resp.status_code == 200
    analyzer_service.client.chat_postMessage.assert_called_once()


# -------------------------------------------------------------------
# Slack EVENTS tests
# -------------------------------------------------------------------

def test_slack_event_url_verification(client):
    payload = {"type": "url_verification", "challenge": "abc123"}

    resp = client.post("/bfa/slack/events", json=payload)

    assert resp.status_code == 200
    assert resp.json()["challenge"] == "abc123"


def test_slack_event_message_ignored_when_no_edit_mode(client, slack_mocks, mocker):
    mocker.patch.object(analyzer_service.redis_conn, "keys", return_value=[])

    payload = {
        "event": {
            "type": "message",
            "user": "U123",
            "channel": "C123",
            "text": "Edited fix text",
            "thread_ts": "111.222",
        }
    }

    resp = client.post("/bfa/slack/events", json=payload)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_slack_event_edit_fix_success(client, slack_mocks, mocker):
    mocker.patch.object(
        analyzer_service.redis_conn,
        "keys",
        return_value=["last_edit:C123:err123"],
    )
    mocker.patch.object(
        analyzer_service.redis_conn,
        "get",
        side_effect=lambda k: "U123" if "last_edit" in k else "err123",
    )

    mocker.patch(
        "analyzer_service.get_fix",
        return_value={
            "error": "gcc failed",
            "message_ts": "111.222",
            "triggered_by": "dev.example.com",
            "metadata": {},
        },
    )
    mocker.patch("analyzer_service.get_user_display_name", return_value="SME User")

    payload = {
        "event": {
            "type": "message",
            "user": "U123",
            "channel": "C123",
            "text": "Install build-essential",
            "thread_ts": "111.222",
        }
    }

    resp = client.post("/bfa/slack/events", json=payload)

    assert resp.status_code == 200
    analyzer_service.db.save_fix_to_db.assert_called_once()
    analyzer_service.store_fix.assert_called_once()
    analyzer_service.send_dev_dm_fix.assert_called_once()