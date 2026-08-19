import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Sequence, Tuple

from .errors import OperationError
from .validation import build_stable_id_index


@dataclass(frozen=True)
class OperationReport:
    output: Path
    applied_operations: int
    targets: Tuple[str, ...]


def _existing_parent(root: MutableMapping[str, Any], parts: Sequence[str], target: str):
    if not parts:
        raise OperationError(f"Target '{target}' does not identify a field")
    current: Any = root
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise OperationError(f"Target '{target}' has no field '{part}'")
        current = current[part]
    field = parts[-1]
    if not isinstance(current, dict) or field not in current:
        raise OperationError(f"Target '{target}' has no field '{field}'")
    return current, field


def apply_operations(resume: Dict[str, Any], config: Mapping[str, Any]) -> Tuple[Dict[str, Any], Tuple[str, ...]]:
    """Apply AI-authored content rewrites to canonical fields, never to DOCX XML."""
    operations = config.get("operations")
    if not isinstance(operations, list) or not operations:
        raise OperationError("Operations file must contain a non-empty 'operations' array")

    result = copy.deepcopy(resume)
    applied_targets = []
    for index, operation in enumerate(operations):
        label = f"operation {index + 1}"
        if not isinstance(operation, dict):
            raise OperationError(f"{label} must be an object")
        if operation.get("operation") != "rewrite":
            raise OperationError(f"{label} uses unsupported operation {operation.get('operation')!r}")
        target = operation.get("target")
        if not isinstance(target, str) or not target:
            raise OperationError(f"{label} must contain a non-empty string 'target'")
        if "value" not in operation:
            raise OperationError(f"{label} must contain 'value'")

        if target == "document" or target.startswith("document."):
            if operation.get("field") is not None:
                raise OperationError(f"{label} cannot combine an absolute target with 'field'")
            parent, field = _existing_parent(result, target.split("."), target)
        else:
            stable_ids = build_stable_id_index(result)
            if target not in stable_ids:
                raise OperationError(f"{label} references unknown stable ID '{target}'")
            entity = stable_ids[target]
            field_path = operation.get("field")
            if field_path is None:
                if "text" not in entity:
                    raise OperationError(
                        f"{label} target '{target}' requires 'field' because it has no default text field"
                    )
                field_path = "text"
            if not isinstance(field_path, str) or not field_path:
                raise OperationError(f"{label} 'field' must be a non-empty string")
            parent, field = _existing_parent(entity, field_path.split("."), f"{target}.{field_path}")

        parent[field] = copy.deepcopy(operation["value"])
        applied_targets.append(target)

    return result, tuple(applied_targets)
