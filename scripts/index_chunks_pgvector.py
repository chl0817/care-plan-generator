#!/usr/bin/env python3
"""Embed DailyMed JSONL chunks and upsert them into PostgreSQL/pgvector."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from openai import OpenAI
from psycopg.types.json import Jsonb


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS drug_label_chunks (
    id text PRIMARY KEY,
    set_id text NOT NULL,
    spl_version text NOT NULL,
    section_code text NOT NULL,
    content text NOT NULL,
    metadata jsonb NOT NULL,
    embedding vector(1536) NOT NULL,
    is_current boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE drug_label_chunks
    ADD COLUMN IF NOT EXISTS is_current boolean NOT NULL DEFAULT true;
CREATE INDEX IF NOT EXISTS drug_label_chunks_set_id_idx
    ON drug_label_chunks (set_id);
CREATE INDEX IF NOT EXISTS drug_label_chunks_embedding_hnsw_idx
    ON drug_label_chunks USING hnsw (embedding vector_cosine_ops);
"""

UPSERT_SQL = """
INSERT INTO drug_label_chunks
    (id, set_id, spl_version, section_code, content, metadata, embedding, is_current)
VALUES (%s, %s, %s, %s, %s, %s, %s::vector, false)
ON CONFLICT (id) DO UPDATE SET
    set_id = EXCLUDED.set_id,
    spl_version = EXCLUDED.spl_version,
    section_code = EXCLUDED.section_code,
    content = EXCLUDED.content,
    metadata = EXCLUDED.metadata,
    embedding = EXCLUDED.embedding,
    updated_at = now();
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--batch-size", type=int, default=100)
    return parser.parse_args()


def batches(path: Path, size: int):
    batch = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                batch.append(json.loads(line))
            if len(batch) == size:
                yield batch
                batch = []
    if batch:
        yield batch


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("set DATABASE_URL or pass --database-url")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")

    client = OpenAI()
    inserted = 0
    touched_set_ids = set()
    with psycopg.connect(args.database_url) as connection:
        connection.execute(SCHEMA_SQL)
        for batch in batches(args.jsonl, args.batch_size):
            response = client.embeddings.create(
                model=args.model,
                input=[record["text"] for record in batch],
                dimensions=1536,
            )
            rows = []
            embeddings = sorted(response.data, key=lambda item: item.index)
            for record, embedding in zip(batch, embeddings):
                metadata = record["metadata"]
                touched_set_ids.add(metadata["set_id"])
                vector = "[" + ",".join(map(str, embedding.embedding)) + "]"
                rows.append(
                    (
                        record["id"],
                        metadata["set_id"],
                        metadata["version"],
                        metadata["section_code"],
                        record["text"],
                        Jsonb(metadata),
                        vector,
                    )
                )
            connection.executemany(UPSERT_SQL, rows)
            connection.commit()
            inserted += len(rows)
            print(f"Upserted {inserted} chunks")
        if touched_set_ids:
            connection.execute(
                """
                UPDATE drug_label_chunks AS chunk
                SET is_current = (chunk.spl_version::integer = latest.version)
                FROM (
                    SELECT set_id, max(spl_version::integer) AS version
                    FROM drug_label_chunks
                    WHERE set_id = ANY(%s)
                    GROUP BY set_id
                ) AS latest
                WHERE chunk.set_id = latest.set_id
                """,
                (list(touched_set_ids),),
            )
            connection.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
