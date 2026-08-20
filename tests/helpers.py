import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "Amin_Haiqal_Resume_Forge_SDT_Template.docx"
DATA = ROOT / "data" / "profile.json"
SCHEMA = ROOT / "schemas" / "profile.schema.json"
BINDINGS = ROOT / "bindings" / "software-engineer.json"
COVER_TEMPLATE = ROOT / "templates" / "Amin_Haiqal_Cover_Letter_SDT_Template.docx"
COVER_DATA = ROOT / "data" / "cover_letter.json"
COVER_SCHEMA = ROOT / "schemas" / "cover-letter.schema.json"
COVER_BINDINGS = ROOT / "bindings" / "cover-letter.json"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


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
