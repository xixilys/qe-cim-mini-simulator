from __future__ import annotations

from pathlib import Path
import subprocess

from .interfaces import DesignPoint, EvaluationResult, WorkloadDescriptor


class SystemCBackend:
    def __init__(self, model_path: Path | str, dry_run: bool = True, allow_execute: bool = False) -> None:
        self.model_path = Path(model_path)
        self.dry_run = dry_run
        self.allow_execute = allow_execute

    def evaluate(
        self,
        workload: WorkloadDescriptor,
        design_point: DesignPoint,
    ) -> EvaluationResult:
        if self.dry_run:
            return EvaluationResult(
                workload=workload,
                design_point=design_point,
                backend="systemc",
                result_status="dry_run",
                source_kind="stub",
                metrics={},
                authority_scope="supporting_evidence_only",
                promotion_state="explain-only",
                final_public_family_winner=None,
                extra_fields={"backend_observability": {"executed": False}},
            )

        if not self.allow_execute:
            raise ValueError("SystemC execution requires explicit opt-in via allow_execute=True")

        completed = subprocess.run(
            [str(self.model_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        result_status = "executed" if completed.returncode == 0 else "model_error"
        return EvaluationResult(
            workload=workload,
            design_point=design_point,
            backend="systemc",
            result_status=result_status,
            source_kind="timed_functional_proxy",
            metrics={},
            authority_scope="supporting_evidence_only",
            promotion_state="explain-only",
            final_public_family_winner=None,
            extra_fields={
                "backend_observability": {
                    "executed": True,
                    "returncode": completed.returncode,
                }
            },
        )
