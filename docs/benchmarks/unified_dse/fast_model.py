from __future__ import annotations

from .interfaces import DesignPoint, EvaluationResult, WorkloadDescriptor
from .stage_a_contracts import default_contract_fields


class FastModelBackend:
    def __init__(self, source_kind: str = "stub") -> None:
        self.source_kind = source_kind

    def evaluate(
        self,
        workload: WorkloadDescriptor,
        design_point: DesignPoint,
    ) -> EvaluationResult:
        return EvaluationResult(
            workload=workload,
            design_point=design_point,
            backend="fast_model",
            result_status="stub",
            source_kind=self.source_kind,
            metrics={"stub_metrics_present": True},
            authority_scope="supporting_evidence_only",
            promotion_state="explain-only",
            final_public_family_winner=None,
            extra_fields=default_contract_fields(
                workload=workload,
                design_point=design_point,
                backend="fast_model",
                source_kind=self.source_kind,
            ),
        )
