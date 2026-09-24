from typing import Any, Dict, List, Mapping, Sequence

from .errors import BindingError
from .validation import build_stable_id_index


class BindingResolver:
    """Resolve semantic paths and stable IDs into flat template values."""

    def __init__(self, resume: Dict[str, Any]):
        self.resume = resume
        self.ids = build_stable_id_index(resume)

    def resolve_all(self, config: Mapping[str, Any]) -> Dict[str, str]:
        bindings = config.get("bindings")
        if not isinstance(bindings, dict):
            raise BindingError("Bindings file must contain a 'bindings' object")

        values = {}
        for tag, spec in bindings.items():
            if not isinstance(tag, str) or not tag:
                raise BindingError("Every binding tag must be a non-empty string")
            try:
                values[tag] = self._resolve_spec(spec, tag)
            except BindingError as exc:
                raise BindingError(f"Could not resolve binding '{tag}': {exc}") from exc
        return values

    def _resolve_spec(self, spec: Any, tag: str) -> str:
        if isinstance(spec, str):
            value = self._resolve_source(spec)
            return self._stringify(value, {}, tag)
        if not isinstance(spec, dict):
            raise BindingError("binding must be a source string or object")

        recognized = {"source", "sources", "literal"}
        selected = [key for key in recognized if key in spec]
        if len(selected) != 1:
            raise BindingError("binding must define exactly one of 'source', 'sources', or 'literal'")

        if "literal" in spec:
            literal = spec["literal"]
            if not isinstance(literal, (str, int, float, bool)) and literal is not None:
                raise BindingError("literal must be a scalar value")
            return "" if literal is None else str(literal)

        if "sources" in spec:
            sources = spec["sources"]
            if not isinstance(sources, list) or not sources:
                raise BindingError("'sources' must be a non-empty array")
            separator = spec.get("separator", "")
            if not isinstance(separator, str):
                raise BindingError("'separator' must be a string")
            omit_empty = spec.get("omitEmpty", True)
            rendered = [self._resolve_operand(item, tag) for item in sources]
            if omit_empty:
                rendered = [item for item in rendered if item != ""]
            return separator.join(rendered)

        return self._resolve_operand(spec, tag)

    def _resolve_operand(self, operand: Any, tag: str) -> str:
        if isinstance(operand, str):
            operand = {"source": operand}
        if not isinstance(operand, dict) or not isinstance(operand.get("source"), str):
            raise BindingError("source operand must contain a string 'source'")

        required = operand.get("required", True)
        try:
            value = self._resolve_source(operand["source"])
            if "select" in operand:
                value = self._select(value, operand["select"])
            if "path" in operand:
                path = operand["path"]
                if not isinstance(path, str) or not path:
                    raise BindingError("'path' must be a non-empty string")
                value = self._traverse(value, path.split("."), path)
        except BindingError:
            if required:
                raise
            return ""

        result = self._stringify(value, operand, tag)
        if "split" in operand:
            result = self._split(result, operand["split"])
        prefix = operand.get("stripPrefix")
        if prefix is not None:
            if not isinstance(prefix, str):
                raise BindingError("'stripPrefix' must be a string")
            if result.startswith(prefix):
                result = result[len(prefix) :]
        return result

    @staticmethod
    def _split(value: str, options: Any) -> str:
        if not isinstance(options, dict):
            raise BindingError("'split' must be an object")
        max_chars = options.get("maxChars")
        part = options.get("part")
        if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1:
            raise BindingError("split 'maxChars' must be a positive integer")
        if part not in {"head", "tail"}:
            raise BindingError("split 'part' must be 'head' or 'tail'")

        if len(value) <= max_chars:
            return value if part == "head" else ""

        boundary = value.rfind(" ", 0, max_chars + 1)
        if boundary < 1:
            boundary = max_chars
        if part == "head":
            return value[:boundary].rstrip()
        return value[boundary:].lstrip()

    def _resolve_source(self, source: str) -> Any:
        parts = source.split(".")
        if not all(parts):
            raise BindingError(f"invalid source path '{source}'")

        if parts[0] == "document":
            return self._traverse(self.resume, parts, source)

        stable_id = parts[0]
        if stable_id not in self.ids:
            raise BindingError(f"unknown stable ID '{stable_id}' in source '{source}'")
        return self._traverse(self.ids[stable_id], parts[1:], source)

    @staticmethod
    def _traverse(value: Any, parts: Sequence[str], source: str) -> Any:
        current = value
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                raise BindingError(f"source '{source}' has no field '{part}'")
            current = current[part]
        return current

    @staticmethod
    def _select(value: Any, criteria: Any) -> Any:
        if not isinstance(value, list):
            raise BindingError("'select' can only be used on an array")
        if not isinstance(criteria, dict) or not criteria:
            raise BindingError("'select' must be a non-empty object")
        matches = [
            item
            for item in value
            if isinstance(item, dict) and all(item.get(key) == expected for key, expected in criteria.items())
        ]
        if not matches:
            raise BindingError(f"no array item matched select criteria {criteria!r}")
        if len(matches) > 1:
            raise BindingError(f"multiple array items matched select criteria {criteria!r}")
        return matches[0]

    @staticmethod
    def _stringify(value: Any, options: Mapping[str, Any], tag: str) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            separator = options.get("join")
            if not isinstance(separator, str):
                raise BindingError(f"array source for '{tag}' requires a string 'join'")
            if any(isinstance(item, (dict, list)) for item in value):
                raise BindingError(f"array source for '{tag}' must contain only scalar values")
            return separator.join("" if item is None else str(item) for item in value)
        if isinstance(value, dict):
            raise BindingError(f"object source for '{tag}' requires a scalar field path")
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)


def resolve_bindings(resume: Dict[str, Any], config: Mapping[str, Any]) -> Dict[str, str]:
    return BindingResolver(resume).resolve_all(config)
