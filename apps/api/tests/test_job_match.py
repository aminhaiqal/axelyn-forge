import unittest

from axelyn_api.job_match import (
    analyze_job_match,
    draft_to_evidence_text,
    tailor_resume_draft,
)


class JobMatchTests(unittest.TestCase):
    def test_three_match_states_use_stable_score_bands(self):
        resume = (
            "Python platform specialist delivering reliable APIs, PostgreSQL services, "
            "cloud operations, observability, product collaboration, and system performance."
        )
        strong = analyze_job_match(
            target_role="Platform Engineer",
            company=None,
            job_description=resume,
            resume_text=resume,
        )
        partial = analyze_job_match(
            target_role="Platform Engineer",
            company=None,
            job_description=(
                "Python platform specialist delivering reliable APIs, PostgreSQL services, "
                "cloud operations, observability, Kubernetes, Terraform, security, networking, "
                "Golang, and Linux."
            ),
            resume_text=resume,
        )
        none = analyze_job_match(
            target_role="Research Chemist",
            company=None,
            job_description=(
                "Molecular spectroscopy chromatography synthesis laboratory polymers chemical "
                "assays microscopy patents formulations and clinical trials."
            ),
            resume_text=resume,
        )

        self.assertEqual("match", strong.match_state)
        self.assertEqual("some_match", partial.match_state)
        self.assertEqual("no_match", none.match_state)
        self.assertFalse(none.can_generate)

    def test_tailoring_reorders_existing_evidence_without_rewriting_it(self):
        draft = {
            "headline": "Engineer",
            "experience_entries": [
                {
                    "company_name": "Studio",
                    "job_title": "Designer",
                    "responsibilities": "Created visual systems.",
                },
                {
                    "company_name": "Platform Co",
                    "job_title": "Engineer",
                    "responsibilities": "Built Python APIs.",
                },
            ],
            "education_entries": [
                {
                    "institution_name": "Example University",
                    "qualification": "Bachelor of Computer Science",
                    "field_of_study": "Software Engineering",
                    "relevant_coursework": "Python and distributed APIs",
                }
            ],
            "sections": {
                "experience": [
                    "Designer | Studio",
                    "2020 - 2021",
                    "• Created visual systems.",
                    "Engineer | Platform Co",
                    "2022 - Present",
                    "• Built Python APIs.",
                ],
                "skills": ["Figma", "Python and APIs"],
            },
        }

        tailored = tailor_resume_draft(
            draft,
            target_role="Backend Engineer",
            matched_keywords=["python", "apis"],
        )

        self.assertEqual("Backend Engineer", tailored["target_role"])
        self.assertEqual(
            "Platform Co", tailored["experience_entries"][0]["company_name"]
        )
        self.assertEqual("Engineer | Platform Co", tailored["sections"]["experience"][0])
        self.assertEqual("Python and APIs", tailored["sections"]["skills"][0])
        self.assertEqual("Designer | Studio", draft["sections"]["experience"][0])
        self.assertEqual("Studio", draft["experience_entries"][0]["company_name"])
        self.assertIn("Built Python APIs", draft_to_evidence_text(draft))
        self.assertIn("distributed APIs", draft_to_evidence_text(draft))


if __name__ == "__main__":
    unittest.main()
