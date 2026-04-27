from __future__ import annotations

from .interfaces import DesignPoint, EvaluationResult, WorkloadDescriptor


class ImplementationBackend:
    def evaluate(
        self,
        workload: WorkloadDescriptor,
        design_point: DesignPoint,
    ) -> EvaluationResult:
        return EvaluationResult(
            workload=workload,
            design_point=design_point,
            backend="implementation",
            result_status="reserved",
            source_kind="stub",
            metrics={},
            authority_scope="supporting_evidence_only",
            promotion_state="explain-only",
            final_public_family_winner=None,
            extra_fields={
                "claim_bearing": False,
                "stub_reason": "implementation_backend_reserved_for_future_non_stage_a_claims",
            },
        )
