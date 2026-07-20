#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> int:
    arguments = sys.argv[1:]
    if arguments in (["--version"], ["version"]):
        print("wikimap 1.1.0-fake")
        return 0
    if not arguments:
        return 2
    command = arguments[0]
    if command == "update":
        print("wikimap: fake index updated")
        return 0
    if command == "doctor":
        if "--json" in arguments:
            print(json.dumps({"healthy": True, "index": {"pending": 0}}))
        else:
            print("wikimap: ok")
        return 0
    if command == "search":
        query = arguments[1] if len(arguments) > 1 else ""
        limit = 8
        if "-n" in arguments:
            try:
                limit = int(arguments[arguments.index("-n") + 1])
            except (IndexError, ValueError):
                return 2
        terms = {
            value.casefold()
            for value in re.findall(r"[\w가-힣]{2,}", query, re.UNICODE)
        }
        results = []
        for path in Path.cwd().rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            folded = text.casefold()
            score = sum(folded.count(term) for term in terms)
            if score:
                results.append(
                    {
                        "path": str(path.relative_to(Path.cwd())),
                        "line": 1,
                        "title": path.stem,
                        "snippet": next(
                            (
                                line
                                for line in text.splitlines()
                                if any(term in line.casefold() for term in terms)
                            ),
                            text[:200],
                        ),
                        "score": score,
                    }
                )
        results.sort(key=lambda item: -item["score"])
        print(json.dumps({"results": results[:limit]}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
