"""RAG-backed care-plan generation orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .prompt_manager import PromptManager
from .rag.pgvector_store import PgVectorStore, SearchResult


@dataclass(frozen=True)
class GeneratedCarePlan:
    text: str
    prompt_version: str
    retrieval_query: str
    retrieved_chunks: list[dict[str, Any]]


def build_retrieval_query(medication: str, diagnosis: str) -> str:
    return f"Medication: {medication}\nDiagnosis or condition: {diagnosis}"


def _serialize_result(result: SearchResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "score": result.score,
        "text": result.text,
        "metadata": result.metadata,
    }


def format_retrieved_context(results: list[SearchResult]) -> str:
    if not results:
        return (
            "No sufficiently relevant drug-label reference was retrieved. "
            "Do not supply drug facts from memory; identify what must be confirmed."
        )

    references = []
    for index, result in enumerate(results, start=1):
        metadata = result.metadata
        references.append(
            "\n".join(
                [
                    f"<drug_reference id=\"{index}\">",
                    f"Chunk ID: {result.id}",
                    f"Similarity score: {result.score:.4f}",
                    f"Drug label: {metadata.get('label_title', 'Unknown')}",
                    f"Section: {metadata.get('section_title', 'Unknown')}",
                    f"DailyMed set_id: {metadata.get('set_id', 'Unknown')}",
                    f"Source URL: {metadata.get('source_url', 'Unknown')}",
                    "Reference text:",
                    result.text,
                    "</drug_reference>",
                ]
            )
        )
    return "\n\n".join(references)


class CarePlanGenerator:
    def __init__(
        self,
        *,
        prompt_manager: PromptManager,
        vector_store: PgVectorStore,
        client: Any,
        model: str,
        top_k: int = 5,
        min_score: float = 0.55,
    ) -> None:
        self.prompt_manager = prompt_manager
        self.vector_store = vector_store
        self.client = client
        self.model = model
        self.top_k = top_k
        self.min_score = min_score

    def generate(
        self,
        *,
        patient_name: str,
        medication: str,
        diagnosis: str,
        patient_record: str,
    ) -> GeneratedCarePlan:
        retrieval_query = build_retrieval_query(medication, diagnosis)
        results = self.vector_store.search(
            retrieval_query,
            top_k=self.top_k,
            min_score=self.min_score,
        )
        retrieved_context = format_retrieved_context(results)
        rendered_prompt = self.prompt_manager.render(
            "care_plan",
            variables={
                "patient_name": patient_name,
                "medication": medication,
                "condition": diagnosis,
                "patient_record": patient_record or "No patient record was provided.",
                "retrieved_context": retrieved_context,
            },
        )
        response = self.client.responses.create(
            model=self.model,
            input=rendered_prompt.content,
        )
        if not response.output_text.strip():
            raise RuntimeError("care-plan model returned an empty response")

        return GeneratedCarePlan(
            text=response.output_text,
            prompt_version=rendered_prompt.version,
            retrieval_query=retrieval_query,
            retrieved_chunks=[_serialize_result(result) for result in results],
        )
