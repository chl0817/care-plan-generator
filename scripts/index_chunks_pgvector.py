#!/usr/bin/env python3
"""Embed DailyMed JSONL chunks and upsert them into PostgreSQL/pgvector."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careplans.rag.pgvector_store import PgVectorStore

load_dotenv()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--batch-size", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("set DATABASE_URL or pass --database-url")

    store = PgVectorStore(args.database_url, embedding_model=args.model)
    count = store.index_jsonl(args.jsonl, batch_size=args.batch_size)
    print(f"Upserted {count} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
