"""OpenAI embeddings backed by PostgreSQL/pgvector."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

import psycopg
from openai import OpenAI
from psycopg.types.json import Jsonb


DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 1536

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


@dataclass(frozen=True)
class SearchResult:
    id: str
    text: str
    score: float
    metadata: dict[str, Any]


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(map(str, values)) + "]"


def _jsonl_batches(path: Path, size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                record["id"]
                record["text"]
                record["metadata"]["set_id"]
                record["metadata"]["version"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(f"invalid chunk JSONL at line {line_number}") from exc
            batch.append(record)
            if len(batch) == size:
                yield batch
                batch = []
    if batch:
        yield batch


class PgVectorStore:
    """Index and search DailyMed chunks in pgvector.

    ``client`` and ``connection_factory`` are injectable to keep this class easy
    to test without calling OpenAI or running PostgreSQL.
    """

    def __init__(
        self,
        database_url: str,
        *,
        client: Any | None = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
        connection_factory: Any = psycopg.connect,
    ) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        if dimensions != DEFAULT_EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"the current schema requires {DEFAULT_EMBEDDING_DIMENSIONS} dimensions"
            )
        self.database_url = database_url
        self.client = client or OpenAI()
        self.embedding_model = embedding_model
        self.dimensions = dimensions
        self._connect = connection_factory

    def initialize(self) -> None:
        with self._connect(self.database_url) as connection:
            connection.execute(SCHEMA_SQL)
            connection.commit()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("embedding input cannot be empty")
        response = self.client.embeddings.create(
            model=self.embedding_model,
            input=list(texts),
            dimensions=self.dimensions,
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(texts):
            raise RuntimeError("embedding API returned an unexpected number of vectors")
        return [item.embedding for item in ordered]

    def index_jsonl(self, path: str | Path, *, batch_size: int = 100) -> int:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")

        inserted = 0
        touched_set_ids: set[str] = set()
        with self._connect(self.database_url) as connection:
            connection.execute(SCHEMA_SQL)
            for batch in _jsonl_batches(Path(path), batch_size):
                vectors = self.embed([record["text"] for record in batch])
                rows = []
                for record, vector in zip(batch, vectors):
                    metadata = record["metadata"]
                    touched_set_ids.add(metadata["set_id"])
                    rows.append(
                        (
                            record["id"],
                            metadata["set_id"],
                            str(metadata["version"]),
                            metadata.get("section_code", ""),
                            record["text"],
                            Jsonb(metadata),
                            _vector_literal(vector),
                        )
                    )
                with connection.cursor() as cursor:
                    cursor.executemany(UPSERT_SQL, rows)
                connection.commit()
                inserted += len(rows)

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
        return inserted

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_score: float | None = None,
        metadata_filter: dict[str, Any] | None = None,
        current_only: bool = True,
    ) -> list[SearchResult]:
        """Return the nearest chunks by cosine similarity.

        ``metadata_filter`` performs exact JSON containment, for example
        ``{"section_code": "34067-9"}`` or ``{"set_id": "..."}``.
        """

        if not query.strip():
            raise ValueError("query cannot be empty")
        if not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        if min_score is not None and not 0 <= min_score <= 1:
            raise ValueError("min_score must be between 0 and 1")

        query_vector = _vector_literal(self.embed([query])[0])
        conditions = []
        parameters: list[Any] = [query_vector]
        if current_only:
            conditions.append("is_current")
        if metadata_filter:
            conditions.append("metadata @> %s")
            parameters.append(Jsonb(metadata_filter))
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        parameters.extend([query_vector, top_k])

        sql = f"""
            SELECT id, content, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM drug_label_chunks
            {where_clause}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        with self._connect(self.database_url) as connection:
            rows = connection.execute(sql, parameters).fetchall()

        results = [
            SearchResult(id=row[0], text=row[1], metadata=row[2], score=float(row[3]))
            for row in rows
        ]
        if min_score is not None:
            results = [result for result in results if result.score >= min_score]
        return results


def search_chunks(
    query: str,
    *,
    top_k: int = 5,
    database_url: str | None = None,
    min_score: float | None = None,
    metadata_filter: dict[str, Any] | None = None,
) -> list[SearchResult]:
    """Convenience function for application code."""

    url = database_url or os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("set DATABASE_URL or pass database_url")
    return PgVectorStore(url).search(
        query,
        top_k=top_k,
        min_score=min_score,
        metadata_filter=metadata_filter,
    )
