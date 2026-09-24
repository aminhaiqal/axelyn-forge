import unittest

from forge.context_selection import parse_markdown_context
from forge.jsonio import load_json
from forge.keyword_alignment import (
    JobKeyword,
    align_job_keywords,
    remove_noop_operations,
)
from forge.openai_provider import build_editable_targets

from .helpers import DATA


class KeywordAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.resume = load_json(DATA)

    def test_matches_exact_alias_context_and_unsupported_keywords(self):
        chunks = parse_markdown_context(
            "# AI Engineer\nVerified Qwen fine-tuning experiment.",
            source="candidate.md",
        )
        keywords = [
            JobKeyword("Python", "required", "technology"),
            JobKeyword("AI Agents", "required", "architecture"),
            JobKeyword("Retrieval-Augmented Generation", "preferred", "architecture"),
            JobKeyword("Qwen", "preferred", "technology"),
            JobKeyword("Node.js", "required", "technology"),
        ]

        alignment = align_job_keywords(
            resume=self.resume,
            keywords=keywords,
            selected_chunks=chunks,
        )

        statuses = {
            match.keyword.phrase: match.status for match in alignment.matches
        }
        self.assertEqual("supported-exact", statuses["Python"])
        self.assertEqual("supported-alias", statuses["AI Agents"])
        self.assertEqual(
            "supported-alias", statuses["Retrieval-Augmented Generation"]
        )
        self.assertEqual("supported-context", statuses["Qwen"])
        self.assertEqual("unsupported", statuses["Node.js"])
        self.assertEqual(
            ["Python", "AI Agents", "Retrieval-Augmented Generation", "Qwen"],
            [match.keyword.phrase for match in alignment.must_surface],
        )

    def test_audit_measures_employer_terms_in_resolved_word_values(self):
        keywords = [
            JobKeyword("RAG", "required", "architecture"),
            JobKeyword("AI Agents", "required", "architecture"),
            JobKeyword("Node.js", "required", "technology"),
        ]
        alignment = align_job_keywords(resume=self.resume, keywords=keywords)

        audit = alignment.build_audit(
            before_values={"summary.text": "Python and RAG systems"},
            after_values={
                "summary.text": "Python, RAG, and AI Agent systems",
                "project.aria.highlight.1": "Built an AI Agent with RAG",
            },
            no_op_targets=("skills-ai.items",),
        )

        coverage = audit["coverage"]
        self.assertEqual(2, coverage["targetedKeywords"])
        self.assertEqual(1, coverage["surfacedBefore"])
        self.assertEqual(2, coverage["surfacedAfter"])
        self.assertEqual(100.0, coverage["percentage"])
        self.assertEqual(["Summary", "Projects"], coverage["changedSections"])
        self.assertEqual(["skills-ai.items"], audit["noOpOperationsRemoved"])

    def test_noop_operations_are_removed_before_rendering(self):
        targets = build_editable_targets(self.resume)
        current = {
            (target["target"], target["field"]): target["currentValue"]
            for target in targets
        }
        operations = [
            {
                "operation": "rewrite",
                "target": "summary-1",
                "field": None,
                "value": current[("summary-1", None)],
            },
            {
                "operation": "rewrite",
                "target": "document.profile.headline",
                "field": None,
                "value": "AI Software Engineer | Python, RAG & APIs",
            },
        ]

        kept, removed = remove_noop_operations(operations, targets)

        self.assertEqual(1, len(kept))
        self.assertEqual("document.profile.headline", kept[0]["target"])
        self.assertEqual(("summary-1",), removed)


if __name__ == "__main__":
    unittest.main()
