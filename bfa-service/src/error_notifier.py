import traceback
import os
import smtplib
from email.mime.text import MIMEText

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from fastapi import Request
from dotenv import load_dotenv
from logging_config import get_logger

load_dotenv()

logger = get_logger("error_notifier")

# -------------------------------------------------
# Slack configuration
# -------------------------------------------------
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_ALERT_EMAILS = [
    e.strip()
    for e in os.getenv("ALERT_SLACK_EMAILS", "").split(",")
    if e.strip()
]

slack_client = WebClient(token=SLACK_TOKEN)

# simple in-memory cache: email -> user_id
_SLACK_USER_CACHE = {}

# -------------------------------------------------
# Email configuration (NO AUTH)
# -------------------------------------------------
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "25"))
SMTP_FROM = os.getenv("SMTP_FROM", "bfa-alerts@localhost")
SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "10"))
TRACEBACK_MAX_CHARS = int(os.getenv("TRACEBACK_MAX_CHARS", "3500"))
EMAIL_TO = [
    e.strip()
    for e in os.getenv("ALERT_EMAIL_TO", "").split(",")
    if e.strip()
]

logger.info("[ErrorNotifier] SMTP_SERVER: %s", SMTP_SERVER)
logger.info("[ErrorNotifier] EMAIL_TO: %s", EMAIL_TO)


# -------------------------------------------------
# Resolve Slack user ID from email
# -------------------------------------------------
def get_slack_user_id(email: str) -> str | None:
    if email in _SLACK_USER_CACHE:
        return _SLACK_USER_CACHE[email]

    try:
        resp = slack_client.users_lookupByEmail(email=email)
        user_id = resp["user"]["id"]
        _SLACK_USER_CACHE[email] = user_id
        return user_id

    except SlackApiError as e:
        logger.error(
            "[ErrorNotifier] Slack lookup failed for %s: %s",
            email, e.response.get('error')
        )
    except Exception as e:
        logger.error("[ErrorNotifier] Unexpected Slack lookup error for %s: %s", email, e)

    return None


# -------------------------------------------------
# Slack DM notifier
# -------------------------------------------------
async def notify_slack(exc: Exception, request: Request):
    tb = traceback.format_exc()

    message = (
        "[ALERT] *BFA INTERNAL ERROR ALERT*\n\n"
        f"*Endpoint:* `{request.url.path}`\n"
        f"*Method:* `{request.method}`\n\n"
        f"*Exception:* `{type(exc).__name__}`\n"
        f"{str(exc)}\n"
        f"*Traceback (truncated):*\n"
        f"{tb[:TRACEBACK_MAX_CHARS]}"
    )

    for email in SLACK_ALERT_EMAILS:
        user_id = get_slack_user_id(email)
        if not user_id:
            logger.warning("[ErrorNotifier] Slack user not found for %s", email)
            continue

        try:
            slack_client.chat_postMessage(
                channel=user_id,
                text=message
            )
            logger.info("[ErrorNotifier] Slack alert sent to %s (%s)", email, user_id)
        except SlackApiError as e:
            logger.error(
                "[ErrorNotifier] Slack DM failed for %s: %s",
                email, e.response.get('error')
            )
        except Exception as e:
            logger.error("[ErrorNotifier] Unexpected Slack DM error: %s", e)


# -------------------------------------------------
# Email notifier (NO LOGIN)
# -------------------------------------------------
def notify_email(exc: Exception, request: Request):
    if not SMTP_SERVER or not EMAIL_TO:
        logger.warning("[ErrorNotifier] SMTP not configured; skipping email alert")
        return

    tb = traceback.format_exc()

    subject = f"[BFA ALERT] Internal error on {request.url.path}"
    body = (
        "Build Failure Analyzer encountered an internal exception.\n\n"
        f"Endpoint : {request.url.path}\n"
        f"Method   : {request.method}\n\n"
        f"Exception: {type(exc).__name__}\n"
        f"Message  : {str(exc)}\n\n"
        f"Traceback:\n{tb}"
    )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(EMAIL_TO)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
            server.sendmail(
                SMTP_FROM,
                EMAIL_TO,
                msg.as_string()
            )
        logger.info("[ErrorNotifier] Email alert sent successfully")
    except Exception as e:
        logger.error("[ErrorNotifier] Email send failed: %s", e)


# -------------------------------------------------
# Unified notifier (SAFE)
# -------------------------------------------------
async def notify_global_error(exc: Exception, request: Request):
    try:
        await notify_slack(exc, request)
    except Exception as e:
        logger.error("[ErrorNotifier] Slack notification failed: %s", e)

    try:
        notify_email(exc, request)
    except Exception as e:
        logger.error("[ErrorNotifier] Email notification failed: %s", e)
