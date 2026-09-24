import copy
import unittest

from forge.bindings import resolve_bindings
from forge.docx import inspect_docx
from forge.errors import BindingError
from forge.jsonio import load_json

from .helpers import BINDINGS, DATA, TEMPLATE


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.resume = load_json(DATA)
        self.config = load_json(BINDINGS)

    def test_fixture_resolves_every_discovered_template_tag(self):
        resolved = resolve_bindings(self.resume, self.config)
        template_tags = {control.tag for control in inspect_docx(TEMPLATE)}

        self.assertEqual(64, len(resolved))
        self.assertEqual(template_tags, set(resolved))
        self.assertEqual("Software Engineer", resolved["experience.axelyn.role"])
        self.assertEqual(
            "Python, Go, TypeScript, SQL",
            resolved["skills.programming.items"],
        )

    def test_composition_and_link_selection(self):
        resolved = resolve_bindings(self.resume, self.config)
        self.assertEqual(
            "aminhaiqal15@gmail.com | (+60) 17-667 2587 | Klang, Selangor | linkedin.com/in/amin-haiqal",
            resolved["profile.contactLine"],
        )
        self.assertEqual(
            "Universiti Teknologi Malaysia | Skudai, Johor",
            resolved["education.utm.meta"],
        )
        self.assertEqual(
            self.resume["document"]["sections"][2]["items"][1]["highlights"][1]["text"],
            resolved["project.aria.highlight.2.part1"]
            + " "
            + resolved["project.aria.highlight.2.part2"],
        )

    def test_missing_stable_id_reports_the_binding_tag(self):
        broken = copy.deepcopy(self.config)
        broken["bindings"]["profile.fullName"]["source"] = "candidate-missing.fullName"

        with self.assertRaisesRegex(BindingError, "profile.fullName"):
            resolve_bindings(self.resume, broken)


if __name__ == "__main__":
    unittest.main()
