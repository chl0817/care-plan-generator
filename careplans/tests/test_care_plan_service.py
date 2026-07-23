import json
from types import SimpleNamespace
from unittest import TestCase

from django.conf import settings

from careplans.care_plan_service import CarePlanGenerator
from careplans.prompt_manager import PromptManager
from careplans.rag.pgvector_store import SearchResult


class FakeVectorStore:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return self.results


VALID_CARE_PLAN = {
    "problem_list": ["Problem 1"],
    "goals": ["Goal 1"],
    "pharmacist_interventions": ["Intervention 1"],
    "monitoring_plan": ["Monitor 1"],
}


class FakeResponses:
    def __init__(self, output_texts=None):
        self.output_texts = list(
            output_texts or [json.dumps(VALID_CARE_PLAN)]
        )
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_texts.pop(0))


class CarePlanGeneratorTests(TestCase):
    def make_generator(self, results):
        vector_store = FakeVectorStore(results)
        responses = FakeResponses()
        generator = CarePlanGenerator(
            prompt_manager=PromptManager(settings.PROMPTS_DIR),
            vector_store=vector_store,
            client=SimpleNamespace(responses=responses),
            model="test-model",
            top_k=4,
            min_score=0.6,
        )
        return generator, vector_store, responses

    def test_generate_retrieves_then_adds_references_and_patient_record(self):
        result = SearchResult(
            id="chunk-1",
            text="The label supports this drug fact.",
            score=0.82,
            metadata={
                "label_title": "EXAMPLE DRUG",
                "section_title": "WARNINGS",
                "set_id": "set-1",
                "source_url": "https://example.test/label",
            },
        )
        generator, vector_store, responses = self.make_generator([result])

        generated = generator.generate(
            patient_name="Alex",
            medication="Example Drug",
            diagnosis="Condition A",
            patient_record="Patient-specific laboratory result.",
        )

        query, search_options = vector_store.calls[0]
        self.assertIn("Example Drug", query)
        self.assertIn("Condition A", query)
        self.assertEqual(search_options, {"top_k": 4, "min_score": 0.6})
        prompt = responses.calls[0]["input"]
        self.assertIn("Patient-specific laboratory result.", prompt)
        self.assertIn("The label supports this drug fact.", prompt)
        self.assertIn("Do not fill the gap from memory", prompt)
        self.assertEqual(
            responses.calls[0]["text"]["format"]["type"], "json_schema"
        )
        self.assertTrue(responses.calls[0]["text"]["format"]["strict"])
        self.assertEqual(generated.structured_data, VALID_CARE_PLAN)
        self.assertFalse(generated.parse_failed)
        self.assertEqual(generated.prompt_version, "v3")
        self.assertEqual(generated.retrieved_chunks[0]["id"], "chunk-1")

    def test_generate_handles_no_relevant_reference_without_inventing_context(self):
        generator, _, responses = self.make_generator([])

        generated = generator.generate(
            patient_name="Alex",
            medication="Unknown Drug",
            diagnosis="Condition A",
            patient_record="",
        )

        prompt = responses.calls[0]["input"]
        self.assertIn("No sufficiently relevant drug-label reference", prompt)
        self.assertIn("No patient record was provided", prompt)
        self.assertEqual(generated.retrieved_chunks, [])

    def test_generate_retries_with_validation_error_and_returns_valid_json(self):
        vector_store = FakeVectorStore([])
        responses = FakeResponses(
            [
                '{"problem_list": []}',
                json.dumps(VALID_CARE_PLAN),
            ]
        )
        generator = CarePlanGenerator(
            prompt_manager=PromptManager(settings.PROMPTS_DIR),
            vector_store=vector_store,
            client=SimpleNamespace(responses=responses),
            model="test-model",
        )

        generated = generator.generate(
            patient_name="Alex",
            medication="Example Drug",
            diagnosis="Condition A",
            patient_record="",
        )

        self.assertEqual(len(responses.calls), 2)
        retry_input = responses.calls[1]["input"]
        self.assertIn("Validation error", retry_input[-1]["content"])
        self.assertIn("goals", retry_input[-1]["content"])
        self.assertEqual(generated.structured_data, VALID_CARE_PLAN)
        self.assertEqual(len(generated.validation_errors), 1)
        self.assertFalse(generated.parse_failed)

    def test_generate_marks_parse_failed_after_two_retries(self):
        vector_store = FakeVectorStore([])
        responses = FakeResponses(["not json", "still not json", "last raw output"])
        generator = CarePlanGenerator(
            prompt_manager=PromptManager(settings.PROMPTS_DIR),
            vector_store=vector_store,
            client=SimpleNamespace(responses=responses),
            model="test-model",
        )

        generated = generator.generate(
            patient_name="Alex",
            medication="Example Drug",
            diagnosis="Condition A",
            patient_record="",
        )

        self.assertEqual(len(responses.calls), 3)
        self.assertTrue(generated.parse_failed)
        self.assertIsNone(generated.structured_data)
        self.assertEqual(generated.raw_output, "last raw output")
        self.assertEqual(generated.text, "last raw output")
        self.assertEqual(len(generated.validation_errors), 3)
