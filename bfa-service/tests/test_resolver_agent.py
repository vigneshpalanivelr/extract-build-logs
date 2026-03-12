import json
import pytest
from unittest.mock import MagicMock

from resolver_agent import ResolverAgent


@pytest.fixture
def redis_mock():
    return MagicMock()


@pytest.fixture
def resolver(redis_mock, mocker):
    # Prevent real VectorDB initialization
    mocker.patch("resolver_agent.VectorDBClient")
    return ResolverAgent(redis_client=redis_mock)


def test_resolver_returns_ai_cache_hit(resolver, redis_mock):
    cached_payload = {
        "fix_text": "Cached AI fix",
        "confidence": 0.9,
        "source": "generated",
    }

    redis_mock.get.return_value = json.dumps(cached_payload)

    result = resolver.resolve(
        ["mvn test failed"],
        metadata={}
    )

    assert result["source"] == "ai_cache"
    assert result["fix_text"] == "Cached AI fix"


def test_resolver_returns_vector_db_fix(resolver, mocker):
    mocker.patch.object(
        resolver.vector,
        "lookup_existing_fix",
        return_value={
            "fix_text": "Known SME fix",
            "confidence": 0.92,
            "source": "vector_db",
            "metadata": {"status": "approved"},
        }
    )

    result = resolver.resolve(
        ["npm install failed"],
        metadata={}
    )

    assert result["source"] == "vector_db"
    assert "Known SME fix" in result["fix_text"]


def test_resolver_generates_ai_fix_when_no_cache_or_vector_hit(resolver, redis_mock, mocker):
    redis_mock.get.return_value = None

    mocker.patch.object(
        resolver.vector,
        "lookup_existing_fix",
        return_value=None
    )

    mocker.patch(
        "resolver_agent.call_llm",
        return_value="Install missing dependency"
    )

    result = resolver.resolve(
        ["clang error: missing header"],
        metadata={"repo": "repo1"}
    )

    assert result["source"] == "generated"
    assert "Install missing dependency" in result["fix_text"]
    redis_mock.setex.assert_called_once()


def test_resolver_handles_empty_error_lines(resolver, mocker):
    mocker.patch.object(
        resolver.vector,
        "lookup_existing_fix",
        return_value=None
    )

    mocker.patch(
        "resolver_agent.call_llm",
        return_value="No error provided"
    )

    result = resolver.resolve([], metadata={})

    assert isinstance(result, dict)
    assert result["source"] == "generated"


def test_resolver_respects_vector_top_k(resolver, mocker):
    spy = mocker.patch.object(
        resolver.vector,
        "lookup_existing_fix",
        return_value=None
    )

    resolver.resolve(
        ["some error"],
        metadata={"vector_top_k": 3}
    )

    spy.assert_called_once()
    _, kwargs = spy.call_args
    assert kwargs["top_k"] == 3


def test_resolver_passes_domain_rag_metadata(resolver, redis_mock, mocker):
    redis_mock.get.return_value = None

    mocker.patch.object(
        resolver.vector,
        "lookup_existing_fix",
        return_value=None
    )

    llm_spy = mocker.patch(
        "resolver_agent.call_llm",
        return_value="Use domain fix"
    )

    resolver.resolve(
        ["timeout connecting to nexus"],
        metadata={
            "domain_rag_snippet": "Nexus outages require mirror switch"
        }
    )

    llm_spy.assert_called_once()
