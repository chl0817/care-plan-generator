import json
from dotenv import load_dotenv
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI
from .models import CarePlan

load_dotenv()

def index(request):
    return render(request, "index.html")

@csrf_exempt
def create_careplan(request):
    data = json.loads(request.body)

    patient_name = data["patient_name"]
    medication = data["medication"]
    condition = data["condition"]

    prompt = f"""
You are helping a CVS healthcare worker create a patient care plan.

Patient name: {patient_name}
Medication: {medication}
Condition or notes: {condition}

Generate a care plan with exactly these sections:
Problem list
Goals
Pharmacist interventions
Monitoring plan
"""

    client = OpenAI()

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
    )

    careplan_text = response.output_text

    careplan = CarePlan.objects.create(
        patient_name=patient_name,
        medication=medication,
        condition=condition,
        generated_text=careplan_text,
    )

    return JsonResponse({
        "id": careplan.id,
        "care_plan": careplan.generated_text,
    })