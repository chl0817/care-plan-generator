import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from openai import OpenAI

from .care_plan_service import CarePlanGenerator
from .models import CarePlan
from .prompt_manager import PromptManager
from .rag.pgvector_store import PgVectorStore


logger = logging.getLogger(__name__)


def index(request):
    return render(request, "index.html")


def _required_text(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


@csrf_exempt
@require_POST
def create_careplan(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        patient_name = _required_text(data, "patient_name")
        medication = _required_text(data, "medication")
        condition = _required_text(data, "condition")
        patient_record = data.get("patient_record", "")
        if not isinstance(patient_record, str):
            raise ValueError("patient_record must be text")
        patient_record = patient_record.strip()
    except (json.JSONDecodeError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    try:
        client = OpenAI()
        generator = CarePlanGenerator(
            prompt_manager=PromptManager(settings.PROMPTS_DIR),
            vector_store=PgVectorStore(
                settings.RAG_DATABASE_URL,
                client=client,
            ),
            client=client,
            model=settings.CARE_PLAN_MODEL,
            top_k=settings.RAG_TOP_K,
            min_score=settings.RAG_MIN_SCORE,
        )
        generated = generator.generate(
            patient_name=patient_name,
            medication=medication,
            diagnosis=condition,
            patient_record=patient_record,
        )
    except Exception:
        logger.exception("RAG care-plan generation failed")
        return JsonResponse(
            {
                "error": (
                    "Care plan generation is temporarily unavailable because "
                    "retrieval or model generation failed."
                )
            },
            status=503,
        )

    careplan = CarePlan.objects.create(
        patient_name=patient_name,
        medication=medication,
        condition=condition,
        patient_record=patient_record,
        retrieval_query=generated.retrieval_query,
        retrieved_chunks=generated.retrieved_chunks,
        generated_text=generated.text,
        prompt_version=generated.prompt_version,
    )

    return JsonResponse(
        {
            "id": careplan.id,
            "care_plan": careplan.generated_text,
            "prompt_version": careplan.prompt_version,
            "references": [
                {
                    "id": chunk["id"],
                    "score": chunk["score"],
                    "section_title": chunk["metadata"].get("section_title"),
                    "source_url": chunk["metadata"].get("source_url"),
                }
                for chunk in generated.retrieved_chunks
            ],
        }
    )
