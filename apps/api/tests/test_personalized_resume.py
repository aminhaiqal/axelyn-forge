import copy
import json
import unittest
import zipfile
from io import BytesIO
from types import SimpleNamespace

from jsonschema import Draft202012Validator, ValidationError

from axelyn_api.personalized_resume import (
    build_personalized_resume_bundle,
    inspect_docx_nodes,
    plan_resume_template_with_openrouter,
    render_personalized_resume,
)


def source_docx() -> bytes:
    content_types = b"""<?xml version="1.0" encoding="UTF-8"?>
    <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
      <Default Extension="xml" ContentType="application/xml"/>
    </Types>"""
    document = b"""<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>Taylor Example</w:t></w:r></w:p>
        <w:p><w:r><w:t>Backend Engineer</w:t></w:r></w:p>
        <w:p><w:r><w:t>Experience</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc>
          <w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>Built production APIs.</w:t></w:r></w:p>
        </w:tc></w:tr></w:tbl>
      </w:body>
    </w:document>"""
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


class FakeResponses:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.payload))


class PersonalizedResumeTests(unittest.TestCase):
    def test_builds_per_document_schema_and_preserves_source_layout(self):
        payload = source_docx()

        def planner(**kwargs):
            self.assertEqual("Taylor Example", kwargs["nodes"][0]["text"])
            self.assertTrue(kwargs["nodes"][3]["in_table"])
            return [
                {
                    "node_id": "p0000",
                    "json_pointer": "/profile/full_name",
                    "title": "Full name",
                    "description": "Candidate name",
                },
                {
                    "node_id": "p0001",
                    "json_pointer": "/profile/headline",
                    "title": "Headline",
                    "description": "Candidate headline",
                },
                {
                    "node_id": "p0003",
                    "json_pointer": "/experience/0/highlights/0",
                    "title": "Experience highlight",
                    "description": "First role highlight",
                },
            ]

        bundle = build_personalized_resume_bundle(
            source_docx=payload,
            display_name="Taylor resume",
            planner=planner,
        )
        example = json.loads(bundle.example_json)
        schema = json.loads(bundle.schema_json)
        manifest = json.loads(bundle.manifest_json)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(example)
        self.assertEqual("Taylor Example", example["profile"]["full_name"])
        self.assertEqual(
            "Built production APIs.",
            example["experience"][0]["highlights"][0],
        )
        self.assertEqual("json-pointer-sdt-v1", manifest["engine"])

        with zipfile.ZipFile(BytesIO(bundle.template_docx)) as archive:
            xml = archive.read("word/document.xml")
        self.assertEqual(3, xml.count(b"<w:sdt>"))
        self.assertIn(b'<w:jc w:val="center"/>', xml)
        self.assertIn(b"<w:tbl>", xml)
        self.assertIn(b"<w:b/>", xml)

    def test_round_trip_updates_bound_sdts_and_validates_json(self):
        bundle = build_personalized_resume_bundle(
            source_docx=source_docx(),
            display_name="Taylor resume",
        )
        example = json.loads(bundle.example_json)
        schema = json.loads(bundle.schema_json)
        manifest = json.loads(bundle.manifest_json)
        changed = copy.deepcopy(example)
        changed["profile"]["full_name"] = "Jordan Example"
        changed["sections"]["experience"][0] = "Created reliable services."

        rendered = render_personalized_resume(
            template_docx=bundle.template_docx,
            data=changed,
            schema=schema,
            manifest=manifest,
        )
        with zipfile.ZipFile(BytesIO(rendered)) as archive:
            xml = archive.read("word/document.xml")
        self.assertIn(b"Jordan Example", xml)
        self.assertIn(b"Created reliable services.", xml)
        self.assertIn(b'<w:jc w:val="center"/>', xml)
        self.assertIn(b"<w:tbl>", xml)

        invalid = copy.deepcopy(example)
        invalid["unexpected"] = "not allowed"
        with self.assertRaises(ValidationError):
            render_personalized_resume(
                template_docx=bundle.template_docx,
                data=invalid,
                schema=schema,
                manifest=manifest,
            )

    def test_openrouter_plan_uses_strict_private_schema(self):
        nodes = inspect_docx_nodes(source_docx())
        responses = FakeResponses(
            {
                "bindings": [
                    {
                        "node_id": "p0000",
                        "json_pointer": "/profile/full_name",
                        "title": "Full name",
                        "description": "Candidate name",
                    }
                ]
            }
        )
        result = plan_resume_template_with_openrouter(
            nodes=nodes,
            display_name="resume",
            client=SimpleNamespace(responses=responses),
            model="openai/gpt-test",
        )

        self.assertEqual("/profile/full_name", result[0]["json_pointer"])
        call = responses.calls[0]
        self.assertTrue(call["text"]["format"]["strict"])
        self.assertFalse(call["store"])
        self.assertTrue(call["extra_body"]["provider"]["zdr"])
        self.assertIn("documentNodes", json.loads(call["input"]))


if __name__ == "__main__":
    unittest.main()
