import traceback
import os
import logging
import smtplib
from email.mime.text import MIMEText
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from fastapi import Request
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("error_notifier")

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
EMAIL_TO = [
    e.strip()
    for e in os.getenv("ALERT_EMAIL_TO", "").split(",")
    if e.strip()
]

logger.info(f"[ErrorNotifier] SMTP_SERVER: {SMTP_SERVER}")
logger.info(f"[ErrorNotifier] EMAIL_TO: {EMAIL_TO}")
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
            f"[ErrorNotifier] Slack lookup failed for {email}: "
            f"{e.response.get('error')}"
        )
    except Exception as e:
        logger.error(f"[ErrorNotifier] Unexpected Slack lookup error for {email}: {e}")

    return None


# -------------------------------------------------
# Slack DM notifier
# -------------------------------------------------
async def notify_slack(exc: Exception, request: Request):
    tb = traceback.format_exc()

    message = f"""
🚨 *BFA INTERNAL ERROR ALERT*

*Endpoint:* `{request.url.path}`
*Method:* `{request.method}`

*Exception:* `{type(exc).__name__}`
{str(exc)}
*Traceback (truncated):*
{tb[:3500]}
""".strip()

    for email in SLACK_ALERT_EMAILS:
        user_id = get_slack_user_id(email)
        if not user_id:
            logger.warning(f"[ErrorNotifier] Slack user not found for {email}")
            continue

        try:
            slack_client.chat_postMessage(
                channel=user_id,
                text=message
            )
            logger.info(f"[ErrorNotifier] Slack alert sent to {email} ({user_id})")
        except SlackApiError as e:
            logger.error(
                f"[ErrorNotifier] Slack DM failed for {email}: "
                f"{e.response.get('error')}"
            )
        except Exception as e:
            logger.error(f"[ErrorNotifier] Unexpected Slack DM error: {e}")


# -------------------------------------------------
# Email notifier (NO LOGIN)
# -------------------------------------------------
def notify_email(exc: Exception, request: Request):
    if not SMTP_SERVER or not EMAIL_TO:
        logger.warning("[ErrorNotifier] SMTP not configured; skipping email alert")
        return

    tb = traceback.format_exc()

    subject = f"[BFA ALERT] Internal error on {request.url.path}"
    body = f"""
Build Failure Analyzer encountered an internal exception.

Endpoint : {request.url.path}
Method   : {request.method}

Exception: {type(exc).__name__}
Message  : {str(exc)}

Traceback:
{tb}
"""

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(EMAIL_TO)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.sendmail(
                SMTP_FROM,
                EMAIL_TO,
                msg.as_string()
            )
        logger.info("[ErrorNotifier] Email alert sent successfully")
    except Exception as e:
        logger.error(f"[ErrorNotifier] Email send failed: {e}")


# -------------------------------------------------
# Unified notifier (SAFE)
# -------------------------------------------------
async def notify_global_error(exc: Exception, request: Request):
    try:
        await notify_slack(exc, request)
    except Exception as e:
        logger.error(f"[ErrorNotifier] Slack notification failed: {e}")

    try:
        notify_email(exc, request)
    except Exception as e:
        logger.error(f"[ErrorNotifier] Email notification failed: {e}")