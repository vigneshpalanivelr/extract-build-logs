import json
import pytest
from unittest.mock import MagicMock, ANY

import slack_helper


# -----------------------------
# Fixtures
# -----------------------------

@pytest.fixture
def redis_mock(mocker):
    r = MagicMock()
    mocker.patch.object(slack_helper, "redis_conn", r)
    return r


@pytest.fixture
def slack_client_mock(mocker):
    client = MagicMock()
    mocker.patch.object(slack_helper, "client", client)
    return client


# -----------------------------
# store_fix / get_fix
# -----------------------------

def test_store_fix_basic(redis_mock):
    slack_helper.store_fix(
        error_id="err123",
        error_title="gcc failed",
        ai_fix_text="Install gcc",
        source="ai",
        triggered_by="dev@company.com",
        metadata={"repo": "repo1"}
    )

    redis_mock.set.assert_any_call(
        "fix:err123",
        json.dumps({
            "error": "gcc failed",
            "fix": "Install gcc",
            "source": "ai",
            "triggered_by": "dev@company.com",
            "metadata": {"repo": "repo1"}
        })
    )


def test_store_fix_creates_error_map(redis_mock):
    slack_helper.store_fix(
        error_id="e1",
        error_title="npm failed",
        ai_fix_text="Run npm install"
    )

    redis_mock.set.assert_any_call("error_map:npm failed", "e1")


def test_store_fix_creates_thread_map(redis_mock):
    slack_helper.store_fix(
        error_id="e2",
        error_title="mvn failed",
        ai_fix_text="Run mvn clean",
        message_ts="123.456",
        channel_id="C1"
    )

    redis_mock.set.assert_any_call("thread_map:C1:123.456", "e2")


def test_get_fix_by_error_id(redis_mock):
    redis_mock.exists.return_value = True
    redis_mock.get.return_value = json.dumps({
        "error": "gcc failed",
        "fix": "Install gcc"
    })

    fix = slack_helper.get_fix("err123")
    assert fix["fix"] == "Install gcc"


def test_get_fix_by_error_text(redis_mock):
    redis_mock.exists.side_effect = [False, True]
    redis_mock.get.side_effect = ["err123", json.dumps({"fix": "Known fix"})]

    fix = slack_helper.get_fix("gcc failed")
    assert fix["fix"] == "Known fix"


def test_get_fix_returns_empty_when_missing(redis_mock):
    redis_mock.exists.return_value = False
    fix = slack_helper.get_fix("unknown")
    assert fix == {}


# -----------------------------
# Slack block generation
# -----------------------------

def test_build_action_block():
    block = slack_helper.build_action_block("err123")

    assert block["type"] == "actions"
    assert len(block["elements"]) == 3


def test_ai_fix_to_blocks_metadata_header():
    blocks = slack_helper.ai_fix_to_blocks(
        error_title="gcc failed",
        ai_fix_text="Install gcc",
        error_id="e1",
        metadata={
            "repo": "repo1",
            "branch": "main",
            "commit": "abc"
        }
    )

    header = blocks[0]["text"]["text"]
    assert "repo1" in header
    assert "main" in header
    assert "abc" in header


def test_ai_fix_to_blocks_handles_long_fix():
    long_fix = "step\n" * 2000

    blocks = slack_helper.ai_fix_to_blocks(
        error_title="long error",
        ai_fix_text=long_fix,
        error_id="e2",
        metadata={}
    )

    # Must split into multiple blocks
    assert len(blocks) > 2


# -----------------------------
# send_error_message
# -----------------------------

def test_send_error_message_posts_to_slack(slack_client_mock, redis_mock):
    slack_client_mock.chat_postMessage.return_value = {
        "ts": "111.222",
        "channel": "C1"
    }

    slack_helper.send_error_message(
        error_title="gcc failed",
        ai_fix_text="Install gcc",
        error_id="err123",
        metadata={"triggered_by": "dev@company.com"}
    )

    slack_client_mock.chat_postMessage.assert_called_once()
    redis_mock.set.assert_any_call("fix:err123", ANY)


def test_send_error_message_handles_slack_failure(
    mocker, slack_client_mock
):
    slack_client_mock.chat_postMessage.side_effect = Exception("Slack down")

    # Should not raise
    slack_helper.send_error_message(
        error_title="gcc failed",
        ai_fix_text="Install gcc",
        error_id="err123"
    )


# -----------------------------
# Error summarization
# -----------------------------

def test_summarize_error_with_ai_success(mocker):
    mocker.patch(
        "slack_helper.call_llm",
        return_value="• Error summary"
    )

    summary = slack_helper.summarize_error_with_ai("very long error")
    assert "Error summary" in summary


def test_summarize_error_with_ai_failure(mocker):
    mocker.patch(
        "slack_helper.call_llm",
        side_effect=Exception("LLM down")
    )

    summary = slack_helper.summarize_error_with_ai("error")
    assert "Summary unavailable" in summary