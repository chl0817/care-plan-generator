"""RAG-backed care-plan generation orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .prompt_manager import PromptManager
from .rag.pgvector_store import PgVectorStore, SearchResult


class CarePlanOutput(BaseModel):
    """The JSON shape returned by the care-plan model."""

    model_config = ConfigDict(extra="forbid")

    problem_list: list[str] = Field(min_length=1)
    goals: list[str] = Field(min_length=1)
    pharmacist_interventions: list[str] = Field(min_length=1)
    monitoring_plan: list[str] = Field(min_length=1)


@dataclass(frozen=True)
class GeneratedCarePlan:
    text: str
    prompt_version: str
    retrieval_query: str
    retrieved_chunks: list[dict[str, Any]]
    structured_data: dict[str, Any] | None = None
    parse_failed: bool = False
    raw_output: str = ""
    validation_errors: tuple[str, ...] = ()


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
    MAX_PARSE_RETRIES: ClassVar[int] = 2

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

        response_format = {
            "format": {
                "type": "json_schema",
                "name": "care_plan",
                "schema": CarePlanOutput.model_json_schema(),
                "strict": True,
            }
        }
        model_input: str | list[dict[str, str]] = rendered_prompt.content
        raw_output = ""
        validation_errors: list[str] = []

        for attempt in range(self.MAX_PARSE_RETRIES + 1):
            response = self.client.responses.create(
                model=self.model,
                input=model_input,
                text=response_format,
            )
            raw_output = response.output_text

            try:
                care_plan = CarePlanOutput.model_validate_json(raw_output)
            except (ValidationError, ValueError) as exc:
                error = _format_validation_error(exc, raw_output)
                validation_errors.append(error)
                if attempt == self.MAX_PARSE_RETRIES:
                    return GeneratedCarePlan(
                        text=raw_output,
                        prompt_version=rendered_prompt.version,
                        retrieval_query=retrieval_query,
                        retrieved_chunks=[
                            _serialize_result(result) for result in results
                        ],
                        parse_failed=True,
                        raw_output=raw_output,
                        validation_errors=tuple(validation_errors),
                    )

                model_input = [
                    {"role": "user", "content": rendered_prompt.content},
                    {"role": "assistant", "content": raw_output},
                    {
                        "role": "user",
                        "content": (
                            "Your previous JSON did not validate against the required "
                            "care-plan schema. Correct it and return only the complete "
                            "JSON object.\n\nValidation error:\n"
                            f"{error}"
                        ),
                    },
                ]
                continue

            structured_data = care_plan.model_dump(mode="json")
            return GeneratedCarePlan(
                text=json.dumps(structured_data, ensure_ascii=False),
                prompt_version=rendered_prompt.version,
                retrieval_query=retrieval_query,
                retrieved_chunks=[
                    _serialize_result(result) for result in results
                ],
                structured_data=structured_data,
                raw_output=raw_output,
                validation_errors=tuple(validation_errors),
            )

        raise AssertionError("unreachable")


def _format_validation_error(exc: Exception, raw_output: str) -> str:
    if not raw_output.strip():
        return "The model returned an empty response instead of a JSON object."
    if isinstance(exc, ValidationError):
        return json.dumps(exc.errors(include_url=False), ensure_ascii=False)
    return str(exc)
