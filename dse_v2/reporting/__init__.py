"""Reporting helpers for generic DSE evidence artifacts."""

__all__ = [
    "CLAIM_VALIDATION_SCHEMA_VERSION",
    "REPORT_ARTIFACTS",
    "REPORT_SCHEMA_VERSION",
    "build_final_report",
    "generate_final_report_artifacts",
    "render_markdown_report",
    "validate_report_claims",
]


def __getattr__(name):
    if name in __all__:
        from . import final_report as _final_report

        return getattr(_final_report, name)
    raise AttributeError(name)
