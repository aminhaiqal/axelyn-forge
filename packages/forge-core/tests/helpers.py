import json
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "profile.json"
SCHEMA = ROOT / "schemas" / "profile.schema.json"
BINDINGS = ROOT / "bindings" / "software-engineer.json"
COVER_TEMPLATE = ROOT / "templates" / "Amin_Haiqal_Cover_Letter_SDT_Template.docx"
COVER_DATA = ROOT / "data" / "cover_letter.json"
COVER_SCHEMA = ROOT / "schemas" / "cover-letter.schema.json"
COVER_BINDINGS = ROOT / "bindings" / "cover-letter.json"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def _build_resume_test_template(path: Path) -> None:
    tags = list(json.loads(BINDINGS.read_text(encoding="utf-8"))["bindings"])
    document = etree.Element(f"{{{W}}}document", nsmap={"w": W})
    body = etree.SubElement(document, f"{{{W}}}body")
    for tag in tags:
        paragraph = etree.SubElement(body, f"{{{W}}}p")
        paragraph_properties = etree.SubElement(paragraph, f"{{{W}}}pPr")
        etree.SubElement(paragraph_properties, f"{{{W}}}keepNext")
        control = etree.SubElement(paragraph, f"{{{W}}}sdt")
        properties = etree.SubElement(control, f"{{{W}}}sdtPr")
        tag_element = etree.SubElement(properties, f"{{{W}}}tag")
        tag_element.set(f"{{{W}}}val", tag)
        content = etree.SubElement(control, f"{{{W}}}sdtContent")
        run = etree.SubElement(content, f"{{{W}}}r")
        run_properties = etree.SubElement(run, f"{{{W}}}rPr")
        etree.SubElement(run_properties, f"{{{W}}}b")
        text = etree.SubElement(run, f"{{{W}}}t")
        text.text = f"fixture:{tag}"

    document_xml = etree.tostring(
        document,
        encoding="UTF-8",
        xml_declaration=True,
    )
    content_types = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document_xml)


_RESUME_TEMPLATE_DIRECTORY = tempfile.TemporaryDirectory()
TEMPLATE = Path(_RESUME_TEMPLATE_DIRECTORY.name) / "resume-test-template.docx"
_build_resume_test_template(TEMPLATE)


def document_tree(path: Path):
    with zipfile.ZipFile(path) as archive:
        return etree.fromstring(archive.read("word/document.xml"))


def formatting_signature(path: Path, tag: str):
    root = document_tree(path)
    candidates = root.xpath(
        ".//w:sdt[w:sdtPr/w:tag[@w:val=$tag]]",
        namespaces=NS,
        tag=tag,
    )
    if not candidates:
        raise AssertionError(f"No content control with tag {tag}")
    sdt = candidates[0]
    paragraph = next(sdt.iterancestors(f"{{{W}}}p"), None)
    paragraph_properties = paragraph.find(f"{{{W}}}pPr") if paragraph is not None else None
    run_properties = sdt.xpath("./w:sdtContent//w:rPr", namespaces=NS)

    def canonical(element):
        if element is None:
            return None
        return etree.tostring(element, method="c14n")

    return canonical(paragraph_properties), tuple(canonical(item) for item in run_properties)
