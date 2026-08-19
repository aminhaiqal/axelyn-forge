"""SQLite ledger for OpenAI request usage and public-price cost estimates."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from .errors import UsageStoreError

PathLike = Union[str, Path]
LLM_USAGE_SCHEMA_VERSION = "2"
OPENAI_PRICING_EFFECTIVE_FROM = "2026-07-30"
OPENAI_PRICING_SOURCE = "https://developers.openai.com/api/docs/models/compare"
OPENAI_TOOL_PRICING_EFFECTIVE_FROM = "2026-08-19"
OPENAI_TOOL_PRICING_SOURCE = "https://developers.openai.com/api/docs/pricing#built-in-tools"
OPENAI_WEB_SEARCH_USD_PER_1000 = 10.0
LONG_CONTEXT_THRESHOLD = 272_000

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS llm_usage_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_pricing (
    pricing_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    service_tier TEXT NOT NULL,
    context_band TEXT NOT NULL CHECK (context_band IN ('short', 'long')),
    effective_from TEXT NOT NULL,
    input_usd_per_million REAL NOT NULL CHECK (input_usd_per_million >= 0),
    cached_input_usd_per_million REAL NOT NULL CHECK (cached_input_usd_per_million >= 0),
    cache_write_usd_per_million REAL NOT NULL CHECK (cache_write_usd_per_million >= 0),
    output_usd_per_million REAL NOT NULL CHECK (output_usd_per_million >= 0),
    source_url TEXT NOT NULL,
    UNIQUE (provider, model, service_tier, context_band, effective_from)
);

CREATE TABLE IF NOT EXISTS llm_tool_pricing (
    tool_pricing_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    tool TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    usd_per_1000_calls REAL NOT NULL CHECK (usd_per_1000_calls >= 0),
    source_url TEXT NOT NULL,
    UNIQUE (provider, tool, effective_from)
);

CREATE TABLE IF NOT EXISTS llm_requests (
    request_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    request_kind TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    requested_model TEXT NOT NULL,
    actual_model TEXT,
    requested_service_tier TEXT NOT NULL,
    actual_service_tier TEXT,
    response_id TEXT,
    response_status TEXT,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    ordinary_input_tokens INTEGER CHECK (
        ordinary_input_tokens IS NULL OR ordinary_input_tokens >= 0
    ),
    cached_input_tokens INTEGER CHECK (
        cached_input_tokens IS NULL OR cached_input_tokens >= 0
    ),
    cache_write_tokens INTEGER CHECK (cache_write_tokens IS NULL OR cache_write_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    reasoning_tokens INTEGER CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
    total_tokens INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
    pricing_id INTEGER,
    pricing_model TEXT,
    pricing_context_band TEXT,
    input_usd_per_million REAL,
    cached_input_usd_per_million REAL,
    cache_write_usd_per_million REAL,
    output_usd_per_million REAL,
    ordinary_input_cost_usd REAL,
    cached_input_cost_usd REAL,
    cache_write_cost_usd REAL,
    output_cost_usd REAL,
    token_cost_usd REAL,
    web_search_calls INTEGER CHECK (web_search_calls IS NULL OR web_search_calls >= 0),
    web_search_usd_per_1000 REAL,
    web_search_cost_usd REAL,
    tool_pricing_source_url TEXT,
    estimated_cost_usd REAL,
    cost_status TEXT NOT NULL,
    pricing_source_url TEXT,
    error_type TEXT,
    error_message TEXT,
    FOREIGN KEY (pricing_id) REFERENCES llm_pricing(pricing_id)
);

CREATE INDEX IF NOT EXISTS llm_requests_workflow_idx
ON llm_requests(workflow_id, started_at);

CREATE INDEX IF NOT EXISTS llm_requests_started_idx
ON llm_requests(started_at);

CREATE INDEX IF NOT EXISTS llm_requests_kind_idx
ON llm_requests(request_kind, started_at);
"""


# Standard-service public list prices per 1M tokens. Long-context rates apply
# to the full request when input_tokens exceeds 272K.
_OPENAI_PRICING: Tuple[Tuple[Any, ...], ...] = (
    ("gpt-5.6-sol", "short", 5.0, 0.5, 6.25, 30.0),
    ("gpt-5.6-sol", "long", 10.0, 1.0, 12.5, 45.0),
    ("gpt-5.6-terra", "short", 2.0, 0.2, 2.5, 12.0),
    ("gpt-5.6-terra", "long", 4.0, 0.4, 5.0, 18.0),
    ("gpt-5.6-luna", "short", 0.2, 0.02, 0.25, 1.2),
    ("gpt-5.6-luna", "long", 0.4, 0.04, 0.5, 1.8),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _optional_token_count(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _canonical_pricing_model(model: Optional[str]) -> Optional[str]:
    if not model:
        return None
    if model == "gpt-5.6":
        return "gpt-5.6-sol"
    for candidate in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        if model == candidate or model.startswith(f"{candidate}-"):
            return candidate
    return None


def _cost(tokens: int, rate: float) -> float:
    value = Decimal(tokens) * Decimal(str(rate)) / Decimal(1_000_000)
    return float(value.quantize(Decimal("0.000000000001")))


def _count_web_search_calls(response: Any) -> int:
    count = 0
    for item in _field(response, "output", []) or []:
        if _field(item, "type") != "web_search_call":
            continue
        action = _field(item, "action", {})
        if _field(action, "type") == "search":
            count += 1
    return count


class OpenAIUsageStore:
    """Persist one ledger row for each logical OpenAI Responses API call."""

    def __init__(self, database: PathLike):
        self.database = Path(database)

    def _connect(self, *, create: bool) -> sqlite3.Connection:
        if not create and not self.database.is_file():
            raise UsageStoreError(f"Usage database does not exist: {self.database}")
        if self.database.exists() and not self.database.is_file():
            raise UsageStoreError(f"Usage database path is not a file: {self.database}")
        try:
            if create:
                self.database.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.database), timeout=10)
        except (OSError, sqlite3.Error) as exc:
            raise UsageStoreError(f"Could not open usage database {self.database}: {exc}") from exc
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            "INSERT OR IGNORE INTO llm_usage_meta(key, value) VALUES (?, ?)",
            ("schema_version", LLM_USAGE_SCHEMA_VERSION),
        )
        row = connection.execute(
            "SELECT value FROM llm_usage_meta WHERE key = ?", ("schema_version",)
        ).fetchone()
        if row is not None and row["value"] == "1":
            OpenAIUsageStore._migrate_v1_to_v2(connection)
            row = connection.execute(
                "SELECT value FROM llm_usage_meta WHERE key = ?", ("schema_version",)
            ).fetchone()
        if row is None or row["value"] != LLM_USAGE_SCHEMA_VERSION:
            actual = None if row is None else row["value"]
            raise UsageStoreError(
                f"Unsupported LLM usage schema version {actual!r}; "
                f"expected {LLM_USAGE_SCHEMA_VERSION}"
            )
        connection.executemany(
            """
            INSERT OR IGNORE INTO llm_pricing(
                provider,
                model,
                service_tier,
                context_band,
                effective_from,
                input_usd_per_million,
                cached_input_usd_per_million,
                cache_write_usd_per_million,
                output_usd_per_million,
                source_url
            ) VALUES ('openai', ?, 'default', ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    model,
                    context_band,
                    OPENAI_PRICING_EFFECTIVE_FROM,
                    input_rate,
                    cached_rate,
                    cache_write_rate,
                    output_rate,
                    OPENAI_PRICING_SOURCE,
                )
                for (
                    model,
                    context_band,
                    input_rate,
                    cached_rate,
                    cache_write_rate,
                    output_rate,
                ) in _OPENAI_PRICING
            ],
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO llm_tool_pricing(
                provider,
                tool,
                effective_from,
                usd_per_1000_calls,
                source_url
            ) VALUES ('openai', 'web_search', ?, ?, ?)
            """,
            (
                OPENAI_TOOL_PRICING_EFFECTIVE_FROM,
                OPENAI_WEB_SEARCH_USD_PER_1000,
                OPENAI_TOOL_PRICING_SOURCE,
            ),
        )

    @staticmethod
    def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(llm_requests)")
        }
        additions = (
            ("token_cost_usd", "REAL"),
            (
                "web_search_calls",
                "INTEGER CHECK (web_search_calls IS NULL OR web_search_calls >= 0)",
            ),
            ("web_search_usd_per_1000", "REAL"),
            ("web_search_cost_usd", "REAL"),
            ("tool_pricing_source_url", "TEXT"),
        )
        for name, declaration in additions:
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE llm_requests ADD COLUMN {name} {declaration}"
                )
        connection.execute(
            """
            UPDATE llm_requests
            SET token_cost_usd = estimated_cost_usd,
                web_search_calls = 0,
                web_search_cost_usd = 0.0
            WHERE token_cost_usd IS NULL
            """
        )
        connection.execute(
            "UPDATE llm_usage_meta SET value = ? WHERE key = 'schema_version'",
            (LLM_USAGE_SCHEMA_VERSION,),
        )

    def initialize(self) -> None:
        connection = self._connect(create=True)
        try:
            with connection:
                self._initialize(connection)
        except sqlite3.Error as exc:
            raise UsageStoreError(
                f"Could not initialize usage database {self.database}: {exc}"
            ) from exc
        finally:
            connection.close()

    def start_request(
        self,
        *,
        workflow_id: str,
        request_kind: str,
        requested_model: str,
        requested_service_tier: str = "default",
    ) -> str:
        request_id = str(uuid.uuid4())
        connection = self._connect(create=True)
        try:
            with connection:
                self._initialize(connection)
                connection.execute(
                    """
                    INSERT INTO llm_requests(
                        request_id,
                        workflow_id,
                        provider,
                        request_kind,
                        endpoint,
                        requested_model,
                        requested_service_tier,
                        status,
                        started_at,
                        cost_status
                    ) VALUES (?, ?, 'openai', ?, 'responses', ?, ?, 'started', ?, 'pending')
                    """,
                    (
                        request_id,
                        workflow_id,
                        request_kind,
                        requested_model,
                        requested_service_tier,
                        _utc_now().isoformat(),
                    ),
                )
        except sqlite3.Error as exc:
            raise UsageStoreError(
                f"Could not start usage record in {self.database}: {exc}"
            ) from exc
        finally:
            connection.close()
        return request_id

    @staticmethod
    def _duration_ms(started_at: str, completed_at: datetime) -> int:
        try:
            started = datetime.fromisoformat(started_at)
        except ValueError:
            return 0
        return max(0, round((completed_at - started).total_seconds() * 1000))

    @staticmethod
    def _pricing_row(
        connection: sqlite3.Connection,
        *,
        model: Optional[str],
        service_tier: Optional[str],
        input_tokens: int,
    ) -> Optional[sqlite3.Row]:
        pricing_model = _canonical_pricing_model(model)
        if pricing_model is None or service_tier != "default":
            return None
        context_band = "long" if input_tokens > LONG_CONTEXT_THRESHOLD else "short"
        return connection.execute(
            """
            SELECT *
            FROM llm_pricing
            WHERE provider = 'openai'
              AND model = ?
              AND service_tier = ?
              AND context_band = ?
              AND effective_from <= ?
            ORDER BY effective_from DESC
            LIMIT 1
            """,
            (pricing_model, service_tier, context_band, _utc_now().date().isoformat()),
        ).fetchone()

    @staticmethod
    def _tool_pricing_row(
        connection: sqlite3.Connection, *, tool: str
    ) -> Optional[sqlite3.Row]:
        return connection.execute(
            """
            SELECT *
            FROM llm_tool_pricing
            WHERE provider = 'openai'
              AND tool = ?
              AND effective_from <= ?
            ORDER BY effective_from DESC
            LIMIT 1
            """,
            (tool, _utc_now().date().isoformat()),
        ).fetchone()

    def complete_request(self, request_id: str, response: Any) -> None:
        completed_at = _utc_now()
        usage = _field(response, "usage")
        actual_model = _field(response, "model")
        actual_service_tier = _field(response, "service_tier") or "default"
        response_id = _field(response, "id")
        response_status = _field(response, "status")
        web_search_calls = _count_web_search_calls(response)

        input_tokens = _optional_token_count(_field(usage, "input_tokens"))
        output_tokens = _optional_token_count(_field(usage, "output_tokens"))
        total_tokens = _optional_token_count(_field(usage, "total_tokens"))
        input_details = _field(usage, "input_tokens_details", {})
        output_details = _field(usage, "output_tokens_details", {})
        cached_tokens = _optional_token_count(_field(input_details, "cached_tokens"))
        cache_write_tokens = _optional_token_count(
            _field(input_details, "cache_write_tokens")
        )
        reasoning_tokens = _optional_token_count(
            _field(output_details, "reasoning_tokens")
        )

        connection = self._connect(create=False)
        try:
            with connection:
                self._initialize(connection)
                started_row = connection.execute(
                    """
                    SELECT started_at, requested_model, requested_service_tier
                    FROM llm_requests
                    WHERE request_id = ?
                    """,
                    (request_id,),
                ).fetchone()
                if started_row is None:
                    raise UsageStoreError(f"Unknown LLM usage request ID: {request_id}")

                duration_ms = self._duration_ms(started_row["started_at"], completed_at)
                cost_status = "usage_unavailable"
                cost_values: Dict[str, Any] = {
                    "ordinary_input_tokens": None,
                    "pricing_id": None,
                    "pricing_model": None,
                    "pricing_context_band": None,
                    "input_usd_per_million": None,
                    "cached_input_usd_per_million": None,
                    "cache_write_usd_per_million": None,
                    "output_usd_per_million": None,
                    "ordinary_input_cost_usd": None,
                    "cached_input_cost_usd": None,
                    "cache_write_cost_usd": None,
                    "output_cost_usd": None,
                    "token_cost_usd": None,
                    "web_search_usd_per_1000": None,
                    "web_search_cost_usd": None,
                    "tool_pricing_source_url": None,
                    "estimated_cost_usd": None,
                    "pricing_source_url": None,
                }
                tool_pricing = self._tool_pricing_row(connection, tool="web_search")
                if tool_pricing is not None:
                    web_search_rate = tool_pricing["usd_per_1000_calls"]
                    cost_values.update(
                        {
                            "web_search_usd_per_1000": web_search_rate,
                            "web_search_cost_usd": _cost(
                                web_search_calls, web_search_rate * 1000
                            ),
                            "tool_pricing_source_url": tool_pricing["source_url"],
                        }
                    )

                if input_tokens is not None and output_tokens is not None:
                    cached = cached_tokens or 0
                    written = cache_write_tokens or 0
                    ordinary = input_tokens - cached - written
                    if ordinary < 0:
                        cost_status = "invalid_usage"
                    else:
                        cost_values["ordinary_input_tokens"] = ordinary
                        pricing_model_candidate = actual_model or started_row["requested_model"]
                        tier_candidate = actual_service_tier or started_row["requested_service_tier"]
                        pricing = self._pricing_row(
                            connection,
                            model=pricing_model_candidate,
                            service_tier=tier_candidate,
                            input_tokens=input_tokens,
                        )
                        if pricing is None:
                            cost_status = (
                                "unpriced_model"
                                if _canonical_pricing_model(pricing_model_candidate) is None
                                else "unpriced_service_tier"
                            )
                        else:
                            ordinary_cost = _cost(
                                ordinary, pricing["input_usd_per_million"]
                            )
                            cached_cost = _cost(
                                cached, pricing["cached_input_usd_per_million"]
                            )
                            write_cost = _cost(
                                written, pricing["cache_write_usd_per_million"]
                            )
                            output_cost = _cost(
                                output_tokens, pricing["output_usd_per_million"]
                            )
                            token_cost = float(
                                sum(
                                    Decimal(str(value))
                                    for value in (
                                        ordinary_cost,
                                        cached_cost,
                                        write_cost,
                                        output_cost,
                                    )
                                )
                            )
                            web_search_cost = cost_values["web_search_cost_usd"]
                            estimated_cost = (
                                float(
                                    Decimal(str(token_cost))
                                    + Decimal(str(web_search_cost))
                                )
                                if web_search_cost is not None
                                else None
                            )
                            cost_status = "estimated_public_list_price"
                            cost_values.update(
                                {
                                    "pricing_id": pricing["pricing_id"],
                                    "pricing_model": pricing["model"],
                                    "pricing_context_band": pricing["context_band"],
                                    "input_usd_per_million": pricing[
                                        "input_usd_per_million"
                                    ],
                                    "cached_input_usd_per_million": pricing[
                                        "cached_input_usd_per_million"
                                    ],
                                    "cache_write_usd_per_million": pricing[
                                        "cache_write_usd_per_million"
                                    ],
                                    "output_usd_per_million": pricing[
                                        "output_usd_per_million"
                                    ],
                                    "ordinary_input_cost_usd": ordinary_cost,
                                    "cached_input_cost_usd": cached_cost,
                                    "cache_write_cost_usd": write_cost,
                                    "output_cost_usd": output_cost,
                                    "token_cost_usd": token_cost,
                                    "estimated_cost_usd": estimated_cost,
                                    "pricing_source_url": pricing["source_url"],
                                }
                            )

                connection.execute(
                    """
                    UPDATE llm_requests
                    SET actual_model = ?,
                        actual_service_tier = ?,
                        response_id = ?,
                        response_status = ?,
                        status = 'completed',
                        completed_at = ?,
                        duration_ms = ?,
                        input_tokens = ?,
                        ordinary_input_tokens = ?,
                        cached_input_tokens = ?,
                        cache_write_tokens = ?,
                        output_tokens = ?,
                        reasoning_tokens = ?,
                        total_tokens = ?,
                        pricing_id = ?,
                        pricing_model = ?,
                        pricing_context_band = ?,
                        input_usd_per_million = ?,
                        cached_input_usd_per_million = ?,
                        cache_write_usd_per_million = ?,
                        output_usd_per_million = ?,
                        ordinary_input_cost_usd = ?,
                        cached_input_cost_usd = ?,
                        cache_write_cost_usd = ?,
                        output_cost_usd = ?,
                        token_cost_usd = ?,
                        web_search_calls = ?,
                        web_search_usd_per_1000 = ?,
                        web_search_cost_usd = ?,
                        tool_pricing_source_url = ?,
                        estimated_cost_usd = ?,
                        cost_status = ?,
                        pricing_source_url = ?
                    WHERE request_id = ?
                    """,
                    (
                        actual_model,
                        actual_service_tier,
                        response_id,
                        response_status,
                        completed_at.isoformat(),
                        duration_ms,
                        input_tokens,
                        cost_values["ordinary_input_tokens"],
                        cached_tokens,
                        cache_write_tokens,
                        output_tokens,
                        reasoning_tokens,
                        total_tokens,
                        cost_values["pricing_id"],
                        cost_values["pricing_model"],
                        cost_values["pricing_context_band"],
                        cost_values["input_usd_per_million"],
                        cost_values["cached_input_usd_per_million"],
                        cost_values["cache_write_usd_per_million"],
                        cost_values["output_usd_per_million"],
                        cost_values["ordinary_input_cost_usd"],
                        cost_values["cached_input_cost_usd"],
                        cost_values["cache_write_cost_usd"],
                        cost_values["output_cost_usd"],
                        cost_values["token_cost_usd"],
                        web_search_calls,
                        cost_values["web_search_usd_per_1000"],
                        cost_values["web_search_cost_usd"],
                        cost_values["tool_pricing_source_url"],
                        cost_values["estimated_cost_usd"],
                        cost_status,
                        cost_values["pricing_source_url"],
                        request_id,
                    ),
                )
        except sqlite3.Error as exc:
            raise UsageStoreError(
                f"Could not complete usage record in {self.database}: {exc}"
            ) from exc
        finally:
            connection.close()

    def fail_request(self, request_id: str, error: BaseException) -> None:
        completed_at = _utc_now()
        connection = self._connect(create=False)
        try:
            with connection:
                self._initialize(connection)
                row = connection.execute(
                    "SELECT started_at FROM llm_requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise UsageStoreError(f"Unknown LLM usage request ID: {request_id}")
                connection.execute(
                    """
                    UPDATE llm_requests
                    SET status = 'failed',
                        completed_at = ?,
                        duration_ms = ?,
                        cost_status = 'usage_unavailable',
                        error_type = ?,
                        error_message = ?
                    WHERE request_id = ?
                    """,
                    (
                        completed_at.isoformat(),
                        self._duration_ms(row["started_at"], completed_at),
                        type(error).__name__,
                        str(error)[:2000],
                        request_id,
                    ),
                )
        except sqlite3.Error as exc:
            raise UsageStoreError(
                f"Could not fail usage record in {self.database}: {exc}"
            ) from exc
        finally:
            connection.close()

    def list_requests(
        self, *, limit: int = 100, workflow_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if limit < 1:
            raise UsageStoreError("Usage request limit must be at least 1")
        connection = self._connect(create=False)
        try:
            self._initialize(connection)
            connection.commit()
            parameters: List[Any] = []
            where = ""
            if workflow_id is not None:
                where = "WHERE workflow_id = ?"
                parameters.append(workflow_id)
            parameters.append(limit)
            rows = connection.execute(
                f"""
                SELECT *
                FROM llm_requests
                {where}
                ORDER BY started_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise UsageStoreError(
                f"Could not list usage records from {self.database}: {exc}"
            ) from exc
        finally:
            connection.close()

    def summary(self, *, workflow_id: Optional[str] = None) -> Dict[str, Any]:
        connection = self._connect(create=False)
        try:
            self._initialize(connection)
            connection.commit()
            parameters: List[Any] = []
            where = ""
            if workflow_id is not None:
                where = "WHERE workflow_id = ?"
                parameters.append(workflow_id)
            total = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS requests,
                    COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0)
                        AS completed,
                    COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0)
                        AS failed,
                    COALESCE(SUM(CASE WHEN status = 'started' THEN 1 ELSE 0 END), 0)
                        AS started,
                    COALESCE(SUM(
                        CASE WHEN estimated_cost_usd IS NOT NULL THEN 1 ELSE 0 END
                    ), 0)
                        AS priced_requests,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(token_cost_usd), 0.0) AS token_cost_usd,
                    COALESCE(SUM(web_search_calls), 0) AS web_search_calls,
                    COALESCE(SUM(web_search_cost_usd), 0.0) AS web_search_cost_usd,
                    COALESCE(SUM(estimated_cost_usd), 0.0) AS estimated_cost_usd
                FROM llm_requests
                {where}
                """,
                parameters,
            ).fetchone()
            by_kind = connection.execute(
                f"""
                SELECT
                    request_kind,
                    COUNT(*) AS requests,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(web_search_calls), 0) AS web_search_calls,
                    COALESCE(SUM(web_search_cost_usd), 0.0) AS web_search_cost_usd,
                    COALESCE(SUM(estimated_cost_usd), 0.0) AS estimated_cost_usd
                FROM llm_requests
                {where}
                GROUP BY request_kind
                ORDER BY request_kind
                """,
                parameters,
            ).fetchall()
        except sqlite3.Error as exc:
            raise UsageStoreError(
                f"Could not summarize usage records from {self.database}: {exc}"
            ) from exc
        finally:
            connection.close()

        result = dict(total)
        result["unpriced_requests"] = result["requests"] - result["priced_requests"]
        result["workflow_id"] = workflow_id
        result["database"] = str(self.database)
        result["currency"] = "USD"
        result["by_request_kind"] = [dict(row) for row in by_kind]
        return result
