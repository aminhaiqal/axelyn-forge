import copy
import json
import tempfile
import unittest
from pathlib import Path

from forge.api import render_resume
from forge.docx import inspect_docx, render_docx, validate_docx_archive
from forge.errors import DocxError, MissingTemplateBindingError, ResumeValidationError
from forge.jsonio import load_json

from .helpers import BINDINGS, DATA, SCHEMA, TEMPLATE, formatting_signature


class DocxRendererTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.output = Path(self.temp_dir.name) / "rendered.docx"
        self.controls = inspect_docx(TEMPLATE)
        self.current_values = {control.tag: control.current_text for control in self.controls}

    def test_discovers_all_reference_controls(self):
        self.assertEqual(64, len(self.controls))
        self.assertEqual(64, len(self.current_values))
        self.assertEqual("word/document.xml", self.controls[0].part)
        self.assertEqual("profile.fullName", self.controls[0].tag)

    def test_identity_render_is_an_exact_archive_copy(self):
        report = render_docx(TEMPLATE, self.output, self.current_values)

        self.assertEqual(0, report.changed_controls)
        self.assertEqual(TEMPLATE.read_bytes(), self.output.read_bytes())

    def test_basic_multiple_and_unicode_replacements(self):
        values = dict(self.current_values)
        values.update(
            {
                "profile.fullName": "Muhammad Amin Haiqal — محمد أمين",
                "summary.text": "Unicode-safe résumé content ✓",
                "education.utm.meta": "Universiti Teknologi Malaysia | Johor Bahru",
            }
        )
        template_before = TEMPLATE.read_bytes()

        report = render_docx(TEMPLATE, self.output, values)
        rendered = {control.tag: control.current_text for control in inspect_docx(self.output)}

        self.assertEqual(3, report.changed_controls)
        self.assertEqual("Muhammad Amin Haiqal — محمد أمين", rendered["profile.fullName"])
        self.assertEqual("Unicode-safe résumé content ✓", rendered["summary.text"])
        self.assertEqual(
            "Universiti Teknologi Malaysia | Johor Bahru",
            rendered["education.utm.meta"],
        )
        self.assertEqual(template_before, TEMPLATE.read_bytes())
        validate_docx_archive(self.output)

    def test_replacement_preserves_paragraph_and_run_properties(self):
        values = dict(self.current_values)
        values["summary.text"] = "A much shorter replacement summary."
        before = formatting_signature(TEMPLATE, "summary.text")

        render_docx(TEMPLATE, self.output, values)

        self.assertEqual(before, formatting_signature(self.output, "summary.text"))

    def test_missing_binding_fails_without_creating_output(self):
        values = dict(self.current_values)
        del values["experience.axelyn.role"]

        with self.assertRaisesRegex(MissingTemplateBindingError, "experience.axelyn.role"):
            render_docx(TEMPLATE, self.output, values)
        self.assertFalse(self.output.exists())

    def test_renderer_refuses_to_modify_template_in_place(self):
        with self.assertRaisesRegex(DocxError, "source template"):
            render_docx(TEMPLATE, TEMPLATE, self.current_values)

    def test_complete_resume_pipeline_produces_valid_docx(self):
        result = render_resume(
            template=TEMPLATE,
            data=DATA,
            schema=SCHEMA,
            bindings=BINDINGS,
            output=self.output,
        )

        self.assertEqual(64, result.resolved_values)
        self.assertEqual(64, result.report.controls)
        self.assertEqual((), result.report.unused_values)
        validate_docx_archive(self.output)

    def test_changed_render_is_deterministic(self):
        second_output = Path(self.temp_dir.name) / "rendered-again.docx"

        render_resume(
            template=TEMPLATE,
            data=DATA,
            schema=SCHEMA,
            bindings=BINDINGS,
            output=self.output,
        )
        render_resume(
            template=TEMPLATE,
            data=DATA,
            schema=SCHEMA,
            bindings=BINDINGS,
            output=second_output,
        )

        self.assertEqual(self.output.read_bytes(), second_output.read_bytes())

    def test_invalid_resume_fails_before_docx_access_or_output_write(self):
        malformed = copy.deepcopy(load_json(DATA))
        del malformed["document"]["profile"]["fullName"]
        invalid_data = Path(self.temp_dir.name) / "invalid.json"
        invalid_data.write_text(json.dumps(malformed), encoding="utf-8")
        nonexistent_template = Path(self.temp_dir.name) / "does-not-exist.docx"

        with self.assertRaises(ResumeValidationError):
            render_resume(
                template=nonexistent_template,
                data=invalid_data,
                schema=SCHEMA,
                bindings=BINDINGS,
                output=self.output,
            )
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
