import io
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from careplans.rag.dailymed import chunk_spl, iter_spl_documents, parse_spl


SAMPLE_SPL = b"""<?xml version="1.0" encoding="UTF-8"?>
<document xmlns="urn:hl7-org:v3">
  <id root="document-1" />
  <code code="34391-3" displayName="HUMAN PRESCRIPTION DRUG LABEL" />
  <title>EXAMPLE DRUG (EXAMPLINE) TABLET [EXAMPLE PHARMA]</title>
  <effectiveTime value="20260720" />
  <setId root="set-1" />
  <versionNumber value="3" />
  <author><assignedEntity><representedOrganization><name>Example Pharma</name>
  </representedOrganization></assignedEntity></author>
  <component><structuredBody>
    <component><section>
      <code code="34067-9" />
      <title>INDICATIONS AND USAGE</title>
      <text><paragraph>Example Drug is indicated for condition A.</paragraph>
      <list><item>Use one.</item><item>Use two.</item></list></text>
    </section></component>
  </structuredBody></component>
</document>"""


class WordCodec:
    def __init__(self):
        self.words = []

    def encode(self, text):
        tokens = []
        for word in text.split():
            try:
                token = self.words.index(word)
            except ValueError:
                self.words.append(word)
                token = len(self.words) - 1
            tokens.append(token)
        return tokens

    def decode(self, tokens):
        return " ".join(self.words[token] for token in tokens)


class DailyMedParsingTests(TestCase):
    def test_parse_spl_preserves_retrieval_metadata_and_narrative(self):
        document = parse_spl(SAMPLE_SPL, "sample.xml")

        self.assertEqual(document.set_id, "set-1")
        self.assertEqual(document.version, "3")
        self.assertEqual(document.manufacturer, "Example Pharma")
        self.assertEqual(document.sections[0].code, "34067-9")
        self.assertIn("Use one.", document.sections[0].text)
        self.assertIn("Use two.", document.sections[0].text)

    def test_chunk_spl_adds_header_and_citation_metadata(self):
        document = parse_spl(SAMPLE_SPL, "sample.xml")

        chunks = list(chunk_spl(document, chunk_size=100, overlap=10, codec=WordCodec()))

        self.assertEqual(len(chunks), 1)
        self.assertIn("Section: INDICATIONS AND USAGE", chunks[0].text)
        self.assertEqual(chunks[0].metadata["set_id"], "set-1")
        self.assertEqual(chunks[0].metadata["section_code"], "34067-9")
        self.assertLessEqual(chunks[0].metadata["token_count"], 100)

    def test_chunk_parameters_are_validated(self):
        document = parse_spl(SAMPLE_SPL)

        with self.assertRaisesRegex(ValueError, "at least 100"):
            list(chunk_spl(document, chunk_size=99, overlap=10, codec=WordCodec()))

    def test_nested_release_zip_is_supported(self):
        nested_buffer = io.BytesIO()
        with zipfile.ZipFile(nested_buffer, "w") as nested:
            nested.writestr("label.xml", SAMPLE_SPL)

        with TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "release.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("one-label.zip", nested_buffer.getvalue())

            documents = list(iter_spl_documents([archive_path]))

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].set_id, "set-1")
