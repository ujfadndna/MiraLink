"""OpenAI hosted web search service."""
from __future__ import annotations

import asyncio
import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.schemas import WebSearchRequest, WebSearchResult, WebSearchSource
from app.services.base import get_backend, register


VALID_CONTEXT_SIZES = {"low", "medium", "high"}
MAX_ERROR_CHARS = 500
_SINGLETONS: dict[str, "WebSearchBackend"] = {}


class WebSearchError(Exception):
    """User-facing search error that omits secrets and raw provider payloads."""


class WebSearchBackend(ABC):
    @abstractmethod
    async def search(self, request: WebSearchRequest) -> WebSearchResult:
        raise NotImplementedError


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_request(request: WebSearchRequest, default_context_size: str) -> str:
    request.query = request.query.strip()
    if not request.query:
        raise WebSearchError("query must not be empty")
    if request.max_sources < 0:
        raise WebSearchError("max_sources must be >= 0")

    context_size = request.context_size or default_context_size
    if context_size not in VALID_CONTEXT_SIZES:
        raise WebSearchError("context_size must be low, medium, or high")
    return context_size


def _safe_message(value: object) -> str:
    compact = " ".join(str(value or "").split())
    for secret in (
        settings.openai_api_key,
        os.getenv("OPENAI_API_KEY", ""),
    ):
        if secret:
            compact = compact.replace(secret, "[redacted]")
    if len(compact) > MAX_ERROR_CHARS:
        return f"{compact[:MAX_ERROR_CHARS]}..."
    return compact


def _read_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _coerce_response(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return json.loads(text)
        except ValueError:
            return value
    return value


def _iter_children(value: Any) -> list[Any]:
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return []
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, (list, tuple, set)):
        return list(value)
    children: list[Any] = []
    for name in ("output", "content", "annotations", "action", "sources", "results"):
        child = getattr(value, name, None)
        if child is not None:
            children.append(child)
    return children


def _extract_answer(response: Any) -> str:
    response = _coerce_response(response)
    if isinstance(response, str):
        return response.strip()

    output_text = _read_attr(response, "output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks: list[str] = []

    def visit(node: Any) -> None:
        node_type = _read_attr(node, "type", "")
        text = _read_attr(node, "text")
        if isinstance(text, str) and text.strip() and node_type in {"", "output_text", "text"}:
            chunks.append(text.strip())
        for child in _iter_children(node):
            visit(child)

    visit(response)
    return "\n".join(dict.fromkeys(chunks)).strip()


def _source_from_value(value: Any) -> WebSearchSource | None:
    url = _read_attr(value, "url") or _read_attr(value, "uri")
    if not isinstance(url, str) or not url.strip():
        return None

    title = _read_attr(value, "title") or _read_attr(value, "name") or ""
    snippet = (
        _read_attr(value, "snippet")
        or _read_attr(value, "content")
        or _read_attr(value, "text")
        or ""
    )
    return WebSearchSource(
        title=str(title).strip(),
        url=url.strip(),
        snippet=str(snippet).strip(),
    )


def _extract_sources(response: Any, max_sources: int) -> list[WebSearchSource]:
    if max_sources <= 0:
        return []
    response = _coerce_response(response)

    sources: list[WebSearchSource] = []
    seen: set[str] = set()

    def add(source: WebSearchSource | None) -> None:
        if source is None or source.url in seen:
            return
        seen.add(source.url)
        sources.append(source)

    def visit(node: Any) -> None:
        if len(sources) >= max_sources:
            return
        node_type = _read_attr(node, "type", "")
        if node_type in {"url_citation", "citation", "web_search_result"}:
            add(_source_from_value(node))
        elif _read_attr(node, "url"):
            add(_source_from_value(node))
        for child in _iter_children(node):
            visit(child)

    visit(response)
    return sources[:max_sources]


@register("web_search", "mock")
class MockWebSearchBackend(WebSearchBackend):
    async def search(self, request: WebSearchRequest) -> WebSearchResult:
        _validate_request(request, settings.web_search_context_size)
        started = time.perf_counter()
        searched_at = _utc_now_iso()
        await asyncio.sleep(0)
        return WebSearchResult(
            query=request.query,
            answer=f"[mock] {request.language} search result for: {request.query}",
            sources=[
                WebSearchSource(
                    title="Mock source",
                    url="https://example.com/herunity-web-search",
                    snippet="Deterministic mock source for local tests and CI.",
                )
            ][: request.max_sources],
            searched_at=searched_at,
            elapsed_ms=round((time.perf_counter() - started) * 1000.0, 3),
            provider="mock",
            model="mock",
        )


@register("web_search", "openai")
class OpenAIWebSearchBackend(WebSearchBackend):
    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    async def search(self, request: WebSearchRequest) -> WebSearchResult:
        context_size = _validate_request(request, settings.web_search_context_size)
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise WebSearchError("OPENAI_API_KEY is not set")

        started = time.perf_counter()
        searched_at = _utc_now_iso()
        timeout_sec = settings.web_search_timeout_sec

        def run_request() -> Any:
            client = self._client or self._make_client(api_key, timeout_sec)
            prompt = (
                f"请用 {request.language} 回答，并基于联网搜索结果给出简洁答案。\n"
                f"查询：{request.query}"
            )
            return client.responses.create(
                model=settings.web_search_model,
                input=prompt,
                tools=[
                    {
                        "type": "web_search",
                        "search_context_size": context_size,
                        "external_web_access": settings.web_search_external_web_access,
                    }
                ],
                tool_choice="required",
                include=["web_search_call.action.sources"],
            )

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(run_request),
                timeout=timeout_sec,
            )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise WebSearchError(f"OpenAI web search timed out after {timeout_sec:g}s") from exc
        except Exception as exc:
            self._raise_safe_openai_error(exc)

        return WebSearchResult(
            query=request.query,
            answer=_extract_answer(response),
            sources=_extract_sources(response, request.max_sources),
            searched_at=searched_at,
            elapsed_ms=round((time.perf_counter() - started) * 1000.0, 3),
            provider="openai",
            model=settings.web_search_model,
        )

    @staticmethod
    def _make_client(api_key: str, timeout_sec: float) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise WebSearchError("openai package is not installed") from exc

        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout_sec}
        base_url = settings.openai_base_url or os.getenv("OPENAI_BASE_URL", "")
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)

    @staticmethod
    def _raise_safe_openai_error(exc: Exception) -> None:
        name = exc.__class__.__name__
        if name in {"APITimeoutError", "Timeout"}:
            raise WebSearchError(
                f"OpenAI web search timed out after {settings.web_search_timeout_sec:g}s"
            ) from exc

        status = getattr(exc, "status_code", None)
        error_type = getattr(exc, "type", "") or getattr(exc, "code", "")
        message = _safe_message(getattr(exc, "message", "") or exc)
        if status:
            summary = f"OpenAI API error status={status}"
            if error_type:
                summary += f" type={error_type}"
            if message:
                summary += f": {message}"
            raise WebSearchError(summary) from exc
        raise WebSearchError(f"OpenAI API error {name}: {message}") from exc


def get_web_search(backend: str | None = None) -> WebSearchBackend:
    selected = backend or settings.web_search_backend
    if selected not in _SINGLETONS:
        backend_cls = get_backend("web_search", selected)
        _SINGLETONS[selected] = backend_cls()
    return _SINGLETONS[selected]
