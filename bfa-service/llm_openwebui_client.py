#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

import os
import json
import logging
import time
from typing import Optional
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llm_openwebui_client")

OPENWEBUI_BASE_URL = os.getenv(
    "OPENWEBUI_BASE_URL", "https://chat-internal.com").rstrip("/")
OPENWEBUI_API_KEY = os.getenv("OPENWEBUI_API_KEY")
OPENWEBUI_MODEL = os.getenv(
    "OPENWEBUI_MODEL", "anthropic.claude-sonnet-4-20250514-v1:0")
OPENWEBUI_TIMEOUT = int(os.getenv("OPENWEBUI_TIMEOUT", "60"))
OPENWEBUI_RETRIES = int(os.getenv("OPENWEBUI_RETRIES", "2"))
OPENWEBUI_BACKOFF = float(os.getenv("OPENWEBUI_BACKOFF", "0.5"))

if not OPENWEBUI_API_KEY:
    logger.warning(
        "OPENWEBUI_API_KEY not set — requests will likely be rejected by OpenWebUI if auth is required.")


class LLMInfraError(RuntimeError):
    """Raised when LLM infrastructure is unavailable (DNS, network, auth, etc)."""
    pass


def _build_headers():
    headers = {"Content-Type": "application/json"}
    if OPENWEBUI_API_KEY:
        headers["Authorization"] = f"Bearer {OPENWEBUI_API_KEY}"
    return headers


def _build_payload(prompt: str, system_prompt: Optional[str], temperature: float, max_tokens: int, model: Optional[str] = None):
    model_to_use = model or OPENWEBUI_MODEL
    # Bedrock-friendly: merge system prompt into user content to avoid 'system' role issues
    merged = (system_prompt.strip() +
              "\n\n" if system_prompt else "") + prompt.strip()
    payload = {
        "model": model_to_use,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": merged}]
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    return payload


def _extract_text_from_choice(choice):
    """
    Handles multiple possible OpenWebUI/Bedrock shapes:
    - choice["message"]["content"] may be a string
    - or a list of {type,text} blocks
    - or choice.get("text")
    - or older shapes
    Safely extract text from all known OpenWebUI / Bedrock response shapes.
    MUST NEVER throw.
    """
    try:
        # Case 1: choice itself is a string
        if isinstance(choice, str):
            return choice.strip()

        if not isinstance(choice, dict):
            return None

        msg = choice.get("message")

        # Case 2: message is a string
        if isinstance(msg, str):
            return msg.strip()

        # Case 3: message is a dict
        if isinstance(msg, dict):
            content = msg.get("content")

            # content is string
            if isinstance(content, str):
                return content.strip()

            # content is list of blocks
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("text"):
                        parts.append(block["text"])
                    elif isinstance(block, str):
                        parts.append(block)
                if parts:
                    return "\n".join(parts).strip()

            # legacy nested dict
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                return content["text"].strip()

        # Case 4: direct text fields
        for key in ("text", "result", "output"):
            val = choice.get(key)
            if isinstance(val, str):
                return val.strip()

    except Exception:
        # Absolute safety — never let parsing crash LLM call
        logger.exception("[LLM] Failed to extract text from choice")

    return None


def call_llm(prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.2, max_tokens: int = 512, model: Optional[str] = None) -> str:
    """
    Call OpenWebUI /api/v1/chat/completions and return assistant text.
    Raises RuntimeError on failure.
    """
    url = f"{OPENWEBUI_BASE_URL}/api/v1/chat/completions"
    payload = _build_payload(prompt, system_prompt,
                             temperature, max_tokens, model)
    headers = _build_headers()

    attempt = 0
    last_exception = None
    while attempt <= OPENWEBUI_RETRIES:
        attempt += 1
        try:
            logger.info("[LLM] POST %s model=%s prompt_len=%d attempt=%d",
                        url, payload.get("model"), len(prompt), attempt)
            resp = requests.post(url, headers=headers,
                                 json=payload, timeout=OPENWEBUI_TIMEOUT)
            # Raise for status will raise HTTPError for 4xx/5xx
            resp.raise_for_status()
            data = resp.json()
            # token usage diagnostics if present
            if isinstance(data, dict) and "usage" in data:
                logger.debug("[LLM] usage: %s", data.get("usage"))

            # extract choices
            if isinstance(data, dict) and "choices" in data:
                choices = data.get("choices") or []
                if len(choices) == 0:
                    raise RuntimeError(f"No choices returned by model: {data}")
                text = _extract_text_from_choice(choices[0])
                if text:
                    return text.strip()
                # try other choices if first fails
                for c in choices[1:]:
                    txt = _extract_text_from_choice(c)
                    if txt:
                        return txt.strip()
                # no usable text found
                raise RuntimeError(
                    f"Could not extract assistant text from choices: {choices}")

            # other shapes
            if isinstance(data, dict) and "message" in data:
                text = _extract_text_from_choice(data)
                if text:
                    return text.strip()

            raise RuntimeError(
                f"Unexpected response structure from OpenWebUI: {json.dumps(data)[:1000]}")

        except requests.exceptions.HTTPError as e:
            body = getattr(e.response, "text", "")[
                :1000] if getattr(e, "response", None) else ""
            logger.warning(
                "[LLM] HTTPError attempt %d: %s body=%s", attempt, e, body)
            last_exception = e
            # If 400 and attempt==1, don't retry (likely bad payload/model); otherwise backoff and retry
            status = getattr(e.response, "status_code", None)
            if status and 400 <= status < 500 and attempt > 1:
                break
            if attempt <= OPENWEBUI_RETRIES:
                time.sleep(OPENWEBUI_BACKOFF * attempt)
                continue
            break
        except Exception as e:
            logger.exception(
                "[LLM] Exception calling model (attempt %d)", attempt)
            last_exception = e
            if attempt <= OPENWEBUI_RETRIES:
                time.sleep(OPENWEBUI_BACKOFF * attempt)
                continue
            break

    error_msg = str(last_exception)

    # Infra-level failures must propagate
    infra_signals = [
        "NameResolutionError",
        "Max retries exceeded",
        "ConnectionError",
        "Failed to resolve",
        "timed out",
        "401",
        "403",
    ]

    if any(sig in error_msg for sig in infra_signals):
        raise LLMInfraError(
            f"LLM infrastructure failure after {attempt} attempts: {error_msg}"
        )

    # Content-level failure (recoverable)
    raise RuntimeError(
        f"LLM returned unusable content after {attempt} attempts: {error_msg}"
    )


def analyze_with_llm(prompt: str, system_prompt: Optional[str] = None) -> dict:
    """
    Wrapper around call_llm() that ensures the LLM returns a structured JSON response.
    Used by /api/rate-my-mr API as well to get metrics on code quality, security,
    and maintainability.
    """
    try:
        raw_output = call_llm(
            prompt=prompt,
            system_prompt=system_prompt or "You are an expert software quality and security reviewer.",
            temperature=0.2,
            max_tokens=1024,
        )
        if not isinstance(raw_output, str):
            logger.error(
                "LLM_INVALID_RESPONSE",
                extra={"reason": "non_string",
                       "type": type(raw_output).__name__}
            )
            return {"summary_text": "Invalid LLM response format"}

        if not raw_output.strip():
            logger.warning("LLM_EMPTY_RESPONSE")
            return {"summary_text": "LLM returned empty response"}

        # Try to extract JSON from text
        try:
            start = raw_output.find("{")
            end = raw_output.rfind("}") + 1
            if start != -1 and end != -1:
                parsed = json.loads(raw_output[start:end])
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass

        # Fallback: plain text summary
        return {
            "summary_text": raw_output.strip()
        }

    except LLMInfraError as e:
        # DO NOT swallow infra failures
        logger.exception("[LLM] analyze_with_llm() Infra failure: %s", e)
        raise

    except Exception as e:
        logger.exception("[LLM] analyze_with_llm() content failure: %s", e)
        return {
            "summary_text": "AI summary could not be generated due to malformed or incomplete LLM output."
        }


# quick test when run as script
if __name__ == "__main__":
    test = call_llm(
        "Explain this error: SyntaxError: missing semicolon",
        system_prompt="You are a build failure analyzer that explains compiler errors clearly."
    )
    print("=== MODEL OUTPUT ===")
    print(test)
