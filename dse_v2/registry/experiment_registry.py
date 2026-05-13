#!/usr/bin/env python3
"""Persistent experiment registry for DSE campaigns and trials."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import cast

from dse_v2.registry.schema import CAMPAIGN_SPEC_REQUIRED_FIELDS, SCHEMA_STATEMENTS


@dataclass(frozen=True)
class Campaign:
    campaign_id: int
    name: str
    metadata: dict[str, object]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TrialRecord:
    trial_id: int
    campaign_id: int
    params: dict[str, object]
    fidelity: str
    status: str
    metrics: dict[str, object]
    artifacts: dict[str, object]
    created_at: str
    updated_at: str


_MISSING = object()
_EMPTY_JSON: Mapping[str, object] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_dumps(data: Mapping[str, object]) -> str:
    return json.dumps(dict(data or {}), sort_keys=True, separators=(",", ":"))


def _json_loads(payload: str) -> dict[str, object]:
    data: object = json.loads(payload) if payload else {}
    if not isinstance(data, dict):
        raise ValueError("registry JSON payload must decode to an object")
    decoded = cast(dict[object, object], data)
    return {str(key): value for key, value in decoded.items()}


def _row_value(row: sqlite3.Row, key: str) -> object:
    return cast(object, row[key])


def _row_int(row: sqlite3.Row, key: str) -> int:
    value = _row_value(row, key)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"expected integer column for {key}")


def _row_str(row: sqlite3.Row, key: str) -> str:
    value = _row_value(row, key)
    if isinstance(value, str):
        return value
    return str(value)


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RuntimeError("SQLite did not return a row id")
    return int(cursor.lastrowid)


def _campaign_from_row(row: sqlite3.Row) -> Campaign:
    return Campaign(
        campaign_id=_row_int(row, "campaign_id"),
        name=_row_str(row, "name"),
        metadata=_json_loads(_row_str(row, "metadata_json")),
        created_at=_row_str(row, "created_at"),
        updated_at=_row_str(row, "updated_at"),
    )


def _trial_from_row(row: sqlite3.Row) -> TrialRecord:
    return TrialRecord(
        trial_id=_row_int(row, "trial_id"),
        campaign_id=_row_int(row, "campaign_id"),
        params=_json_loads(_row_str(row, "params_json")),
        fidelity=_row_str(row, "fidelity"),
        status=_row_str(row, "status"),
        metrics=_json_loads(_row_str(row, "metrics_json")),
        artifacts=_json_loads(_row_str(row, "artifacts_json")),
        created_at=_row_str(row, "created_at"),
        updated_at=_row_str(row, "updated_at"),
    )


class ExperimentRegistry:
    """Small SQLite-backed ledger for campaigns and DSE trial records.

    This package owns the persistent ledger. Candidate queue and Pareto archive
    modules should reference registry ids rather than being embedded here.
    """

    def __init__(self, db_path: Path):
        self.db_path: Path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._closed: bool = False
        self._create_schema()

    def _connection(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("experiment registry is closed")
        return self._conn

    def _create_schema(self) -> None:
        conn = self._connection()
        _ = conn.execute("PRAGMA foreign_keys = ON")
        for statement in SCHEMA_STATEMENTS:
            _ = conn.execute(statement)
        conn.commit()

    def close(self) -> None:
        if not self._closed:
            self._conn.close()
            self._closed = True

    def __enter__(self) -> "ExperimentRegistry":
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        self.close()

    def create_campaign(self, name: str, metadata: Mapping[str, object] = _EMPTY_JSON) -> Campaign:
        now = _now_iso()
        conn = self._connection()
        cursor = conn.execute(
            """
            INSERT INTO campaigns(name, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, _json_dumps(metadata), now, now),
        )
        conn.commit()
        campaign = self.get_campaign(_lastrowid(cursor))
        if campaign is None:
            raise RuntimeError("failed to reload created campaign")
        return campaign

    def create_campaign_from_spec(self, spec: Mapping[str, object], *, name: str | None = None) -> Campaign:
        """Persist a structured campaign spec without losing its required fields."""
        missing = [field for field in CAMPAIGN_SPEC_REQUIRED_FIELDS if field not in spec]
        if missing:
            raise ValueError(f"campaign spec missing required fields: {', '.join(missing)}")
        campaign_name = name or str(spec["campaign_id"])
        return self.create_campaign(campaign_name, metadata=dict(spec))

    def get_campaign(self, campaign_id: int) -> Campaign | None:
        row = cast(sqlite3.Row | None, self._connection().execute(
            """
            SELECT campaign_id, name, metadata_json, created_at, updated_at
            FROM campaigns
            WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone())
        return _campaign_from_row(row) if row is not None else None

    def list_campaigns(self) -> list[Campaign]:
        rows = cast(list[sqlite3.Row], self._connection().execute(
            """
            SELECT campaign_id, name, metadata_json, created_at, updated_at
            FROM campaigns
            ORDER BY campaign_id
            """
        ).fetchall())
        return [_campaign_from_row(row) for row in rows]

    def add_trial(
        self,
        campaign_id: int,
        params: Mapping[str, object],
        fidelity: str,
        status: str,
        metrics: Mapping[str, object] = _EMPTY_JSON,
        artifacts: Mapping[str, object] = _EMPTY_JSON,
    ) -> TrialRecord:
        now = _now_iso()
        conn = self._connection()
        cursor = conn.execute(
            """
            INSERT INTO trials(
                campaign_id, params_json, fidelity, status, metrics_json, artifacts_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                _json_dumps(params),
                fidelity,
                status,
                _json_dumps(metrics),
                _json_dumps(artifacts),
                now,
                now,
            ),
        )
        conn.commit()
        return self._get_trial_or_raise(_lastrowid(cursor))

    def update_trial(
        self,
        trial_id: int,
        *,
        status: object = _MISSING,
        fidelity: object = _MISSING,
        params: object = _MISSING,
        metrics: object = _MISSING,
        artifacts: object = _MISSING,
    ) -> TrialRecord:
        updates: list[str] = []
        values: list[object] = []
        if status is not _MISSING:
            if not isinstance(status, str):
                raise TypeError("status must be a string")
            updates.append("status = ?")
            values.append(status)
        if fidelity is not _MISSING:
            if not isinstance(fidelity, str):
                raise TypeError("fidelity must be a string")
            updates.append("fidelity = ?")
            values.append(fidelity)
        if params is not _MISSING:
            if not isinstance(params, Mapping):
                raise TypeError("params must be a mapping")
            updates.append("params_json = ?")
            values.append(_json_dumps(cast(Mapping[str, object], params)))
        if metrics is not _MISSING:
            if not isinstance(metrics, Mapping):
                raise TypeError("metrics must be a mapping")
            updates.append("metrics_json = ?")
            values.append(_json_dumps(cast(Mapping[str, object], metrics)))
        if artifacts is not _MISSING:
            if not isinstance(artifacts, Mapping):
                raise TypeError("artifacts must be a mapping")
            updates.append("artifacts_json = ?")
            values.append(_json_dumps(cast(Mapping[str, object], artifacts)))

        if updates:
            updates.append("updated_at = ?")
            values.append(_now_iso())
            values.append(trial_id)
            conn = self._connection()
            _ = conn.execute(f"UPDATE trials SET {', '.join(updates)} WHERE trial_id = ?", values)
            conn.commit()

        return self._get_trial_or_raise(trial_id)

    def query_trials(
        self,
        *,
        campaign_id: int | None = None,
        status: str | None = None,
        fidelity: str | None = None,
    ) -> list[TrialRecord]:
        where: list[str] = []
        values: list[object] = []
        if campaign_id is not None:
            where.append("campaign_id = ?")
            values.append(campaign_id)
        if status is not None:
            where.append("status = ?")
            values.append(status)
        if fidelity is not None:
            where.append("fidelity = ?")
            values.append(fidelity)

        sql = """
            SELECT trial_id, campaign_id, params_json, fidelity, status, metrics_json, artifacts_json, created_at, updated_at
            FROM trials
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY trial_id"
        rows = cast(list[sqlite3.Row], self._connection().execute(sql, values).fetchall())
        return [_trial_from_row(row) for row in rows]

    def _get_trial_or_raise(self, trial_id: int) -> TrialRecord:
        row = cast(sqlite3.Row | None, self._connection().execute(
            """
            SELECT trial_id, campaign_id, params_json, fidelity, status, metrics_json, artifacts_json, created_at, updated_at
            FROM trials
            WHERE trial_id = ?
            """,
            (trial_id,),
        ).fetchone())
        if row is None:
            raise KeyError(f"trial_id not found: {trial_id}")
        return _trial_from_row(row)
