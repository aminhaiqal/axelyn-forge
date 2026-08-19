from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

from .bindings import resolve_bindings
from .docx import ContentControl, RenderReport, inspect_docx, render_docx
from .jsonio import load_json
from .jsonio import write_json
from .operations import OperationReport, apply_operations
from .validation import validate_resume

PathLike = Union[str, Path]


@dataclass(frozen=True)
class ForgeRenderResult:
    report: RenderReport
    resolved_values: int


def validate_resume_file(data: PathLike, schema: PathLike) -> None:
    resume = load_json(data)
    resume_schema = load_json(schema)
    validate_resume(resume, resume_schema)


def inspect_template(template: PathLike) -> List[ContentControl]:
    return inspect_docx(template)


def apply_resume_operations_file(
    *,
    data: PathLike,
    schema: PathLike,
    operations: PathLike,
    output: PathLike,
) -> OperationReport:
    source = Path(data)
    destination = Path(output)
    if source.resolve() == destination.resolve():
        from .errors import OperationError

        raise OperationError("Refusing to overwrite the master resume JSON in place")

    resume = load_json(source)
    resume_schema = load_json(schema)
    operation_config = load_json(operations)
    validate_resume(resume, resume_schema)
    tailored, targets = apply_operations(resume, operation_config)
    validate_resume(tailored, resume_schema)
    written = write_json(destination, tailored)
    return OperationReport(output=written, applied_operations=len(targets), targets=targets)


def render_resume(
    *,
    template: PathLike,
    data: PathLike,
    schema: PathLike,
    bindings: PathLike,
    output: PathLike,
    strict: bool = True,
) -> ForgeRenderResult:
    """Validate, bind, and render a canonical resume into a copied DOCX."""
    resume = load_json(data)
    resume_schema = load_json(schema)
    binding_config = load_json(bindings)

    # This always happens before the template archive is opened for rendering.
    validate_resume(resume, resume_schema)
    values = resolve_bindings(resume, binding_config)
    report = render_docx(template, output, values, strict=strict)
    return ForgeRenderResult(report=report, resolved_values=len(values))
