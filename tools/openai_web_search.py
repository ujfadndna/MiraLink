from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas import WebSearchRequest
from app.services.web_search import WebSearchError, get_web_search


def format_text(payload: dict[str, object]) -> str:
    lines = [
        f"Query: {payload['query']}",
        f"Provider: {payload['provider']}",
        f"Model: {payload['model']}",
        f"Searched at: {payload['searched_at']}",
        f"Elapsed: {payload['elapsed_ms']} ms",
        "",
        "Answer:",
        str(payload["answer"]),
    ]
    sources = payload.get("sources") or []
    if sources:
        lines.extend(["", "Sources:"])
        for index, item in enumerate(sources, start=1):
            if not isinstance(item, dict):
                continue
            title = item.get("title") or "(untitled)"
            url = item.get("url") or "(no url)"
            snippet = item.get("snippet") or ""
            lines.append(f"{index}. {title}")
            lines.append(f"   {url}")
            if snippet:
                lines.append(f"   {snippet}")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenAI hosted web search debug CLI")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--max-sources", type=int, default=5)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--backend", choices=("mock", "openai"), default=None)
    return parser


async def run(args: argparse.Namespace) -> dict[str, object]:
    result = await get_web_search(args.backend).search(
        WebSearchRequest(query=args.query, max_sources=args.max_sources)
    )
    return result.model_dump(mode="json")


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        payload = asyncio.run(run(args))
    except WebSearchError as exc:
        if args.format == "json":
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
