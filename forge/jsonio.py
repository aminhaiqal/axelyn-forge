import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Union

from .errors import JsonFileError

PathLike = Union[str, Path]


def load_json(path: PathLike) -> Dict[str, Any]:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except OSError as exc:
        raise JsonFileError(f"Could not read JSON file {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise JsonFileError(
            f"Invalid JSON in {source} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(value, dict):
        raise JsonFileError(f"Expected a JSON object in {source}")
    return value


def write_json(path: PathLike, value: Dict[str, Any]) -> Path:
    """Atomically write deterministic, UTF-8 canonical JSON."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary = Path(temp_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, destination)
        temporary = None
    except OSError as exc:
        raise JsonFileError(f"Could not write JSON file {destination}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    return destination
