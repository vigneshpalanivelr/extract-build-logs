import pytest
from types import SimpleNamespace
from error_notifier import notify_global_error, notify_slack, notify_email


@pytest.fixture
def request_mock():
    return SimpleNamespace(
        url=SimpleNamespace(path="/api/analyze"),
        method="POST",
        headers={"x-request-id": "req-123"},
    )


@pytest.fixture
def exception():
    return RuntimeError("Test exception")


# ---------------------------------------------------------
# notify_global_error
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_notify_global_error_invokes_slack_and_email(mocker, request_mock, exception):
    slack_spy = mocker.patch("error_notifier.notify_slack", autospec=True)
    email_spy = mocker.patch("error_notifier.notify_email", autospec=True)

    await notify_global_error(exception, request_mock)

    slack_spy.assert_called_once_with(exception, request_mock)
    email_spy.assert_called_once_with(exception, request_mock)


@pytest.mark.asyncio
async def test_notify_global_error_is_safe_on_internal_failure(mocker, request_mock, exception):
    mocker.patch(
        "error_notifier.notify_slack",
        side_effect=Exception("Slack down"),
    )
    mocker.patch("error_notifier.notify_email")

    # Must not raise
    await notify_global_error(exception, request_mock)


# ---------------------------------------------------------
# notify_email
# ---------------------------------------------------------
def test_notify_email_skips_when_smtp_not_configured(mocker, request_mock, exception):
    mocker.patch("error_notifier.SMTP_SERVER", None)
    mocker.patch("error_notifier.EMAIL_TO", [])

    smtp_spy = mocker.patch("smtplib.SMTP")

    notify_email(exception, request_mock)

    smtp_spy.assert_not_called()


def test_notify_email_sends_when_configured(mocker, request_mock, exception):
    mocker.patch("error_notifier.SMTP_SERVER", "localhost")
    mocker.patch("error_notifier.EMAIL_TO", ["ops@example.com"])

    smtp_mock = mocker.patch("smtplib.SMTP", autospec=True)
    server = smtp_mock.return_value.__enter__.return_value

    notify_email(exception, request_mock)

    server.sendmail.assert_called_once()


# ---------------------------------------------------------
# notify_slack
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_notify_slack_sends_dm(mocker, request_mock, exception):
    mocker.patch("error_notifier.SLACK_ALERT_EMAILS", ["dev@example.com"])
    mocker.patch(
        "error_notifier.get_slack_user_id",
        return_value="U123"
    )

    chat_spy = mocker.patch(
        "error_notifier.slack_client.chat_postMessage",
        autospec=True
    )

    await notify_slack(exception, request_mock)

    chat_spy.assert_called_once()
    args, kwargs = chat_spy.call_args
    assert "/api/analyze" in kwargs["text"]
    assert "RuntimeError" in kwargs["text"]


@pytest.mark.asyncio
async def test_notify_slack_handles_api_failure(mocker, request_mock, exception):
    mocker.patch("error_notifier.SLACK_ALERT_EMAILS", ["dev@example.com"])
    mocker.patch(
        "error_notifier.get_slack_user_id",
        return_value="U123"
    )

    mocker.patch(
        "error_notifier.slack_client.chat_postMessage",
        side_effect=Exception("Slack error"),
    )

    # Must not raise
    await notify_slack(exception, request_mock)
