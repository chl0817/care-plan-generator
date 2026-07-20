import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from careplans.rag.pgvector_store import PgVectorStore


class FakeEmbeddings:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        # Deliberately reverse API items; PgVectorStore must restore input order.
        data = [
            SimpleNamespace(index=index, embedding=[float(index), 0.5])
            for index in reversed(range(len(kwargs["input"])))
        ]
        return SimpleNamespace(data=data)


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.batch_calls = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, sql, parameters=None):
        self.calls.append((sql, parameters))
        return self

    def fetchall(self):
        return self.rows

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def executemany(self, sql, rows):
        self.connection.batch_calls.append((sql, rows))


class PgVectorStoreTests(TestCase):
    def test_embed_preserves_input_order_and_configuration(self):
        embeddings = FakeEmbeddings()
        store = PgVectorStore(
            "postgresql://example",
            client=SimpleNamespace(embeddings=embeddings),
            connection_factory=lambda _: None,
        )

        vectors = store.embed(["first", "second"])

        self.assertEqual(vectors, [[0.0, 0.5], [1.0, 0.5]])
        self.assertEqual(embeddings.calls[0]["model"], "text-embedding-3-small")
        self.assertEqual(embeddings.calls[0]["dimensions"], 1536)

    def test_search_returns_top_k_chunks_with_metadata_filter(self):
        embeddings = FakeEmbeddings()
        connection = FakeConnection(
            [("chunk-1", "Relevant label text", {"section_code": "34067-9"}, 0.91)]
        )
        store = PgVectorStore(
            "postgresql://example",
            client=SimpleNamespace(embeddings=embeddings),
            connection_factory=lambda _: connection,
        )

        results = store.search(
            "What is this drug used for?",
            top_k=3,
            metadata_filter={"section_code": "34067-9"},
        )

        self.assertEqual(results[0].id, "chunk-1")
        self.assertEqual(results[0].score, 0.91)
        self.assertIn("is_current", connection.calls[0][0])
        self.assertIn("metadata @> %s", connection.calls[0][0])
        self.assertEqual(connection.calls[0][1][-1], 3)

    def test_search_validates_query_and_top_k(self):
        store = PgVectorStore(
            "postgresql://example",
            client=SimpleNamespace(embeddings=FakeEmbeddings()),
            connection_factory=lambda _: None,
        )

        with self.assertRaisesRegex(ValueError, "query"):
            store.search("   ")
        with self.assertRaisesRegex(ValueError, "top_k"):
            store.search("query", top_k=101)
        with self.assertRaisesRegex(ValueError, "min_score"):
            store.search("query", min_score=1.1)

    def test_search_applies_minimum_score(self):
        embeddings = FakeEmbeddings()
        connection = FakeConnection(
            [
                ("relevant", "Relevant", {}, 0.8),
                ("weak", "Weak", {}, 0.4),
            ]
        )
        store = PgVectorStore(
            "postgresql://example",
            client=SimpleNamespace(embeddings=embeddings),
            connection_factory=lambda _: connection,
        )

        results = store.search("query", top_k=2, min_score=0.55)

        self.assertEqual([result.id for result in results], ["relevant"])

    def test_index_jsonl_batches_embeddings_and_database_writes(self):
        embeddings = FakeEmbeddings()
        connection = FakeConnection([])
        store = PgVectorStore(
            "postgresql://example",
            client=SimpleNamespace(embeddings=embeddings),
            connection_factory=lambda _: connection,
        )
        record = {
            "id": "chunk-1",
            "text": "Drug label text",
            "metadata": {
                "set_id": "set-1",
                "version": "2",
                "section_code": "34067-9",
            },
        }

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "chunks.jsonl"
            path.write_text(json.dumps(record), encoding="utf-8")
            count = store.index_jsonl(path)

        self.assertEqual(count, 1)
        self.assertEqual(len(connection.batch_calls), 1)
        self.assertEqual(connection.batch_calls[0][1][0][0], "chunk-1")
        self.assertGreaterEqual(connection.commits, 2)
