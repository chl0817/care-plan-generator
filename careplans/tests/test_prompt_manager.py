from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from django.conf import settings

from careplans.prompt_manager import (
    PromptManager,
    PromptNotFoundError,
    PromptRenderError,
)


class PromptManagerTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.prompts_dir = Path(self.temp_dir.name)
        (self.prompts_dir / "care_plan").mkdir()
        (self.prompts_dir / "config.yaml").write_text(
            """
prompts:
  care_plan:
    default_version: v1
    versions:
      v1:
        file: care_plan/v1.txt
      v2:
        file: care_plan/v2.txt
""".strip(),
            encoding="utf-8",
        )
        (self.prompts_dir / "care_plan" / "v1.txt").write_text(
            "Patient: {patient_name}", encoding="utf-8"
        )
        (self.prompts_dir / "care_plan" / "v2.txt").write_text(
            "Patient name: {patient_name}", encoding="utf-8"
        )
        self.manager = PromptManager(self.prompts_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_render_uses_default_version(self):
        prompt = self.manager.render("care_plan", {"patient_name": "Alex"})

        self.assertEqual(prompt.content, "Patient: Alex")
        self.assertEqual(prompt.version, "v1")
        self.assertEqual(prompt.name, "care_plan")

    def test_render_uses_requested_version(self):
        prompt = self.manager.render(
            "care_plan", {"patient_name": "Alex"}, version="v2"
        )

        self.assertEqual(prompt.content, "Patient name: Alex")
        self.assertEqual(prompt.version, "v2")

    def test_render_rejects_missing_variables(self):
        with self.assertRaisesRegex(PromptRenderError, "patient_name"):
            self.manager.render("care_plan", {})

    def test_load_rejects_unknown_version(self):
        with self.assertRaises(PromptNotFoundError):
            self.manager.load("care_plan", version="v3")


class ProjectPromptConfigurationTests(TestCase):
    def test_care_plan_v3_is_the_project_default(self):
        prompt = PromptManager(settings.PROMPTS_DIR).render(
            "care_plan",
            {
                "patient_name": "Alex",
                "medication": "Example medication",
                "condition": "Example condition",
                "patient_record": "Example patient record",
                "retrieved_context": "Example DailyMed reference",
            },
        )

        self.assertEqual(prompt.version, "v3")
        self.assertIn("Example patient record", prompt.content)
        self.assertIn("Example DailyMed reference", prompt.content)
        self.assertIn("Do not fill the gap from memory", prompt.content)
