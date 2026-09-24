import copy
import unittest

from forge.errors import DuplicateResumeIdError, ResumeValidationError
from forge.jsonio import load_json
from forge.validation import validate_resume

from .helpers import DATA, SCHEMA


class ResumeValidationTests(unittest.TestCase):
    def setUp(self):
        self.resume = load_json(DATA)
        self.schema = load_json(SCHEMA)

    def test_reference_resume_is_valid(self):
        validate_resume(self.resume, self.schema)

    def test_malformed_resume_fails_with_path(self):
        malformed = copy.deepcopy(self.resume)
        del malformed["document"]["profile"]["fullName"]

        with self.assertRaisesRegex(ResumeValidationError, r"\$\.document\.profile"):
            validate_resume(malformed, self.schema)

    def test_duplicate_stable_ids_are_rejected(self):
        malformed = copy.deepcopy(self.resume)
        projects = malformed["document"]["sections"][2]["items"]
        projects[1]["id"] = projects[0]["id"]

        with self.assertRaisesRegex(DuplicateResumeIdError, "Duplicate stable ID"):
            validate_resume(malformed, self.schema)


if __name__ == "__main__":
    unittest.main()
