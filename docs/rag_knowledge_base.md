# DailyMed RAG knowledge base

## Recommended chunking

Start with **800 tokens per chunk and 120 tokens of overlap**. The builder first
splits each label at its SPL section boundaries (for example, Indications,
Dosage, Contraindications, and Warnings), then applies token windows only when a
section is too large. Every chunk repeats the drug-label title and section title.

This is a starting point, not a universal optimum. Evaluate retrieval with real
questions and compare roughly 600/100, 800/120, and 1,000/150. Avoid a very high
overlap for this corpus because boilerplate is already repeated across labels.

## 1. Build chunks

Install dependencies:

```bash
pip install -r requirements.txt
```

For a quick test with one current DailyMed label:

```bash
python3 scripts/build_dailymed_kb.py \
  --set-id 1efe378e-fee1-4ae9-8ea5-0fe2265fe2d8 \
  --output data/dailymed/chunks.jsonl
```

For a downloaded release ZIP (nested ZIPs are supported):

```bash
python3 scripts/build_dailymed_kb.py \
  /path/to/dm_spl_release_human_rx_part1.zip \
  --output data/dailymed/human_rx_part1.jsonl \
  --chunk-size 800 \
  --overlap 120
```

The full human prescription release is split into several multi-gigabyte files.
Process one part at a time. Use `--limit 10` for a smoke test before a full run.
The output is JSONL with `id`, `text`, and citation/filter metadata including
DailyMed `set_id`, SPL version, effective date, label type, manufacturer, and
section code/title.

## 2. Store embeddings in PostgreSQL/pgvector

Use a PostgreSQL image/package that includes the `vector` extension, then set:

```bash
export DATABASE_URL='postgresql://user:password@localhost:5432/careplan'
export OPENAI_API_KEY='...'
python3 scripts/index_chunks_pgvector.py data/dailymed/chunks.jsonl
```

The indexer creates an HNSW cosine index and idempotently upserts each chunk. It
uses `text-embedding-3-small` with 1,536 dimensions. Keep the same embedding
model and dimensions for both indexing and queries.

A retrieval query follows the same pattern:

```python
query_vector = client.embeddings.create(
    model="text-embedding-3-small",
    input=[question],
    dimensions=1536,
).data[0].embedding

rows = connection.execute(
    """
    SELECT content, metadata, 1 - (embedding <=> %s::vector) AS score
    FROM drug_label_chunks
    WHERE is_current
      AND metadata->>'label_type' ILIKE '%%HUMAN%%'
    ORDER BY embedding <=> %s::vector
    LIMIT 8
    """,
    (str(query_vector), str(query_vector)),
).fetchall()
```

In production, add lexical/BM25 search and fuse it with vector results. Drug
names, NDCs, strengths, abbreviations, and section codes are exact identifiers
that pure semantic search can miss. Also filter to the current SPL version and
show `source_url` beside generated clinical content so a pharmacist can verify
the source label.

## 3. Update strategy

1. Bootstrap from the full human prescription release.
2. Poll the DailyMed daily or weekly update ZIP.
3. Rebuild labels keyed by `set_id`; a higher SPL `version` supersedes the old
   label in the active retrieval corpus.
4. The indexer marks only the highest imported version for each `set_id` as
   `is_current`; retrieval must include that filter. Older rows remain available
   for an audit trail.
5. Validate download checksums published by DailyMed before production import.

DailyMed labels are source material for retrieval, not a substitute for clinical
review. The generation path should cite the retrieved label sections and must
not silently invent dosing or contraindication facts.
