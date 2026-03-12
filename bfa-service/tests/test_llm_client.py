import pytest
from unittest.mock import MagicMock

from llm_openwebui_client import call_llm, analyze_with_llm


# ------------------------------------------------------------------
# call_llm()
# ------------------------------------------------------------------

def test_call_llm_success(mocker):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "choices": [
            {"message": {"content": "LLM response text"}}
        ]
    }

    mocker.patch(
        "llm_openwebui_client.requests.post",
        return_value=mock_resp
    )

    result = call_llm(prompt="Fix the error")

    assert result == "LLM response text"


def test_call_llm_empty_response_raises(mocker):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "choices": [
            {"message": {"content": ""}}
        ]
    }

    mocker.patch(
        "llm_openwebui_client.requests.post",
        return_value=mock_resp
    )

    with pytest.raises(RuntimeError):
        call_llm(prompt="Test")


def test_call_llm_http_exception_raises(mocker):
    mocker.patch(
        "llm_openwebui_client.requests.post",
        side_effect=Exception("LLM down")
    )

    with pytest.raises(RuntimeError):
        call_llm(prompt="Test")


# ------------------------------------------------------------------
# analyze_with_llm()
# ------------------------------------------------------------------

def test_analyze_with_llm_valid_json(mocker):
    mocker.patch(
        "llm_openwebui_client.call_llm",
        return_value="""
        {
            "quality_score": 8,
            "security_score": 9,
            "maintainability_score": 7,
            "overall_summary": "Looks good",
            "potential_vulnerabilities": [],
            "recommended_improvements": []
        }
        """
    )

    result = analyze_with_llm("analyze this code")

    assert result["quality_score"] == 8
    assert result["security_score"] == 9
    assert result["maintainability_score"] == 7
    assert "overall_summary" in result


def test_analyze_with_llm_malformed_json_fallback(mocker):
    mocker.patch(
        "llm_openwebui_client.call_llm",
        return_value="this is not json"
    )

    result = analyze_with_llm("bad output")

    assert isinstance(result, dict)
    assert "summary_text" in result


def test_analyze_with_llm_empty_response(mocker):
    mocker.patch(
        "llm_openwebui_client.call_llm",
        return_value=""
    )

    result = analyze_with_llm("")

    assert result == {"summary_text": ""}


def test_analyze_with_llm_propagates_exception(mocker):
    mocker.patch(
        "llm_openwebui_client.call_llm",
        side_effect=Exception("OpenWebUI timeout")
    )

    with pytest.raises(RuntimeError):
        analyze_with_llm("trigger")


# ------------------------------------------------------------------
# Prompt integrity
# ------------------------------------------------------------------

def test_analyze_with_llm_prompt_passed_correctly(mocker):
    spy = mocker.patch(
        "llm_openwebui_client.call_llm",
        return_value="{}"
    )

    analyze_with_llm("hello world")

    _, kwargs = spy.call_args
    assert "hello world" in kwargs["prompt"]
