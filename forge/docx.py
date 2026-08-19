import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from lxml import etree

from .errors import DocxError, MissingTemplateBindingError

PathLike = Union[str, Path]
WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
NAMESPACES = {"w": WORD_NAMESPACE}
W_SDT = f"{{{WORD_NAMESPACE}}}sdt"
W_SDT_CONTENT = f"{{{WORD_NAMESPACE}}}sdtContent"
W_TAG = f"{{{WORD_NAMESPACE}}}tag"
W_TEXT = f"{{{WORD_NAMESPACE}}}t"
W_VAL = f"{{{WORD_NAMESPACE}}}val"
XML_SPACE = f"{{{XML_NAMESPACE}}}space"


@dataclass(frozen=True)
class ContentControl:
    tag: str
    current_text: str
    part: str
    occurrence: int

    def as_dict(self) -> Dict[str, object]:
        return {
            "tag": self.tag,
            "currentText": self.current_text,
            "part": self.part,
            "occurrence": self.occurrence,
        }


@dataclass(frozen=True)
class RenderReport:
    output: Path
    controls: int
    changed_controls: int
    unchanged_controls: int
    changed_parts: Tuple[str, ...]
    unused_values: Tuple[str, ...]


@dataclass
class _ParsedControl:
    tag: str
    element: etree._Element
    texts: List[etree._Element]

    @property
    def current_text(self) -> str:
        return "".join(text.text or "" for text in self.texts)


def _xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        remove_blank_text=False,
        huge_tree=False,
    )


def _is_word_xml_part(name: str) -> bool:
    return name.startswith("word/") and name.endswith(".xml")


def _owned_text_nodes(sdt: etree._Element) -> List[etree._Element]:
    content = sdt.find(W_SDT_CONTENT)
    if content is None:
        return []

    owned = []
    for text in content.iter(W_TEXT):
        nearest_sdt = next(text.iterancestors(W_SDT), None)
        if nearest_sdt is sdt:
            owned.append(text)
    return owned


def _parse_controls(xml: bytes, part: str) -> Tuple[etree._ElementTree, List[_ParsedControl]]:
    try:
        tree = etree.parse(BytesIO(xml), _xml_parser())
    except etree.XMLSyntaxError as exc:
        raise DocxError(f"Invalid WordprocessingML in {part}: {exc}") from exc

    controls = []
    for sdt in tree.getroot().iter(W_SDT):
        tag_nodes = sdt.xpath("./w:sdtPr/w:tag", namespaces=NAMESPACES)
        if not tag_nodes:
            continue
        tag = tag_nodes[0].get(W_VAL)
        if not tag:
            continue
        controls.append(_ParsedControl(tag=tag, element=sdt, texts=_owned_text_nodes(sdt)))
    return tree, controls


def _read_archive(path: Path) -> Tuple[List[zipfile.ZipInfo], Dict[str, bytes], bytes]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise DocxError(f"Corrupt DOCX ZIP member: {bad_member}")
            infos = archive.infolist()
            payloads = {info.filename: archive.read(info.filename) for info in infos}
            comment = archive.comment
    except FileNotFoundError as exc:
        raise DocxError(f"DOCX file does not exist: {path}") from exc
    except zipfile.BadZipFile as exc:
        raise DocxError(f"Not a valid DOCX ZIP archive: {path}") from exc
    except OSError as exc:
        raise DocxError(f"Could not read DOCX file {path}: {exc}") from exc

    required = {"[Content_Types].xml", "word/document.xml"}
    missing = sorted(required.difference(payloads))
    if missing:
        raise DocxError(f"DOCX archive is missing required part(s): {', '.join(missing)}")
    return infos, payloads, comment


def inspect_docx(path: PathLike) -> List[ContentControl]:
    """Return every tagged SDT discovered in all Word XML parts."""
    source = Path(path)
    _, payloads, _ = _read_archive(source)
    discovered = []
    occurrences: Dict[str, int] = {}

    for part, payload in payloads.items():
        if not _is_word_xml_part(part):
            continue
        _, controls = _parse_controls(payload, part)
        for control in controls:
            occurrences[control.tag] = occurrences.get(control.tag, 0) + 1
            discovered.append(
                ContentControl(
                    tag=control.tag,
                    current_text=control.current_text,
                    part=part,
                    occurrence=occurrences[control.tag],
                )
            )
    return discovered


def _replace_text(control: _ParsedControl, value: str) -> bool:
    if control.current_text == value:
        return False
    if not control.texts:
        raise DocxError(f"Content control '{control.tag}' contains no w:t text node")

    first, *remaining = control.texts
    first.text = value or None
    if value[:1].isspace() or value[-1:].isspace():
        first.set(XML_SPACE, "preserve")
    for text in remaining:
        text.text = None
    return True


def _serialize_tree(tree: etree._ElementTree) -> bytes:
    standalone = tree.docinfo.standalone
    return etree.tostring(
        tree,
        encoding="UTF-8",
        xml_declaration=True,
        standalone=standalone,
    )


def _write_archive(
    target: Path,
    infos: Sequence[zipfile.ZipInfo],
    payloads: Mapping[str, bytes],
    comment: bytes,
) -> None:
    with zipfile.ZipFile(target, "w") as archive:
        archive.comment = comment
        for info in infos:
            archive.writestr(info, payloads[info.filename])


def validate_docx_archive(path: PathLike) -> None:
    """Check ZIP integrity and required core DOCX parts."""
    _read_archive(Path(path))


def render_docx(
    template: PathLike,
    output: PathLike,
    values: Mapping[str, str],
    *,
    strict: bool = True,
) -> RenderReport:
    """Render flat tag values into a new DOCX without rebuilding Word layout."""
    source = Path(template)
    destination = Path(output)
    try:
        if source.resolve() == destination.resolve():
            raise DocxError("Refusing to overwrite the source template in place")
    except OSError as exc:
        raise DocxError(f"Could not resolve DOCX path: {exc}") from exc

    invalid_values = sorted(
        repr(tag)
        for tag, value in values.items()
        if not isinstance(tag, str) or not isinstance(value, str)
    )
    if invalid_values:
        raise DocxError(f"Resolved DOCX values must be strings: {', '.join(invalid_values)}")

    infos, payloads, comment = _read_archive(source)
    parsed_parts: Dict[str, Tuple[etree._ElementTree, List[_ParsedControl]]] = {}
    all_tags = []
    total_controls = 0
    for part, payload in payloads.items():
        if not _is_word_xml_part(part):
            continue
        tree, controls = _parse_controls(payload, part)
        if controls:
            parsed_parts[part] = (tree, controls)
            all_tags.extend(control.tag for control in controls)
            total_controls += len(controls)

    unbound = sorted(set(all_tags).difference(values))
    if strict and unbound:
        raise MissingTemplateBindingError(unbound)

    changed_controls = 0
    unchanged_controls = 0
    changed_parts = []
    for part, (tree, controls) in parsed_parts.items():
        part_changed = False
        for control in controls:
            if control.tag not in values:
                unchanged_controls += 1
                continue
            if _replace_text(control, values[control.tag]):
                changed_controls += 1
                part_changed = True
            else:
                unchanged_controls += 1
        if part_changed:
            payloads[part] = _serialize_tree(tree)
            changed_parts.append(part)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        os.close(descriptor)
        temporary = Path(temp_name)
        if changed_parts:
            _write_archive(temporary, infos, payloads, comment)
        else:
            shutil.copyfile(source, temporary)
        validate_docx_archive(temporary)
        os.replace(temporary, destination)
        temporary = None
    except OSError as exc:
        raise DocxError(f"Could not write rendered DOCX {destination}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    unused = tuple(sorted(set(values).difference(all_tags)))
    return RenderReport(
        output=destination,
        controls=total_controls,
        changed_controls=changed_controls,
        unchanged_controls=unchanged_controls,
        changed_parts=tuple(changed_parts),
        unused_values=unused,
    )
