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
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trials (
        trial_id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id INTEGER NOT NULL,
        params_json TEXT NOT NULL,
        fidelity TEXT NOT NULL,
        status TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        artifacts_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trials_campaign ON trials(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_trials_campaign_status ON trials(campaign_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_trials_campaign_status_fidelity ON trials(campaign_id, status, fidelity)",
]
