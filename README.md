# Care Plan Generator

AI powered Care Plan Generator for Specialty Pharmacy

## Features

- Patient validation
- Duplicate detection
- Provider validation
- AI generated Care Plans
- Care Plan download
- Reporting export

## Tech Stack

- Python
- FastAPI
- OpenAI API
- SQLite / PostgreSQL
- React (Future)

## Documentation

See `design.md`.

## Running

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Prompt versioning

Prompt text is kept outside the application code:

```text
prompts/
├── config.yaml
└── care_plan/
    ├── v1.txt
    └── v2.txt
```

`prompts/config.yaml` maps each prompt and version to a template file and selects
the default version. To release a new version, add (for example)
`prompts/care_plan/v2.txt`, register it under `versions`, then change
`default_version` when it is ready for use. Existing care plans retain the exact
version used in their `prompt_version` field.

Application code renders prompts through `careplans.prompt_manager.PromptManager`:

```python
rendered = manager.render(
    "care_plan",
    variables={"patient_name": "Alex", "medication": "...", "condition": "..."},
    version="v1",  # Optional; omit to use config.yaml's default_version.
)

rendered.content
rendered.version
```

## DailyMed RAG knowledge base

The project includes a section-aware DailyMed SPL parser/chunker and a
PostgreSQL/pgvector indexing script. See
[`docs/rag_knowledge_base.md`](docs/rag_knowledge_base.md) for setup, chunking,
indexing, retrieval, and incremental-update instructions.
