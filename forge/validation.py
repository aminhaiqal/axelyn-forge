from typing import Any, Dict, Iterable, Tuple

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .errors import DuplicateResumeIdError, ResumeValidationError


def _path_key(error) -> Tuple[str, ...]:
    return tuple(str(part) for part in error.absolute_path)


def _display_path(parts: Iterable[Any]) -> str:
    result = "$"
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}"
    return result


def _collect_ids(value: Any, path: Tuple[Any, ...] = (), seen=None) -> Dict[str, Any]:
    if seen is None:
        seen = {}

    if isinstance(value, dict):
        stable_id = value.get("id")
        if isinstance(stable_id, str):
            if stable_id in seen:
                first_path = _display_path(seen[stable_id][0])
                second_path = _display_path(path)
                raise DuplicateResumeIdError(
                    f"Duplicate stable ID '{stable_id}' at {second_path}; first defined at {first_path}"
                )
            seen[stable_id] = (path, value)
        for key, child in value.items():
            _collect_ids(child, path + (key,), seen)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_ids(child, path + (index,), seen)
    return {stable_id: item[1] for stable_id, item in seen.items()}


def build_stable_id_index(resume: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Index every canonical entity with an ID, rejecting ambiguous duplicates."""
    return _collect_ids(resume)


def validate_resume(resume: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Validate a canonical resume and its global stable-ID invariant."""
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ResumeValidationError(f"Resume schema is invalid: {exc.message}") from exc

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(resume), key=_path_key)
    if errors:
        formatted = []
        for error in errors:
            path = _display_path(error.absolute_path)
            formatted.append(f"- {path}: {error.message}")
        raise ResumeValidationError("Resume validation failed:\n" + "\n".join(formatted))

    build_stable_id_index(resume)
