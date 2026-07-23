import json
from unittest.mock import patch

from django.test import TestCase

from careplans.care_plan_service import GeneratedCarePlan
from careplans.models import CarePlan


class CreateCarePlanViewTests(TestCase):
    @patch("careplans.views.CarePlanGenerator")
    @patch("careplans.views.PgVectorStore")
    @patch("careplans.views.OpenAI")
    def test_create_careplan_persists_patient_record_and_retrieval_evidence(
        self, openai, vector_store, generator_class
    ):
        generator_class.return_value.generate.return_value = GeneratedCarePlan(
            text='{"problem_list": ["Grounded problem"]}',
            prompt_version="v3",
            retrieval_query="Medication: Example Drug\nDiagnosis or condition: Condition A",
            retrieved_chunks=[
                {
                    "id": "chunk-1",
                    "score": 0.81,
                    "text": "Reference text",
                    "metadata": {
                        "section_title": "WARNINGS",
                        "source_url": "https://example.test/label",
                    },
                }
            ],
            structured_data={
                "problem_list": ["Grounded problem"],
                "goals": ["Grounded goal"],
                "pharmacist_interventions": ["Grounded intervention"],
                "monitoring_plan": ["Grounded monitoring"],
            },
            raw_output='{"problem_list": ["Grounded problem"]}',
        )

        response = self.client.post(
            "/api/careplans/",
            data=json.dumps(
                {
                    "patient_name": "Alex",
                    "medication": "Example Drug",
                    "condition": "Condition A",
                    "patient_record": "Patient record text",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["references"][0]["id"], "chunk-1")
        self.assertEqual(
            response.json()["care_plan"]["problem_list"], ["Grounded problem"]
        )
        self.assertFalse(response.json()["parse_failed"])
        careplan = CarePlan.objects.get()
        self.assertEqual(careplan.patient_record, "Patient record text")
        self.assertEqual(careplan.prompt_version, "v3")
        self.assertEqual(careplan.retrieved_chunks[0]["id"], "chunk-1")
        self.assertEqual(
            careplan.structured_data["monitoring_plan"], ["Grounded monitoring"]
        )
        self.assertFalse(careplan.parse_failed)

    def test_create_careplan_rejects_missing_required_input(self):
        response = self.client.post(
            "/api/careplans/",
            data=json.dumps({"patient_name": "Alex"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("medication", response.json()["error"])

    @patch("careplans.views.CarePlanGenerator")
    @patch("careplans.views.PgVectorStore")
    @patch("careplans.views.OpenAI")
    def test_create_careplan_fails_closed_when_retrieval_fails(
        self, openai, vector_store, generator_class
    ):
        generator_class.return_value.generate.side_effect = RuntimeError("database down")

        response = self.client.post(
            "/api/careplans/",
            data=json.dumps(
                {
                    "patient_name": "Alex",
                    "medication": "Example Drug",
                    "condition": "Condition A",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(CarePlan.objects.count(), 0)
