#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

#!/usr/bin/env python3

import os
import json
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

from vector_db import init_vector_db, save_fix_to_db
from slack_helper import redis_conn, get_fix, store_fix

load_dotenv()

FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5001"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

app = Flask(__name__)
client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
db = init_vector_db()  # initialize once


def parse_slack_payload(req):
    ctype = req.headers.get("Content-Type", "")
    if "application/json" in ctype:
        return req.get_json()
    return json.loads(req.form["payload"])


# Helper: Get Slack display name
def get_user_display_name(user_id):
    try:
        resp = client.users_info(user=user_id)
        user = resp.get("user", {})
        return user.get("real_name") or user.get("name") or user_id
    except Exception as e:
        print(f"Error fetching Slack username for {user_id}: {e}")
        return user_id


@app.route("/bfa/slack/events", methods=["POST"])
def slack_events():
    try:
        data = request.get_json(force=True, silent=True) or {}
        # Slack verification challenge
        if data.get("type") == "url_verification":
            return jsonify({"challenge": data.get("challenge")}), 200

        # Handle thread replies as edited fixes (NO 'EDIT:' prefix required)
        event = data.get("event", {})
        if event.get("type") == "message" and not event.get("bot_id"):
            channel_id = event.get("channel")
            user_id = event.get("user")
            thread_ts = event.get("thread_ts")
            text = (event.get("text") or "").strip()

            # 1) Check if this user is in EDIT mode
            pattern = f"last_edit:{channel_id}:*"
            keys = redis_conn.keys(pattern)
            error_id = None
            for key in keys:
                if redis_conn.get(key) == user_id:
                    error_id = key.split(":")[-1]  # extract the error_id
                    break

            if not error_id:
                # User is NOT in edit mode → ignore silently
                return jsonify({"status": "ignored"}), 200

            # 2) User IS in edit mode → must reply in thread
            if not thread_ts:
                client.chat_postMessage(
                    channel=channel_id,
                    text="Please reply *in the thread* of the original fix message to submit your edit.",
                    thread_ts=event.get("ts")
                )
                return jsonify({"status": "must_reply_in_thread"}), 200

            # 3) Validate that this thread_ts belongs to correct error_id
            mapped_error_id = redis_conn.get(f"thread_map:{channel_id}:{thread_ts}")
            if not mapped_error_id or mapped_error_id != error_id:
                return jsonify({"status": "wrong_thread"}), 200

            # 4) Retrieve original error context
            stored = get_fix(error_id)
            error_text = stored.get("error", "")
            if not error_text:
                client.chat_postMessage(
                    channel=channel_id,
                    text="Could not find the original error context.",
                    thread_ts=thread_ts
                )
                return jsonify({"status": "missing_error"}), 200

            new_fix_text = text  # full message body is the edited fix

            # 5) Save edited fix to Vector DB & Redis with display name
            display_name = get_user_display_name(user_id)
            try:
                save_fix_to_db(
                    db, error_text, new_fix_text,
                    approver=display_name, status="edited"
                )
                message_ts = stored.get("message_ts")
                store_fix(
                    error_id, error_text, new_fix_text,
                    source="edited", approver=display_name,
                    message_ts=message_ts, channel_id=channel_id
                )
                print(f"[DEBUG] Saved edited fix for {error_text[:50]}... by {display_name}")
                client.chat_postMessage(channel=channel_id, text="Your edited fix has been saved.", thread_ts=thread_ts)
            except Exception as e:
                print("Error saving edited fix:", e)
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"Failed to save your edited fix: {e}",
                    thread_ts=thread_ts
                )

            # 6) Cleanup edit intent
            redis_conn.delete(f"last_edit:{channel_id}:{error_id}")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("Error in slack_events:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/bfa/slack/actions", methods=["POST"])
def slack_actions():
    try:
        payload = parse_slack_payload(request)
        action = payload["actions"][0]
        user_obj = payload.get("user", {})
        user_id = user_obj.get("id")

        # Use display name instead of user ID
        approver = get_user_display_name(user_id)
        print(f"Slack Approver name: {approver}")
        action_id = action.get("action_id", "")
        action_name, error_id = action_id.split("_", 1)

        channel_id = payload.get("channel", {}).get("id")

        # retrieve the stored fix from Redis (by error_id)
        stored = get_fix(error_id)
        error_text = stored.get("error", "")
        fix_text = stored.get("fix", "")
        if not error_text:
            client.chat_postMessage(
                channel=channel_id,
                text="Original error text not found. Cannot process this action."
            )
            return jsonify({"status": "missing_error"}), 200

        if action_name == "approve":
            # Save to Vector DB with display name
            save_fix_to_db(db, error_text, fix_text, approver=approver, status="approved")
            # Sync Redis cache with display name
            message_ts = stored.get("message_ts")
            store_fix(
                error_id, error_text, fix_text,
                source="approved",
                approver=approver,
                message_ts=message_ts,
                channel_id=channel_id
            )

        elif action_name == "edit":
            # 1) Store edit intent
            last_edit_key = f"last_edit:{channel_id}:{error_id}"
            redis_conn.set(last_edit_key, user_id)

            # 2) Find original message ts
            original_ts = stored.get("message_ts") or payload.get("message", {}).get("ts")

            # 3) Prompt in thread (opens thread UI automatically)
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=original_ts,
                text=f"<@{user_id}> please enter the updated fix here."
            )

        elif action_name == "discard":
            redis_conn.delete(f"fix:{error_id}")

        else:
            pass  # Unknown action

        # Disable buttons on original message
        try:
            original_ts = payload.get("message", {}).get("ts")
            old_blocks = payload.get("message", {}).get("blocks", [])
            new_blocks = [b for b in old_blocks if not b.get("block_id", "").startswith("actions_")]

            new_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Reviewed by <@{user_id}> — *{action_name.upper()}ED*"}]
            })

            client.chat_update(
                channel=channel_id,
                ts=original_ts,
                text=f"Fix {action_name}d by {approver}",
                blocks=new_blocks
            )

        except SlackApiError as e:
            print("Slack post error:", e.response.get("error"))

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("Error processing Slack action:", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
