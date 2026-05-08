#!/usr/bin/env python3
"""
DSE Interface Validator

Validates artifacts against JSON Schema definitions at step boundaries.
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str]
    warnings: List[str]
    schema_version: str


class InterfaceValidator:
    """Validates DSE workflow interface artifacts."""

    SUPPORTED_FAMILIES = {"F1", "F2", "F3", "F4", "F5", "F6", "F7"}
    
    SCHEMAS = {
        "workload_profile_v1": "schemas/workload_profile_v1.json",
        "architecture_spec_v1": "schemas/architecture_spec_v1.json",
        "design_point_v1": "schemas/design_point_v1.json",
        "evaluation_config_v1": "schemas/evaluation_config_v1.json",
        "evaluation_result_v1": "schemas/evaluation_result_v1.json",
        "release_bundle_v1": "schemas/release_bundle_v1.json"
    }
    
    def __init__(self, schema_dir: Path = None):
        self.schema_dir = schema_dir or Path(__file__).parent.parent / "schemas"
        self._schemas = {}
        self._load_schemas()
    
    def _load_schemas(self):
        """Load all JSON schemas."""
        for name, path in self.SCHEMAS.items():
            schema_path = Path(path)
            if not schema_path.is_absolute():
                schema_path = self.schema_dir / schema_path.name
            if schema_path.exists():
                with open(schema_path) as f:
                    self._schemas[name] = json.load(f)
    
    def validate(self, artifact: Dict, schema_name: str) -> ValidationResult:
        """Validate artifact against schema."""
        errors = []
        warnings = []
        
        # Check schema version
        if "schema_version" not in artifact:
            errors.append("Missing schema_version field")
            return ValidationResult(False, errors, warnings, "")
        
        if artifact["schema_version"] != schema_name:
            errors.append(f"Schema version mismatch: expected {schema_name}, got {artifact['schema_version']}")
        
        # Basic structure validation
        schema = self._schemas.get(schema_name, {})
        required = schema.get("required", [])
        
        for field in required:
            if field not in artifact:
                errors.append(f"Missing required field: {field}")
        
        # Domain-specific validation
        if schema_name == "workload_profile_v1":
            self._validate_workload_profile(artifact, errors, warnings)
        elif schema_name == "architecture_spec_v1":
            self._validate_architecture_spec(artifact, errors, warnings)
        elif schema_name == "design_point_v1":
            self._validate_design_point(artifact, errors, warnings)
        elif schema_name == "evaluation_config_v1":
            self._validate_evaluation_config(artifact, errors, warnings)
        elif schema_name == "evaluation_result_v1":
            self._validate_evaluation_result(artifact, errors, warnings)
        elif schema_name == "release_bundle_v1":
            self._validate_release_bundle(artifact, errors, warnings)
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            schema_version=artifact.get("schema_version", "")
        )
    
    def _validate_workload_profile(self, artifact: Dict, errors: List, warnings: List):
        """Validate WorkloadProfile-specific constraints."""
        compute_graph = artifact.get("compute_graph", {})
        nodes = compute_graph.get("nodes", [])
        
        if not nodes:
            errors.append("compute_graph must have at least one node")
            return
        
        # Check dominance sum
        total_dominance = sum(n.get("dominance", 0) for n in nodes)
        if total_dominance > 1.01:  # Allow small floating point error
            errors.append(f"Total dominance {total_dominance} exceeds 1.0")
        
        # Check for dominant kernel
        max_dominance = max(n.get("dominance", 0) for n in nodes)
        if max_dominance < 0.3:
            warnings.append("No dominant kernel (max dominance < 0.3)")
        
        # Check precision consistency
        for node in nodes:
            flops = node.get("flops_per_call", 0)
            precision = node.get("precision", "FP64")
            if precision == "FP64" and flops > 1e15:
                warnings.append(f"Node {node['id']}: FP64 with very high FLOPs ({flops})")
    
    def _validate_architecture_spec(self, artifact: Dict, errors: List, warnings: List):
        """Validate ArchitectureSpec-specific constraints."""
        partition = artifact.get("partition", {})
        host_scope = set(partition.get("host_scope", []))
        device_scope = set(partition.get("device_scope", []))
        fallback_scope = set(partition.get("fallback_scope", []))
        
        # Check for overlaps
        if host_scope & device_scope:
            errors.append(f"host_scope and device_scope overlap: {host_scope & device_scope}")
        if host_scope & fallback_scope:
            errors.append(f"host_scope and fallback_scope overlap: {host_scope & fallback_scope}")
        if device_scope & fallback_scope:
            errors.append(f"device_scope and fallback_scope overlap: {device_scope & fallback_scope}")
        
        # Check family rationale
        if len(artifact.get("family_rationale", "")) < 10:
            warnings.append("family_rationale is very short (< 10 chars)")
    
    def _validate_design_point(self, artifact: Dict, errors: List, warnings: List):
        """Validate DesignPoint-specific constraints."""
        params = artifact.get("parameters", {})
        constraints = artifact.get("constraints", {})
        system_level = params.get("system_level", {})

        # Check parameter ranges
        family = artifact.get("family", system_level.get("family"))
        self.validate_family(family, errors)
        if "n_gemm_tiles" in system_level:
            n = system_level["n_gemm_tiles"]
            if n < 1 or n > 16:
                errors.append(f"n_gemm_tiles {n} out of range [1, 16]")
        
        # Check constraint satisfiability
        for key, value in constraints.items():
            if isinstance(value, (int, float)) and value < 0:
                errors.append(f"Constraint {key} is negative: {value}")
                break
        if "max_area_mm2" in constraints and "max_power_w" in constraints:
            if constraints["max_area_mm2"] <= 0 or constraints["max_power_w"] <= 0:
                errors.append("Constraints must be positive")

    def validate_family(self, family: Optional[str], errors: List[str]) -> bool:
        """Validate that a family is within the supported F1-F7 range."""
        if family is None:
            errors.append("Missing family")
            return False
        family_name = str(family)
        if family_name not in self.SUPPORTED_FAMILIES:
            errors.append(f"Unknown family: {family_name} (not supported; expected F1-F7)")
            return False
        return True
    
    def _validate_evaluation_config(self, artifact: Dict, errors: List, warnings: List):
        """Validate EvaluationConfig-specific constraints."""
        fidelity_config = artifact.get("fidelity_config", {})
        
        # Check monotonic cost
        costs = []
        for level in ["L0", "L1", "L2", "L3", "L4"]:
            if level in fidelity_config:
                costs.append(fidelity_config[level].get("max_cost_seconds", 0))
        
        for i in range(1, len(costs)):
            if costs[i] < costs[i-1]:
                errors.append(f"Cost not monotonic: L{i-1}={costs[i-1]} > L{i}={costs[i]}")
        
        # Check promotion policy
        policy = artifact.get("promotion_policy", {})
        threshold = policy.get("threshold_for_promotion", 0)
        if threshold < 0 or threshold > 1:
            errors.append(f"threshold_for_promotion {threshold} out of range [0, 1]")
    
    def _validate_evaluation_result(self, artifact: Dict, errors: List, warnings: List):
        """Validate EvaluationResult-specific constraints."""
        metrics = artifact.get("metrics", {})
        
        # Check non-negative metrics
        for key, value in metrics.items():
            if value < 0:
                errors.append(f"Metric {key} is negative: {value}")
        
        # Check accuracy
        accuracy = metrics.get("accuracy_vs_reference", 1.0)
        if accuracy < 0 or accuracy > 1:
            errors.append(f"accuracy_vs_reference {accuracy} out of range [0, 1]")
        
        # Check promotion consistency
        if artifact.get("promotion_recommendation") == "promote" and artifact.get("status") != "passed":
            errors.append("Cannot promote result that did not pass")
        
        # Check confidence intervals
        uncertainty = artifact.get("uncertainty", {})
        for key in ["latency_ci_95", "throughput_ci_95"]:
            if key in uncertainty:
                ci = uncertainty[key]
                if len(ci) != 2 or ci[0] >= ci[1]:
                    errors.append(f"Invalid confidence interval {key}: {ci}")
    
    def _validate_release_bundle(self, artifact: Dict, errors: List, warnings: List):
        """Validate ReleaseBundle-specific constraints."""
        pareto = set(artifact.get("pareto_frontier", []))
        results = set(artifact.get("evaluation_results", []))
        
        if not pareto:
            errors.append("pareto_frontier must be non-empty")
        
        if not pareto.issubset(results):
            errors.append("pareto_frontier contains hashes not in evaluation_results")
        
        # Check authority
        authority = artifact.get("authority", {})
        if authority.get("stage") == "B" and not authority.get("adjudicator_approval", False):
            errors.append("Stage B release requires adjudicator_approval=true")
        
        # Check confidence
        recommendation = artifact.get("recommendation", {}) or {}
        if "confidence" not in recommendation:
            errors.append("Missing recommendation confidence")
        else:
            confidence = recommendation["confidence"]
            if confidence < 0 or confidence > 1:
                errors.append(f"confidence {confidence} out of range [0, 1]")
    
    def compute_hash(self, artifact: Dict) -> str:
        """Compute SHA-256 hash of artifact."""
        content = json.dumps(artifact, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate DSE interface artifacts")
    parser.add_argument("--artifact", type=Path, required=True, help="Path to artifact JSON")
    parser.add_argument("--schema", type=str, required=True, help="Schema name (e.g., workload_profile_v1)")
    args = parser.parse_args()
    
    with open(args.artifact) as f:
        artifact = json.load(f)
    
    validator = InterfaceValidator()
    result = validator.validate(artifact, args.schema)
    
    print(f"Validation: {'PASSED' if result.valid else 'FAILED'}")
    print(f"Schema: {result.schema_version}")
    
    if result.errors:
        print("\nErrors:")
        for error in result.errors:
            print(f"  ❌ {error}")
    
    if result.warnings:
        print("\nWarnings:")
        for warning in result.warnings:
            print(f"  ⚠️  {warning}")
    
    if result.valid:
        artifact_hash = validator.compute_hash(artifact)
        print(f"\nArtifact hash: {artifact_hash}")
    
    return 0 if result.valid else 1


if __name__ == "__main__":
    exit(main())
