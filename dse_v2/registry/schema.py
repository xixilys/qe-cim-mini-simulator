#!/usr/bin/env python3
"""SQLite schema for persistent DSE experiment registries."""

from __future__ import annotations


CAMPAIGN_SPEC_REQUIRED_FIELDS = (
    "campaign_id",
    "purpose",
    "families_primary",
    "families_conditional",
    "main_cases",
    "anchor_cases",
    "coverage_cases",
    "generalization_cases",
    "design_axes",
    "objectives",
    "required_gates",
    "expected_outputs",
)


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS campaigns (
        campaign_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'created',
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workload_runs (
        workload_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id INTEGER NOT NULL,
        workload_ref_json TEXT NOT NULL,
        status TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        failure_policy_json TEXT NOT NULL,
        resume_json TEXT NOT NULL,
        blockers_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trials (
        trial_id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id INTEGER NOT NULL,
        workload_run_id INTEGER,
        params_json TEXT NOT NULL,
        fidelity TEXT NOT NULL,
        status TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        artifacts_json TEXT NOT NULL,
        provenance_json TEXT NOT NULL DEFAULT '{}',
        failure_policy_json TEXT NOT NULL DEFAULT '{}',
        resume_json TEXT NOT NULL DEFAULT '{}',
        generation_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
        FOREIGN KEY (workload_run_id) REFERENCES workload_runs(workload_run_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activities (
        activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id INTEGER NOT NULL,
        workload_run_id INTEGER,
        trial_id INTEGER,
        activity_type TEXT NOT NULL,
        status TEXT NOT NULL,
        command_json TEXT NOT NULL,
        environment_json TEXT NOT NULL,
        inputs_json TEXT NOT NULL,
        outputs_json TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        failure_policy_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
        FOREIGN KEY (workload_run_id) REFERENCES workload_runs(workload_run_id) ON DELETE SET NULL,
        FOREIGN KEY (trial_id) REFERENCES trials(trial_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artifact_refs (
        artifact_ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id INTEGER NOT NULL,
        workload_run_id INTEGER,
        trial_id INTEGER,
        path TEXT NOT NULL,
        schema_id TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        content_hash_alg TEXT NOT NULL,
        producing_activity_id INTEGER,
        consuming_activity_ids_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
        FOREIGN KEY (workload_run_id) REFERENCES workload_runs(workload_run_id) ON DELETE SET NULL,
        FOREIGN KEY (trial_id) REFERENCES trials(trial_id) ON DELETE SET NULL,
        FOREIGN KEY (producing_activity_id) REFERENCES activities(activity_id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_workload_runs_campaign ON workload_runs(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_workload_runs_campaign_status ON workload_runs(campaign_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_trials_campaign ON trials(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_trials_workload_run ON trials(workload_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_trials_campaign_status ON trials(campaign_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_trials_campaign_status_fidelity ON trials(campaign_id, status, fidelity)",
    "CREATE INDEX IF NOT EXISTS idx_activities_campaign ON activities(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_activities_trial ON activities(trial_id)",
    "CREATE INDEX IF NOT EXISTS idx_artifact_refs_campaign ON artifact_refs(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_artifact_refs_workload_run ON artifact_refs(workload_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_artifact_refs_trial ON artifact_refs(trial_id)",
]


SCHEMA_MIGRATIONS = {
    "campaigns": {
        "status": "ALTER TABLE campaigns ADD COLUMN status TEXT NOT NULL DEFAULT 'created'",
    },
    "trials": {
        "workload_run_id": "ALTER TABLE trials ADD COLUMN workload_run_id INTEGER",
        "provenance_json": "ALTER TABLE trials ADD COLUMN provenance_json TEXT NOT NULL DEFAULT '{}'",
        "failure_policy_json": "ALTER TABLE trials ADD COLUMN failure_policy_json TEXT NOT NULL DEFAULT '{}'",
        "resume_json": "ALTER TABLE trials ADD COLUMN resume_json TEXT NOT NULL DEFAULT '{}'",
        "generation_json": "ALTER TABLE trials ADD COLUMN generation_json TEXT NOT NULL DEFAULT '{}'",
    },
}
