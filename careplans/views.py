import json
from dotenv import load_dotenv
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI
from .models import CarePlan
from .prompt_manager import PromptManager

load_dotenv()

def index(request):
    return render(request, "index.html")

@csrf_exempt
def create_careplan(request):
    data = json.loads(request.body)

    patient_name = data["patient_name"]
    medication = data["medication"]
    condition = data["condition"]

    rendered_prompt = PromptManager(settings.PROMPTS_DIR).render(
        "care_plan",
        variables={
            "patient_name": patient_name,
            "medication": medication,
            "condition": condition,
        },
    )

    client = OpenAI()

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=rendered_prompt.content,
    )

    careplan_text = response.output_text

    careplan = CarePlan.objects.create(
        patient_name=patient_name,
        medication=medication,
        condition=condition,
        generated_text=careplan_text,
        prompt_version=rendered_prompt.version,
    )

    return JsonResponse({
        "id": careplan.id,
        "care_plan": careplan.generated_text,
        "prompt_version": careplan.prompt_version,
    })
