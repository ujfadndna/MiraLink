from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import settings
from app.schemas import WebSearchRequest
from app.services.web_search import OpenAIWebSearchBackend, WebSearchError, get_web_search


def run(coro):
    return asyncio.run(coro)


def test_mock_backend_returns_stable_structure(monkeypatch):
    monkeypatch.setattr(settings, "web_search_context_size", "low")

    result = run(get_web_search("mock").search(WebSearchRequest(query="今天有什么AI新闻")))

    assert result.query == "今天有什么AI新闻"
    assert result.provider == "mock"
    assert result.model == "mock"
    assert result.answer
    assert result.sources[0].url == "https://example.com/MIRALINK-web-search"
    assert result.searched_at
    assert result.elapsed_ms >= 0


def test_openai_backend_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(WebSearchError, match="OPENAI_API_KEY is not set"):
        run(OpenAIWebSearchBackend().search(WebSearchRequest(query="news")))


def test_empty_query_is_rejected():
    with pytest.raises(WebSearchError, match="query must not be empty"):
        run(get_web_search("mock").search(WebSearchRequest(query="   ")))


def test_invalid_context_size_is_rejected():
    with pytest.raises(WebSearchError, match="context_size must be low, medium, or high"):
        run(get_web_search("mock").search(WebSearchRequest(query="news", context_size="huge")))


def test_openai_success_response_is_normalized(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-secret")
    monkeypatch.setattr(settings, "web_search_model", "gpt-test")
    monkeypatch.setattr(settings, "web_search_context_size", "low")
    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return {
                "output_text": "这是联网搜索答案。",
                "output": [
                    {
                        "type": "web_search_call",
                        "action": {
                            "sources": [
                                {
                                    "type": "web_search_result",
                                    "title": "Source A",
                                    "url": "https://example.com/a",
                                    "snippet": "A snippet",
                                },
                                {
                                    "type": "web_search_result",
                                    "title": "Duplicate",
                                    "url": "https://example.com/a",
                                    "snippet": "Ignored",
                                },
                            ]
                        },
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "这是联网搜索答案。",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "title": "Source B",
                                        "url": "https://example.com/b",
                                        "snippet": "B snippet",
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }

    class FakeClient:
        responses = FakeResponses()

    result = run(
        OpenAIWebSearchBackend(client=FakeClient()).search(
            WebSearchRequest(query="OpenAI web search", max_sources=2, language="zh")
        )
    )

    assert captured["model"] == "gpt-test"
    assert captured["tool_choice"] == "required"
    assert captured["include"] == ["web_search_call.action.sources"]
    assert captured["tools"] == [
        {"type": "web_search", "search_context_size": "low", "external_web_access": True}
    ]
    assert result.answer == "这是联网搜索答案。"
    assert [source.url for source in result.sources] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert result.provider == "openai"
    assert result.model == "gpt-test"
    assert result.searched_at
    assert result.elapsed_ms >= 0


def test_openai_string_response_is_used_as_answer(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-secret")
    monkeypatch.setattr(settings, "web_search_model", "gpt-test")

    class FakeResponses:
        def create(self, **_kwargs):
            return "兼容端点返回的文本答案"

    class FakeClient:
        responses = FakeResponses()

    result = run(
        OpenAIWebSearchBackend(client=FakeClient()).search(
            WebSearchRequest(query="OpenAI web search", max_sources=2)
        )
    )

    assert result.answer == "兼容端点返回的文本答案"
    assert result.sources == []


def test_openai_timeout_error_is_safe(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-secret")
    monkeypatch.setattr(settings, "web_search_timeout_sec", 0.01)

    class FakeResponses:
        def create(self, **_kwargs):
            import time

            time.sleep(1)

    class FakeClient:
        responses = FakeResponses()

    with pytest.raises(WebSearchError) as exc_info:
        run(OpenAIWebSearchBackend(client=FakeClient()).search(WebSearchRequest(query="news")))

    message = str(exc_info.value)
    assert message == "OpenAI web search timed out after 0.01s"
    assert "test-secret" not in message


def test_openai_api_error_is_safe(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-secret")
    monkeypatch.setattr(settings, "web_search_timeout_sec", 1.0)

    class FakeOpenAIError(Exception):
        status_code = 401
        type = "invalid_request_error"
        message = "bad request with test-secret"

    class FakeResponses:
        def create(self, **_kwargs):
            raise FakeOpenAIError()

    class FakeClient:
        responses = FakeResponses()

    with pytest.raises(WebSearchError) as exc_info:
        run(OpenAIWebSearchBackend(client=FakeClient()).search(WebSearchRequest(query="news")))

    message = str(exc_info.value)
    assert "status=401" in message
    assert "invalid_request_error" in message
    assert "test-secret" not in message


def test_cli_mock_json_is_valid():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "openai_web_search.py"),
            "--backend",
            "mock",
            "--query",
            "今天有什么AI新闻",
            "--format",
            "json",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["provider"] == "mock"
    assert payload["query"] == "今天有什么AI新闻"


def test_cli_openai_missing_key_is_readable(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "openai_web_search.py"),
            "--backend",
            "openai",
            "--query",
            "news",
            "--format",
            "json",
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout) == {
        "ok": False,
        "error": "OPENAI_API_KEY is not set",
    }
