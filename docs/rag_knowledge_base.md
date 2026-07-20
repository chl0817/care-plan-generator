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

For this application, prefer pgvector over Chroma. The care-plan system already
targets PostgreSQL, while the drug-label index needs transactions, durable
storage, metadata filters, current/old SPL version handling, and an audit trail.
Chroma remains useful for a quick notebook or disposable local prototype.

Start the included pgvector service:

```bash
docker compose up -d db
export DATABASE_URL='postgresql://careplan:careplan@localhost:5432/careplan'
```

Then embed and index the generated chunks:

```bash
export OPENAI_API_KEY='...'
python3 scripts/index_chunks_pgvector.py data/dailymed/chunks.jsonl
```

The indexer creates an HNSW cosine index and idempotently upserts each chunk. It
uses `text-embedding-3-small` with 1,536 dimensions. Keep the same embedding
model and dimensions for both indexing and queries.

A reusable search function is available from application code:

```python
from careplans.rag.pgvector_store import search_chunks

results = search_chunks(
    "What are the contraindications for ethacrynic acid?",
    top_k=5,
)

for result in results:
    print(result.score, result.metadata["section_title"])
    print(result.text)
```

You can apply exact metadata filters when the medication or SPL identifier is
already known:

```python
results = search_chunks(
    "recommended dosage",
    top_k=5,
    metadata_filter={"set_id": "1efe378e-fee1-4ae9-8ea5-0fe2265fe2d8"},
)
```

Or test retrieval from the command line:

```bash
python3 scripts/search_dailymed.py \
  "What are the contraindications for ethacrynic acid?" \
  --top-k 5
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
