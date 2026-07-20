#!/usr/bin/env python3
"""Search the indexed DailyMed chunks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careplans.rag.pgvector_store import PgVectorStore

load_dotenv()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--set-id", help="Optional exact DailyMed set_id filter")
    parser.add_argument("--section-code", help="Optional exact SPL section code filter")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("set DATABASE_URL or pass --database-url")

    metadata_filter = {
        key: value
        for key, value in {
            "set_id": args.set_id,
            "section_code": args.section_code,
        }.items()
        if value is not None
    }
    results = PgVectorStore(args.database_url).search(
        args.query,
        top_k=args.top_k,
        metadata_filter=metadata_filter,
    )
    print(
        json.dumps(
            [
                {
                    "id": result.id,
                    "score": result.score,
                    "text": result.text,
                    "metadata": result.metadata,
                }
                for result in results
            ],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
