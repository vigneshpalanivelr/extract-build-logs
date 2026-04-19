#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

import os
import json
import time
import threading
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
import redis
from llm_openwebui_client import call_llm

load_dotenv()

client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
channel = os.getenv("SLACK_CHANNEL")

# Connect to Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

redis_conn = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

def store_fix(error_id, error_title, ai_fix_text, source="ai", approver=None, message_ts=None, channel_id=None, triggered_by=None, metadata=None):
    """
    Stores the fix by error_id and maintains the mapping from error_text -> error_id.
    Also (if provided) stores the Slack message_ts and a thread map: thread_map:<channel_id>:<message_ts> -> error_id
    Keys:
      - fix:<error_id> = {"error": ..., "fix": ..., "source": ..., "approved_by": ..., "message_ts": ...}
      - error_map:<error_text> = <error_id>
      - thread_map:<channel_id>:<message_ts> = <error_id>   (only if message_ts & channel_id provided)
    """
    data = {
        "error": error_title,
        "fix": ai_fix_text or "",
        "source": source
    }
    if approver:
        data["approved_by"] = approver
    if triggered_by:
        data["triggered_by"] = triggered_by
    if message_ts:
        data["message_ts"] = message_ts
    if metadata:
        data["metadata"] = metadata

    # 1) Store the fix by error_id
    redis_conn.set(f"fix:{error_id}", json.dumps(data))

    # 2) Map the error text to this error_id (latest wins)
    redis_conn.set(f"error_map:{error_title}", error_id)

    # 3) If we know the Slack thread, map it to error_id as well
    if message_ts and channel_id:
        redis_conn.set(f"thread_map:{channel_id}:{message_ts}", error_id)

def get_fix(key):
    """
    Fetches a fix. 'key' can be either:
      - error_id  (we look up fix:<error_id>)
      - error_text (we resolve error_map:<error_text> -> error_id -> fix:<error_id>)
    Returns {} if not found or JSON parse fails.
    """
    # Try direct fix:<key> first (assume key is an error_id)
    direct_key = f"fix:{key}"
    if redis_conn.exists(direct_key):
        raw = redis_conn.get(direct_key)
        try:
            return json.loads(raw)
        except Exception:
            return {}

    # Otherwise, assume 'key' is an error_text and resolve via error_map
    mapped_id = redis_conn.get(f"error_map:{key}")
    if not mapped_id:
        return {}

    mapped_fix_key = f"fix:{mapped_id}"
    if not redis_conn.exists(mapped_fix_key):
        return {}

    raw = redis_conn.get(mapped_fix_key)
    try:
        return json.loads(raw)
    except Exception:
        return {}


# -----------------------------
# Text Chunking Utility
# -----------------------------
def chunk_text(text, max_len=2500):
    text = text or ""
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + max_len])
        start += max_len
    return chunks


# -----------------------------
# Build Interactive Action Block
# -----------------------------
def build_action_block(error_id):
    return {
        "type": "actions",
        "block_id": f"actions_{error_id}",
        "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "✅ Approve"},
             "style": "primary", "value": f"approve_{error_id}", "action_id": f"approve_{error_id}"},
            {"type": "button", "text": {"type": "plain_text", "text": "✏️ Edit"},
             "value": f"edit_{error_id}", "action_id": f"edit_{error_id}"},
            {"type": "button", "text": {"type": "plain_text", "text": "🗑️ Discard"},
             "style": "danger", "value": f"discard_{error_id}", "action_id": f"discard_{error_id}"}
        ]
    }


# -----------------------------
# summarize long error logs into short bullets
# -----------------------------
def summarize_error_with_ai(full_error_text: str) -> str:
    """
    Summarizes long error logs into clean 4-6 bullet points.
    """
    prompt = f"""
    You are a CI/CD build log analyzer. Summarize the following error log
    into EXACTLY 4–6 bullet points. Use concise engineering language.

    Error log:
    -------------------
    {full_error_text}
    -------------------
    """
    try:
        summary = call_llm(
            prompt=prompt,
            system_prompt="You summarize developer build logs clearly.",
            temperature=0.2,
            max_tokens=300
        )
        return summary.strip()
    except Exception as e:
        return f"• Error log too large to display ({len(full_error_text)} chars)\n• Summary unavailable due to LLM error: {e}"


def ai_fix_to_blocks(error_title, ai_fix_text, error_id, metadata):
    max_block_len = 2500

    # Build header with pipeline / repo context
    header_text = ""

    if metadata.get("pipeline_id"):
        header_text += f"\n🔗 <{metadata['pipeline_id']}|View Pipeline Log>"
    if metadata.get("repo"):
        header_text += f"\n🗂️ *Repository:* `{metadata['repo']}`"
    if metadata.get("branch"):
        header_text += f"\n🌿 *Branch:* `{metadata['branch']}`"
    if metadata.get("commit"):
        header_text += f"\n🔖 *Commit:* `{metadata['commit']}`"
    if metadata.get("job_name"):
        header_text += f"\n⚙️ *Job:* `{metadata['job_name']}`"
    if metadata.get("step_name"):
        header_text += f"\n🧩 *Step:* `{metadata['step_name']}`"

    blocks = [{
        "type": "section",
        "text": {"type": "mrkdwn", "text": header_text}
    }]

    # ---- FIX: preserve markdown & convert **bold** -> *bold* for Slack ----
    text = ai_fix_text or ""
    lines = text.split("\n")
    current_lines = []
    inside_code = False

    def flush_current():
        nonlocal current_lines
        if not current_lines:
            return

        chunk_text = "\n".join(current_lines)
        # enforce Slack block size safety
        start = 0
        while start < len(chunk_text):
            chunk = chunk_text[start:start + max_block_len]
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": chunk}
            })
            start += max_block_len
        current_lines = []

    for line in lines:
        stripped = line.strip()

        # Handle fenced code blocks (```), do NOT touch content inside
        if stripped.startswith("```"):
            if inside_code:
                # closing fence
                current_lines.append(line)
                flush_current()
                inside_code = False
            else:
                # opening fence
                flush_current()
                current_lines.append(line)
                inside_code = True
            continue

        if not inside_code:
            # Slack uses *bold*, not **bold** → convert outside code blocks
            line = line.replace("**", "*")

        current_lines.append(line)

    flush_current()

    # Add action buttons
    blocks.append(build_action_block(error_id))
    return blocks


# -----------------------------
#  Send Error + AI Fix Message to Slack
# -----------------------------
def send_error_message(error_title, ai_fix_text, error_id, metadata={}):
    """
    Sends an AI-generated fix message to Slack.
    Also ensures the fix is cached under fix:<error_id>, error_map:<error_text>,
    and maps the Slack thread to this error_id.
    """
    try:
        # Build blocks first
        # --- AI summarize long error logs ---
        if len(error_title) > 300 or "\n" in error_title:
            error_summary = summarize_error_with_ai(error_title)
        else:
            error_summary = f"{error_title}"

        summary_block = {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*❌ Error Summary (ID: `{error_id}`)*\n{error_summary}"
            }
        }

        # Build fix blocks
        fix_blocks = ai_fix_to_blocks(error_summary, ai_fix_text, error_id, metadata)

        # Insert summary above fix
        blocks = [summary_block] + fix_blocks
        payload_size = len(json.dumps(blocks))
        print(f"📦 Payload size for '{error_summary}': {payload_size} bytes, {len(blocks)} blocks")

        resp = client.chat_postMessage(channel=channel, text=f"AI fix for error: {error_summary}", blocks=blocks)

        # Capture Slack message ts & channel, then persist alongside fix
        message_ts = resp.get("ts")
        channel_id = resp.get("channel")

        store_fix(
            error_id=error_id,
            error_title=error_title,
            ai_fix_text=ai_fix_text,
            source="ai",
            approver=None,
            message_ts=message_ts,
            channel_id=channel_id,
            triggered_by=metadata.get("triggered_by")
        )

    except SlackApiError as e:
        error_msg = e.response.get("error", "unknown_error")
        print(f"⚠️ Slack API error for '{error_title}': {error_msg}")
        try:
            client.chat_postMessage(channel=channel, text=f"⚠️ Fallback summary for '{error_title}': {ai_fix_text[:1000]}")
        except Exception as inner_e:
            print(f"❌ Failed fallback message: {inner_e}")
    except Exception as e:
        print(f"❌ Unexpected error while sending message for '{error_title}': {e}")
