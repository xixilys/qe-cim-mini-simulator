#!/usr/bin/env python3
"""Persistent experiment registry for DSE campaigns and trials."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import cast

from dse_v2.registry.schema import CAMPAIGN_SPEC_REQUIRED_FIELDS, SCHEMA_MIGRATIONS, SCHEMA_STATEMENTS


CAMPAIGN_STATES = frozenset({
    "created",
    "running",
    "deliverable_complete",
    "partial_blocked_not_complete",
    "failed",
})
CAMPAIGN_TERMINAL_STATES = frozenset({"deliverable_complete", "partial_blocked_not_complete", "failed"})
CAMPAIGN_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "created": frozenset({"running", "failed"}),
    "running": CAMPAIGN_TERMINAL_STATES,
    "deliverable_complete": frozenset(),
    "partial_blocked_not_complete": frozenset(),
    "failed": frozenset(),
}

WORKLOAD_RUN_STATES = frozenset({
    "created",
    "ingesting",
    "lowered",
    "validated",
    "blocked",
    "ready_for_step2",
})
WORKLOAD_RUN_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "created": frozenset({"ingesting", "blocked"}),
    "ingesting": frozenset({"lowered", "blocked"}),
    "lowered": frozenset({"validated", "blocked"}),
    "validated": frozenset({"ready_for_step2", "blocked"}),
    "blocked": frozenset({"ingesting", "lowered", "validated"}),
    "ready_for_step2": frozenset(),
}

TRIAL_STATES = frozenset({
    "generated",
    "screened",
    "promoted",
    "scheduled_for_sim",
    "simulated",
    "adjudicated",
    "reported",
    "finalist",
    "rejected",
    "blocked",
    "selected",
})
TRIAL_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "generated": frozenset({"screened", "blocked", "rejected"}),
    "screened": frozenset({"promoted", "blocked", "rejected"}),
    "promoted": frozenset({"scheduled_for_sim", "blocked", "rejected"}),
    "scheduled_for_sim": frozenset({"simulated", "blocked"}),
    "simulated": frozenset({"adjudicated", "blocked"}),
    "adjudicated": frozenset({"reported", "finalist", "blocked", "rejected"}),
    "reported": frozenset({"finalist", "selected", "rejected"}),
    "finalist": frozenset({"selected", "rejected"}),
    "blocked": frozenset({"generated", "screened", "promoted", "scheduled_for_sim"}),
    "selected": frozenset(),
    "rejected": frozenset(),
}

ACTIVITY_STATES = frozenset({"created", "running", "succeeded", "failed", "blocked"})
ACTIVITY_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "created": frozenset({"running", "blocked", "failed"}),
    "running": frozenset({"succeeded", "failed", "blocked"}),
    "blocked": frozenset({"running", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
}

FINAL_STATUS_LABELS = frozenset({"deliverable_complete", "partial_blocked_not_complete", "failed"})


@dataclass(frozen=True)
class FailurePolicy:
    """Retry/no-retry policy owned by the registry lifecycle layer."""

    max_retries: int = 1
    retryable_reasons: tuple[str, ...] = ("timeout", "crash")
    no_retry_reasons: tuple[str, ...] = ("schema-invalid", "missing-binding")
    recovery_actions: Mapping[str, str] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "max_retries": self.max_retries,
            "retryable_reasons": list(self.retryable_reasons),
            "no_retry_reasons": list(self.no_retry_reasons),
            "recovery_actions": dict(self.recovery_actions or {}),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object] | None) -> "FailurePolicy":
        data = dict(payload or {})
        return cls(
            max_retries=int(data.get("max_retries", 1)),
            retryable_reasons=tuple(str(item) for item in data.get("retryable_reasons", ("timeout", "crash"))),
            no_retry_reasons=tuple(str(item) for item in data.get("no_retry_reasons", ("schema-invalid", "missing-binding"))),
            recovery_actions=cast(Mapping[str, str] | None, data.get("recovery_actions")),
        )


DEFAULT_FAILURE_POLICY = FailurePolicy(
    recovery_actions={
        "timeout": "retry_after_timeout_budget_review",
        "crash": "retry_after_crash_diagnostics",
        "schema-invalid": "fix_schema_payload_before_resume",
        "missing-binding": "restore_required_binding_before_resume",
    }
)


@dataclass(frozen=True)
class FailureDecision:
    reason: str
    attempts: int
    action: str
    retry_allowed: bool
    max_retries: int
    recovery_action: str
    next_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "attempts": self.attempts,
            "action": self.action,
            "retry_allowed": self.retry_allowed,
            "max_retries": self.max_retries,
            "recovery_action": self.recovery_action,
            "next_status": self.next_status,
        }


@dataclass(frozen=True)
class Campaign:
    campaign_id: int
    name: str
    metadata: dict[str, object]
    created_at: str
    updated_at: str
    status: str = "created"


@dataclass(frozen=True)
class WorkloadRunRecord:
    workload_run_id: int
    campaign_id: int
    workload_ref: dict[str, object]
    status: str
    provenance: dict[str, object]
    failure_policy: dict[str, object]
    resume: dict[str, object]
    blockers: dict[str, object]
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
    workload_run_id: int | None = None
    provenance: dict[str, object] | None = None
    failure_policy: dict[str, object] | None = None
    resume: dict[str, object] | None = None
    generation: dict[str, object] | None = None


@dataclass(frozen=True)
class ActivityRecord:
    activity_id: int
    campaign_id: int
    workload_run_id: int | None
    trial_id: int | None
    activity_type: str
    status: str
    command: dict[str, object]
    environment: dict[str, object]
    inputs: dict[str, object]
    outputs: dict[str, object]
    provenance: dict[str, object]
    failure_policy: dict[str, object]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ArtifactRef:
    artifact_ref_id: int
    campaign_id: int
    workload_run_id: int | None
    trial_id: int | None
    path: str
    schema_id: str
    schema_version: str
    content_hash: str
    content_hash_alg: str
    producing_activity_id: int | None
    consuming_activity_ids: tuple[int, ...]
    metadata: dict[str, object]
    created_at: str


@dataclass(frozen=True)
class ResumePlan:
    campaign: Campaign
    workload_run: WorkloadRunRecord | None
    trial: TrialRecord | None
    activities: tuple[ActivityRecord, ...]
    artifacts: tuple[ArtifactRef, ...]
    next_actions: tuple[str, ...]


class InvalidTransitionError(ValueError):
    """Raised when lifecycle policy rejects a state transition."""


class ProvenanceRequiredError(ValueError):
    """Raised when a policy-owned transition lacks audit provenance."""


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


def _json_list_dumps(data: Iterable[object]) -> str:
    return json.dumps(list(data or []), sort_keys=True, separators=(",", ":"))


def _json_int_tuple_loads(payload: str) -> tuple[int, ...]:
    data: object = json.loads(payload) if payload else []
    if not isinstance(data, list):
        raise ValueError("registry JSON payload must decode to a list")
    return tuple(int(item) for item in data)


def _row_value(row: sqlite3.Row, key: str) -> object:
    return cast(object, row[key])


def _row_int(row: sqlite3.Row, key: str) -> int:
    value = _row_value(row, key)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"expected integer column for {key}")


def _row_optional_int(row: sqlite3.Row, key: str) -> int | None:
    value = _row_value(row, key)
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"expected optional integer column for {key}")


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
        status=_row_str(row, "status"),
    )


def _workload_from_row(row: sqlite3.Row) -> WorkloadRunRecord:
    return WorkloadRunRecord(
        workload_run_id=_row_int(row, "workload_run_id"),
        campaign_id=_row_int(row, "campaign_id"),
        workload_ref=_json_loads(_row_str(row, "workload_ref_json")),
        status=_row_str(row, "status"),
        provenance=_json_loads(_row_str(row, "provenance_json")),
        failure_policy=_json_loads(_row_str(row, "failure_policy_json")),
        resume=_json_loads(_row_str(row, "resume_json")),
        blockers=_json_loads(_row_str(row, "blockers_json")),
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
        workload_run_id=_row_optional_int(row, "workload_run_id"),
        provenance=_json_loads(_row_str(row, "provenance_json")),
        failure_policy=_json_loads(_row_str(row, "failure_policy_json")),
        resume=_json_loads(_row_str(row, "resume_json")),
        generation=_json_loads(_row_str(row, "generation_json")),
    )


def _activity_from_row(row: sqlite3.Row) -> ActivityRecord:
    return ActivityRecord(
        activity_id=_row_int(row, "activity_id"),
        campaign_id=_row_int(row, "campaign_id"),
        workload_run_id=_row_optional_int(row, "workload_run_id"),
        trial_id=_row_optional_int(row, "trial_id"),
        activity_type=_row_str(row, "activity_type"),
        status=_row_str(row, "status"),
        command=_json_loads(_row_str(row, "command_json")),
        environment=_json_loads(_row_str(row, "environment_json")),
        inputs=_json_loads(_row_str(row, "inputs_json")),
        outputs=_json_loads(_row_str(row, "outputs_json")),
        provenance=_json_loads(_row_str(row, "provenance_json")),
        failure_policy=_json_loads(_row_str(row, "failure_policy_json")),
        created_at=_row_str(row, "created_at"),
        updated_at=_row_str(row, "updated_at"),
    )


def _artifact_from_row(row: sqlite3.Row) -> ArtifactRef:
    return ArtifactRef(
        artifact_ref_id=_row_int(row, "artifact_ref_id"),
        campaign_id=_row_int(row, "campaign_id"),
        workload_run_id=_row_optional_int(row, "workload_run_id"),
        trial_id=_row_optional_int(row, "trial_id"),
        path=_row_str(row, "path"),
        schema_id=_row_str(row, "schema_id"),
        schema_version=_row_str(row, "schema_version"),
        content_hash=_row_str(row, "content_hash"),
        content_hash_alg=_row_str(row, "content_hash_alg"),
        producing_activity_id=_row_optional_int(row, "producing_activity_id"),
        consuming_activity_ids=_json_int_tuple_loads(_row_str(row, "consuming_activity_ids_json")),
        metadata=_json_loads(_row_str(row, "metadata_json")),
        created_at=_row_str(row, "created_at"),
    )


def _require_provenance(provenance: Mapping[str, object], *, context: str) -> dict[str, object]:
    payload = dict(provenance or {})
    if not payload.get("actor") or not payload.get("reason"):
        raise ProvenanceRequiredError(f"{context} requires provenance fields: actor, reason")
    return payload


def _validate_state(value: str, allowed_states: frozenset[str], *, kind: str) -> None:
    if value not in allowed_states:
        raise InvalidTransitionError(f"unknown {kind} state: {value}")


def _validate_transition(
    *,
    kind: str,
    current: str,
    target: str,
    states: frozenset[str],
    transitions: Mapping[str, frozenset[str]],
) -> None:
    _validate_state(current, states, kind=kind)
    _validate_state(target, states, kind=kind)
    if target not in transitions.get(current, frozenset()):
        raise InvalidTransitionError(f"invalid {kind} transition: {current} -> {target}")


def completion_status_allows_final_claim(status: str) -> bool:
    """Return whether a terminal campaign status can satisfy final completion."""
    return status == "deliverable_complete"


class ExperimentRegistry:
    """SQLite-backed ledger for campaigns, workload runs, activities, artifacts, and trials.

    The lifecycle APIs in this class own Campaign -> WorkloadRun/IngestionRun
    -> Trial transitions. The older ``add_trial``/``update_trial`` methods are
    retained for existing pilot compatibility and should not be used for new
    Step1-Step5 lifecycle mutation.
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
        for table, migrations in SCHEMA_MIGRATIONS.items():
            columns = {
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, statement in migrations.items():
                if column not in columns:
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

    def create_campaign(
        self,
        name: str,
        metadata: Mapping[str, object] = _EMPTY_JSON,
        *,
        status: str = "created",
    ) -> Campaign:
        _validate_state(status, CAMPAIGN_STATES, kind="campaign")
        now = _now_iso()
        conn = self._connection()
        cursor = conn.execute(
            """
            INSERT INTO campaigns(name, status, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, status, _json_dumps(metadata), now, now),
        )
        conn.commit()
        campaign = self.get_campaign(_lastrowid(cursor))
        if campaign is None:
            raise RuntimeError("failed to reload created campaign")
        return campaign

    def transition_campaign(self, campaign_id: int, status: str, *, provenance: Mapping[str, object]) -> Campaign:
        _ = _require_provenance(provenance, context="campaign transition")
        campaign = self._get_campaign_or_raise(campaign_id)
        _validate_transition(
            kind="campaign",
            current=campaign.status,
            target=status,
            states=CAMPAIGN_STATES,
            transitions=CAMPAIGN_TRANSITIONS,
        )
        now = _now_iso()
        _ = self._connection().execute(
            "UPDATE campaigns SET status = ?, updated_at = ? WHERE campaign_id = ?",
            (status, now, campaign_id),
        )
        self._connection().commit()
        return self._get_campaign_or_raise(campaign_id)

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
            SELECT campaign_id, name, status, metadata_json, created_at, updated_at
            FROM campaigns
            WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone())
        return _campaign_from_row(row) if row is not None else None

    def _get_campaign_or_raise(self, campaign_id: int) -> Campaign:
        campaign = self.get_campaign(campaign_id)
        if campaign is None:
            raise KeyError(f"campaign_id not found: {campaign_id}")
        return campaign

    def list_campaigns(self) -> list[Campaign]:
        rows = cast(list[sqlite3.Row], self._connection().execute(
            """
            SELECT campaign_id, name, status, metadata_json, created_at, updated_at
            FROM campaigns
            ORDER BY campaign_id
            """
        ).fetchall())
        return [_campaign_from_row(row) for row in rows]

    def create_workload_run(
        self,
        campaign_id: int,
        workload_ref: Mapping[str, object],
        *,
        provenance: Mapping[str, object],
        failure_policy: FailurePolicy | Mapping[str, object] | None = None,
        resume: Mapping[str, object] = _EMPTY_JSON,
        blockers: Mapping[str, object] = _EMPTY_JSON,
    ) -> WorkloadRunRecord:
        _ = self._get_campaign_or_raise(campaign_id)
        provenance_payload = _require_provenance(provenance, context="workload run creation")
        failure_payload = self._failure_policy_payload(failure_policy)
        now = _now_iso()
        cursor = self._connection().execute(
            """
            INSERT INTO workload_runs(
                campaign_id, workload_ref_json, status, provenance_json,
                failure_policy_json, resume_json, blockers_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                _json_dumps(workload_ref),
                "created",
                _json_dumps(provenance_payload),
                _json_dumps(failure_payload),
                _json_dumps(resume),
                _json_dumps(blockers),
                now,
                now,
            ),
        )
        self._connection().commit()
        return self._get_workload_run_or_raise(_lastrowid(cursor))

    def get_workload_run(self, workload_run_id: int) -> WorkloadRunRecord | None:
        row = cast(sqlite3.Row | None, self._connection().execute(
            """
            SELECT workload_run_id, campaign_id, workload_ref_json, status, provenance_json,
                   failure_policy_json, resume_json, blockers_json, created_at, updated_at
            FROM workload_runs
            WHERE workload_run_id = ?
            """,
            (workload_run_id,),
        ).fetchone())
        return _workload_from_row(row) if row is not None else None

    def query_workload_runs(self, *, campaign_id: int | None = None, status: str | None = None) -> list[WorkloadRunRecord]:
        where: list[str] = []
        values: list[object] = []
        if campaign_id is not None:
            where.append("campaign_id = ?")
            values.append(campaign_id)
        if status is not None:
            where.append("status = ?")
            values.append(status)
        sql = """
            SELECT workload_run_id, campaign_id, workload_ref_json, status, provenance_json,
                   failure_policy_json, resume_json, blockers_json, created_at, updated_at
            FROM workload_runs
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY workload_run_id"
        rows = cast(list[sqlite3.Row], self._connection().execute(sql, values).fetchall())
        return [_workload_from_row(row) for row in rows]

    def transition_workload_run(
        self,
        workload_run_id: int,
        status: str,
        *,
        provenance: Mapping[str, object],
        resume: Mapping[str, object] | None = None,
        blockers: Mapping[str, object] | None = None,
    ) -> WorkloadRunRecord:
        provenance_payload = _require_provenance(provenance, context="workload run transition")
        workload = self._get_workload_run_or_raise(workload_run_id)
        _validate_transition(
            kind="workload run",
            current=workload.status,
            target=status,
            states=WORKLOAD_RUN_STATES,
            transitions=WORKLOAD_RUN_TRANSITIONS,
        )
        updates = ["status = ?", "provenance_json = ?", "updated_at = ?"]
        values: list[object] = [status, _json_dumps(provenance_payload), _now_iso()]
        if resume is not None:
            updates.append("resume_json = ?")
            values.append(_json_dumps(resume))
        if blockers is not None:
            updates.append("blockers_json = ?")
            values.append(_json_dumps(blockers))
        values.append(workload_run_id)
        _ = self._connection().execute(
            f"UPDATE workload_runs SET {', '.join(updates)} WHERE workload_run_id = ?",
            values,
        )
        self._connection().commit()
        return self._get_workload_run_or_raise(workload_run_id)

    def create_trial(
        self,
        workload_run_id: int,
        params: Mapping[str, object],
        fidelity: str,
        *,
        generation_reasons: Sequence[str],
        provenance: Mapping[str, object],
        metrics: Mapping[str, object] = _EMPTY_JSON,
        artifacts: Mapping[str, object] = _EMPTY_JSON,
        failure_policy: FailurePolicy | Mapping[str, object] | None = None,
    ) -> TrialRecord:
        workload = self._get_workload_run_or_raise(workload_run_id)
        if workload.status != "ready_for_step2":
            raise InvalidTransitionError(
                f"trial creation requires workload run ready_for_step2, got {workload.status}"
            )
        provenance_payload = _require_provenance(provenance, context="trial creation")
        failure_payload = self._failure_policy_payload(failure_policy)
        generation = {"generation_reasons": list(generation_reasons)}
        now = _now_iso()
        cursor = self._connection().execute(
            """
            INSERT INTO trials(
                campaign_id, workload_run_id, params_json, fidelity, status, metrics_json,
                artifacts_json, provenance_json, failure_policy_json, resume_json,
                generation_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workload.campaign_id,
                workload_run_id,
                _json_dumps(params),
                fidelity,
                "generated",
                _json_dumps(metrics),
                _json_dumps(artifacts),
                _json_dumps(provenance_payload),
                _json_dumps(failure_payload),
                _json_dumps({"resume_allowed": True, "source": "ledger"}),
                _json_dumps(generation),
                now,
                now,
            ),
        )
        self._connection().commit()
        return self._get_trial_or_raise(_lastrowid(cursor))

    def add_trial(
        self,
        campaign_id: int,
        params: Mapping[str, object],
        fidelity: str,
        status: str,
        metrics: Mapping[str, object] = _EMPTY_JSON,
        artifacts: Mapping[str, object] = _EMPTY_JSON,
    ) -> TrialRecord:
        """Compatibility inserter for legacy pilot registry rows.

        New Step1-Step5 code should use ``create_workload_run`` +
        ``create_trial`` + ``transition_trial`` so lifecycle mutation is
        policy-owned and provenance-backed.
        """
        _ = self._get_campaign_or_raise(campaign_id)
        now = _now_iso()
        conn = self._connection()
        cursor = conn.execute(
            """
            INSERT INTO trials(
                campaign_id, workload_run_id, params_json, fidelity, status, metrics_json,
                artifacts_json, provenance_json, failure_policy_json, resume_json,
                generation_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                None,
                _json_dumps(params),
                fidelity,
                status,
                _json_dumps(metrics),
                _json_dumps(artifacts),
                _json_dumps({"compatibility_api": "add_trial"}),
                _json_dumps(DEFAULT_FAILURE_POLICY.to_dict()),
                _json_dumps({"resume_allowed": False, "source": "legacy_trial"}),
                _json_dumps({}),
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
        """Compatibility updater for legacy registry rows.

        Prefer ``transition_trial`` for lifecycle state changes.
        """
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

    def transition_trial(
        self,
        trial_id: int,
        status: str,
        *,
        provenance: Mapping[str, object],
        metrics: Mapping[str, object] | None = None,
        artifacts: Mapping[str, object] | None = None,
        resume: Mapping[str, object] | None = None,
    ) -> TrialRecord:
        provenance_payload = _require_provenance(provenance, context="trial transition")
        trial = self._get_trial_or_raise(trial_id)
        _validate_transition(
            kind="trial",
            current=trial.status,
            target=status,
            states=TRIAL_STATES,
            transitions=TRIAL_TRANSITIONS,
        )
        updates = ["status = ?", "provenance_json = ?", "updated_at = ?"]
        values: list[object] = [status, _json_dumps(provenance_payload), _now_iso()]
        if metrics is not None:
            updates.append("metrics_json = ?")
            values.append(_json_dumps(metrics))
        if artifacts is not None:
            updates.append("artifacts_json = ?")
            values.append(_json_dumps(artifacts))
        if resume is not None:
            updates.append("resume_json = ?")
            values.append(_json_dumps(resume))
        values.append(trial_id)
        _ = self._connection().execute(f"UPDATE trials SET {', '.join(updates)} WHERE trial_id = ?", values)
        self._connection().commit()
        return self._get_trial_or_raise(trial_id)

    def record_trial_failure(
        self,
        trial_id: int,
        *,
        reason: str,
        attempts: int,
        provenance: Mapping[str, object],
    ) -> tuple[TrialRecord, FailureDecision]:
        trial = self._get_trial_or_raise(trial_id)
        decision = self.resolve_failure_action(
            reason=reason,
            attempts=attempts,
            policy=trial.failure_policy or DEFAULT_FAILURE_POLICY.to_dict(),
        )
        resume = dict(trial.resume or {})
        resume["last_failure"] = decision.to_dict()
        resume["resume_allowed"] = decision.retry_allowed
        updated = self.transition_trial(
            trial_id,
            decision.next_status,
            provenance=provenance,
            resume=resume,
        )
        return updated, decision

    def resolve_failure_action(
        self,
        *,
        reason: str,
        attempts: int,
        policy: FailurePolicy | Mapping[str, object] | None = None,
    ) -> FailureDecision:
        failure_policy = policy if isinstance(policy, FailurePolicy) else FailurePolicy.from_mapping(policy)
        reason_key = reason.strip()
        retryable = set(failure_policy.retryable_reasons)
        no_retry = set(failure_policy.no_retry_reasons)
        recovery_actions = dict(failure_policy.recovery_actions or {})
        if reason_key in retryable and attempts < failure_policy.max_retries:
            action = "retry"
            retry_allowed = True
        elif reason_key in no_retry or reason_key in retryable:
            action = "no_retry"
            retry_allowed = False
        else:
            action = "no_retry"
            retry_allowed = False
        recovery_action = recovery_actions.get(reason_key, f"review_failure_reason:{reason_key}")
        return FailureDecision(
            reason=reason_key,
            attempts=attempts,
            action=action,
            retry_allowed=retry_allowed,
            max_retries=failure_policy.max_retries,
            recovery_action=recovery_action,
            next_status="blocked",
        )

    def create_activity(
        self,
        campaign_id: int,
        activity_type: str,
        *,
        provenance: Mapping[str, object],
        status: str = "created",
        workload_run_id: int | None = None,
        trial_id: int | None = None,
        command: Mapping[str, object] = _EMPTY_JSON,
        environment: Mapping[str, object] = _EMPTY_JSON,
        inputs: Mapping[str, object] = _EMPTY_JSON,
        outputs: Mapping[str, object] = _EMPTY_JSON,
        failure_policy: FailurePolicy | Mapping[str, object] | None = None,
    ) -> ActivityRecord:
        _validate_state(status, ACTIVITY_STATES, kind="activity")
        provenance_payload = _require_provenance(provenance, context="activity creation")
        self._validate_parent_ids(campaign_id=campaign_id, workload_run_id=workload_run_id, trial_id=trial_id)
        failure_payload = self._failure_policy_payload(failure_policy)
        now = _now_iso()
        cursor = self._connection().execute(
            """
            INSERT INTO activities(
                campaign_id, workload_run_id, trial_id, activity_type, status,
                command_json, environment_json, inputs_json, outputs_json,
                provenance_json, failure_policy_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                workload_run_id,
                trial_id,
                activity_type,
                status,
                _json_dumps(command),
                _json_dumps(environment),
                _json_dumps(inputs),
                _json_dumps(outputs),
                _json_dumps(provenance_payload),
                _json_dumps(failure_payload),
                now,
                now,
            ),
        )
        self._connection().commit()
        return self._get_activity_or_raise(_lastrowid(cursor))

    def transition_activity(self, activity_id: int, status: str, *, provenance: Mapping[str, object]) -> ActivityRecord:
        provenance_payload = _require_provenance(provenance, context="activity transition")
        activity = self._get_activity_or_raise(activity_id)
        _validate_transition(
            kind="activity",
            current=activity.status,
            target=status,
            states=ACTIVITY_STATES,
            transitions=ACTIVITY_TRANSITIONS,
        )
        _ = self._connection().execute(
            "UPDATE activities SET status = ?, provenance_json = ?, updated_at = ? WHERE activity_id = ?",
            (status, _json_dumps(provenance_payload), _now_iso(), activity_id),
        )
        self._connection().commit()
        return self._get_activity_or_raise(activity_id)

    def register_artifact_ref(
        self,
        *,
        campaign_id: int,
        path: str,
        schema_id: str,
        schema_version: str,
        content_hash: str,
        content_hash_alg: str = "sha256",
        producing_activity_id: int | None = None,
        consuming_activity_ids: Sequence[int] = (),
        workload_run_id: int | None = None,
        trial_id: int | None = None,
        scope: str = "campaign",
        metadata: Mapping[str, object] = _EMPTY_JSON,
    ) -> ArtifactRef:
        if scope not in {"campaign", "workload_run", "trial"}:
            raise ValueError("artifact scope must be campaign, workload_run, or trial")
        if scope == "workload_run" and workload_run_id is None:
            raise ValueError("workload_run-scoped artifacts require workload_run_id")
        if scope == "trial" and trial_id is None:
            raise ValueError("trial-scoped artifacts require trial_id")
        resolved_workload_run_id = self._validate_parent_ids(
            campaign_id=campaign_id,
            workload_run_id=workload_run_id,
            trial_id=trial_id,
        )
        if scope == "trial" and workload_run_id is None:
            workload_run_id = resolved_workload_run_id
        if producing_activity_id is not None:
            activity = self._get_activity_or_raise(producing_activity_id)
            if activity.campaign_id != campaign_id:
                raise ValueError("producing activity campaign_id does not match artifact campaign_id")
        for activity_id in consuming_activity_ids:
            activity = self._get_activity_or_raise(int(activity_id))
            if activity.campaign_id != campaign_id:
                raise ValueError("consuming activity campaign_id does not match artifact campaign_id")
        now = _now_iso()
        cursor = self._connection().execute(
            """
            INSERT INTO artifact_refs(
                campaign_id, workload_run_id, trial_id, path, schema_id, schema_version,
                content_hash, content_hash_alg, producing_activity_id,
                consuming_activity_ids_json, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                workload_run_id,
                trial_id,
                path,
                schema_id,
                schema_version,
                content_hash,
                content_hash_alg,
                producing_activity_id,
                _json_list_dumps(consuming_activity_ids),
                _json_dumps(metadata),
                now,
            ),
        )
        self._connection().commit()
        return self._get_artifact_ref_or_raise(_lastrowid(cursor))

    def list_artifact_refs(
        self,
        *,
        campaign_id: int | None = None,
        workload_run_id: int | None = None,
        trial_id: int | None = None,
    ) -> list[ArtifactRef]:
        where: list[str] = []
        values: list[object] = []
        if campaign_id is not None:
            where.append("campaign_id = ?")
            values.append(campaign_id)
        if workload_run_id is not None:
            where.append("workload_run_id = ?")
            values.append(workload_run_id)
        if trial_id is not None:
            where.append("trial_id = ?")
            values.append(trial_id)
        sql = """
            SELECT artifact_ref_id, campaign_id, workload_run_id, trial_id, path,
                   schema_id, schema_version, content_hash, content_hash_alg,
                   producing_activity_id, consuming_activity_ids_json, metadata_json, created_at
            FROM artifact_refs
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY artifact_ref_id"
        rows = cast(list[sqlite3.Row], self._connection().execute(sql, values).fetchall())
        return [_artifact_from_row(row) for row in rows]

    def list_activities(
        self,
        *,
        campaign_id: int | None = None,
        workload_run_id: int | None = None,
        trial_id: int | None = None,
    ) -> list[ActivityRecord]:
        where: list[str] = []
        values: list[object] = []
        if campaign_id is not None:
            where.append("campaign_id = ?")
            values.append(campaign_id)
        if workload_run_id is not None:
            where.append("workload_run_id = ?")
            values.append(workload_run_id)
        if trial_id is not None:
            where.append("trial_id = ?")
            values.append(trial_id)
        sql = """
            SELECT activity_id, campaign_id, workload_run_id, trial_id, activity_type, status,
                   command_json, environment_json, inputs_json, outputs_json, provenance_json,
                   failure_policy_json, created_at, updated_at
            FROM activities
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY activity_id"
        rows = cast(list[sqlite3.Row], self._connection().execute(sql, values).fetchall())
        return [_activity_from_row(row) for row in rows]

    def resume_trial(self, trial_id: int) -> ResumePlan:
        trial = self._get_trial_or_raise(trial_id)
        campaign = self._get_campaign_or_raise(trial.campaign_id)
        workload = self.get_workload_run(trial.workload_run_id) if trial.workload_run_id is not None else None
        activities = tuple(self.list_activities(trial_id=trial_id))
        artifacts = tuple(self.list_artifact_refs(trial_id=trial_id))
        next_actions = self._next_actions_for_trial(trial)
        return ResumePlan(
            campaign=campaign,
            workload_run=workload,
            trial=trial,
            activities=activities,
            artifacts=artifacts,
            next_actions=next_actions,
        )

    def resume_workload_run(self, workload_run_id: int) -> ResumePlan:
        workload = self._get_workload_run_or_raise(workload_run_id)
        campaign = self._get_campaign_or_raise(workload.campaign_id)
        activities = tuple(self.list_activities(workload_run_id=workload_run_id))
        artifacts = tuple(self.list_artifact_refs(workload_run_id=workload_run_id))
        next_actions = self._next_actions_for_workload(workload)
        return ResumePlan(
            campaign=campaign,
            workload_run=workload,
            trial=None,
            activities=activities,
            artifacts=artifacts,
            next_actions=next_actions,
        )

    def query_trials(
        self,
        *,
        campaign_id: int | None = None,
        status: str | None = None,
        fidelity: str | None = None,
        workload_run_id: int | None = None,
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
        if workload_run_id is not None:
            where.append("workload_run_id = ?")
            values.append(workload_run_id)

        sql = """
            SELECT trial_id, campaign_id, workload_run_id, params_json, fidelity, status,
                   metrics_json, artifacts_json, provenance_json, failure_policy_json,
                   resume_json, generation_json, created_at, updated_at
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
            SELECT trial_id, campaign_id, workload_run_id, params_json, fidelity, status,
                   metrics_json, artifacts_json, provenance_json, failure_policy_json,
                   resume_json, generation_json, created_at, updated_at
            FROM trials
            WHERE trial_id = ?
            """,
            (trial_id,),
        ).fetchone())
        if row is None:
            raise KeyError(f"trial_id not found: {trial_id}")
        return _trial_from_row(row)

    def _get_workload_run_or_raise(self, workload_run_id: int) -> WorkloadRunRecord:
        workload = self.get_workload_run(workload_run_id)
        if workload is None:
            raise KeyError(f"workload_run_id not found: {workload_run_id}")
        return workload

    def _get_activity_or_raise(self, activity_id: int) -> ActivityRecord:
        row = cast(sqlite3.Row | None, self._connection().execute(
            """
            SELECT activity_id, campaign_id, workload_run_id, trial_id, activity_type, status,
                   command_json, environment_json, inputs_json, outputs_json, provenance_json,
                   failure_policy_json, created_at, updated_at
            FROM activities
            WHERE activity_id = ?
            """,
            (activity_id,),
        ).fetchone())
        if row is None:
            raise KeyError(f"activity_id not found: {activity_id}")
        return _activity_from_row(row)

    def _get_artifact_ref_or_raise(self, artifact_ref_id: int) -> ArtifactRef:
        row = cast(sqlite3.Row | None, self._connection().execute(
            """
            SELECT artifact_ref_id, campaign_id, workload_run_id, trial_id, path,
                   schema_id, schema_version, content_hash, content_hash_alg,
                   producing_activity_id, consuming_activity_ids_json, metadata_json, created_at
            FROM artifact_refs
            WHERE artifact_ref_id = ?
            """,
            (artifact_ref_id,),
        ).fetchone())
        if row is None:
            raise KeyError(f"artifact_ref_id not found: {artifact_ref_id}")
        return _artifact_from_row(row)

    def _validate_parent_ids(
        self,
        *,
        campaign_id: int,
        workload_run_id: int | None = None,
        trial_id: int | None = None,
    ) -> int | None:
        _ = self._get_campaign_or_raise(campaign_id)
        resolved_workload_run_id = workload_run_id
        if workload_run_id is not None:
            workload = self._get_workload_run_or_raise(workload_run_id)
            if workload.campaign_id != campaign_id:
                raise ValueError("workload_run_id does not belong to campaign_id")
        if trial_id is not None:
            trial = self._get_trial_or_raise(trial_id)
            if trial.campaign_id != campaign_id:
                raise ValueError("trial_id does not belong to campaign_id")
            if workload_run_id is not None and trial.workload_run_id != workload_run_id:
                raise ValueError("trial_id does not belong to workload_run_id")
            resolved_workload_run_id = trial.workload_run_id
        return resolved_workload_run_id

    def _failure_policy_payload(self, failure_policy: FailurePolicy | Mapping[str, object] | None) -> dict[str, object]:
        if failure_policy is None:
            return DEFAULT_FAILURE_POLICY.to_dict()
        if isinstance(failure_policy, FailurePolicy):
            return failure_policy.to_dict()
        return FailurePolicy.from_mapping(failure_policy).to_dict()

    def _next_actions_for_workload(self, workload: WorkloadRunRecord) -> tuple[str, ...]:
        actions = {
            "created": ("start_ingestion",),
            "ingesting": ("resume_ingestion",),
            "lowered": ("validate_lowered_workload",),
            "validated": ("mark_ready_for_step2",),
            "blocked": ("apply_recovery_policy",),
            "ready_for_step2": ("create_trials",),
        }
        return actions.get(workload.status, ("inspect_workload_state",))

    def _next_actions_for_trial(self, trial: TrialRecord) -> tuple[str, ...]:
        if trial.status == "blocked":
            resume = trial.resume or {}
            last_failure = cast(Mapping[str, object], resume.get("last_failure", {}))
            if last_failure.get("retry_allowed") is True:
                return ("apply_recovery_policy", "resume_trial")
            return ("inspect_blocker",)
        actions = {
            "generated": ("screen_candidate",),
            "screened": ("promote_or_reject",),
            "promoted": ("schedule_simulation",),
            "scheduled_for_sim": ("run_simulation",),
            "simulated": ("adjudicate_evidence",),
            "adjudicated": ("report_or_select",),
            "reported": ("rank_or_select",),
            "finalist": ("select_or_reject",),
            "selected": (),
            "rejected": (),
        }
        return actions.get(trial.status, ("inspect_trial_state",))
