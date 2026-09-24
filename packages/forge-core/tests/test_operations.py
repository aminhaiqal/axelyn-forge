import copy
import tempfile
import unittest
from pathlib import Path

from forge.api import apply_resume_operations_file
from forge.errors import OperationError, ResumeValidationError
from forge.jsonio import load_json
from forge.operations import apply_operations

from .helpers import DATA, SCHEMA


class ResumeOperationTests(unittest.TestCase):
    def setUp(self):
        self.resume = load_json(DATA)

    def test_rewrites_absolute_and_stable_id_targets_without_mutating_master(self):
        operations = {
            "operations": [
                {
                    "operation": "rewrite",
                    "target": "document.profile.headline",
                    "value": "Target headline",
                },
                {
                    "operation": "rewrite",
                    "target": "summary-1",
                    "value": "Target summary",
                },
                {
                    "operation": "rewrite",
                    "target": "skills-programming",
                    "field": "items",
                    "value": ["TypeScript", "Python", "SQL"],
                },
            ]
        }

        tailored, targets = apply_operations(self.resume, operations)

        self.assertEqual("Target headline", tailored["document"]["profile"]["headline"])
        self.assertEqual("Target summary", tailored["document"]["sections"][0]["content"][0]["text"])
        self.assertEqual(
            ["TypeScript", "Python", "SQL"],
            tailored["document"]["sections"][5]["groups"][0]["items"],
        )
        self.assertNotEqual("Target headline", self.resume["document"]["profile"]["headline"])
        self.assertEqual(3, len(targets))

    def test_unknown_target_fails_clearly(self):
        operations = {
            "operations": [
                {"operation": "rewrite", "target": "missing-entity", "value": "No"}
            ]
        }
        with self.assertRaisesRegex(OperationError, "missing-entity"):
            apply_operations(self.resume, operations)

    def test_invalid_tailored_result_is_not_written(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            operation_path = Path(temp_dir) / "operations.json"
            output = Path(temp_dir) / "tailored.json"
            operation_path.write_text(
                '{"operations":[{"operation":"rewrite","target":"document.profile.fullName","value":""}]}',
                encoding="utf-8",
            )

            with self.assertRaises(ResumeValidationError):
                apply_resume_operations_file(
                    data=DATA,
                    schema=SCHEMA,
                    operations=operation_path,
                    output=output,
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
