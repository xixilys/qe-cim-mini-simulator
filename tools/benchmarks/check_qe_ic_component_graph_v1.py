#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from qe_ic_graph_projection_utils import (
    GraphProjectionError,
    project_system_level_v1_design_point,
    project_system_level_v1_shared_join_keys,
    project_system_level_v1_system_run_config_patch,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPONENT_CATALOG = ROOT / "docs/architecture/qe_ic_component_catalog_system_level_v1.json"
DEFAULT_GRAPH_SEED = ROOT / "docs/architecture/qe_ic_graph_seed_system_level_v1.json"

REQUIRED_JOIN_KEYS = {
    "family",
    "diag_policy",
    "offload_scope",
    "resident_policy",
    "partition_strategy",
    "workload_id",
    "workload_group_id",
    "qe_tolerance_schema_id",
    "fairness_policy_id",
    "observability_contract_id",
}

REQUIRED_COMPONENTS = {
    "system_container",
    "host_scf_controller",
    "device_runtime",
    "transfer_fabric",
    "hardware_datapath_container",
    "episode_schedule_controller",
    "residency_near_memory_subsystem",
    "operator_apply_engine",
    "reduced_build_closure_unit",
    "diag_fallback_unit",
    "refresh_residual_unit",
}

MODULE_TO_FLAG = {
    "fft_support_unit": "graph_has_fft_unit",
    "reduced_build_closure_unit": "graph_has_reduction_unit",
    "diag_fallback_unit": "graph_has_diag_unit",
    "refresh_residual_unit": "graph_has_refresh_unit",
}


class ValidationError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def component_index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components = catalog.get("components")
    if not isinstance(components, list):
        raise ValidationError("component catalog must contain non-empty components")
    require(len(components) > 0, "component catalog must contain non-empty components")
    index: dict[str, dict[str, Any]] = {}
    for component in components:
        require(isinstance(component, dict), "component entries must be objects")
        component_id = component.get("component_id")
        require(isinstance(component_id, str), "component_id must be a non-empty string")
        require(bool(component_id), "component_id must be a non-empty string")
        require(component_id not in index, f"duplicate component_id: {component_id}")
        index[component_id] = component
    return index


def validate_catalog(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    require(
        catalog.get("catalog_version") == "qe_ic_component_catalog_system_level_v1",
        "catalog_version must be qe_ic_component_catalog_system_level_v1",
    )
    index = component_index(catalog)
    missing = sorted(REQUIRED_COMPONENTS - set(index))
    require(not missing, f"component catalog missing required components: {', '.join(missing)}")
    for component_id, component in index.items():
        require("component_type" in component, f"component {component_id} missing component_type")
        require("role" in component, f"component {component_id} missing role")
        require("default_placement" in component, f"component {component_id} missing default_placement")
        require("brownfield_anchor" in component, f"component {component_id} missing brownfield_anchor")
        require("dse_surface" in component, f"component {component_id} missing dse_surface")
        require("sim_binding" in component, f"component {component_id} missing sim_binding")
    return index


def validate_modules(graph: dict[str, Any], index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    modules = graph.get("modules")
    if not isinstance(modules, list):
        raise ValidationError("graph_spec.modules must be a non-empty list")
    require(len(modules) > 0, "graph_spec.modules must be a non-empty list")
    seen_ids: set[str] = set()
    validated_modules: list[dict[str, Any]] = []
    for module in modules:
        require(isinstance(module, dict), "module entries must be objects")
        module_id = module.get("module_id")
        require(isinstance(module_id, str), "module_id must be a non-empty string")
        require(bool(module_id), "module_id must be a non-empty string")
        require(module_id not in seen_ids, f"duplicate module_id: {module_id}")
        seen_ids.add(module_id)
        component_ref = module.get("component_ref")
        require(component_ref in index, f"module {module_id} references unknown component_ref: {component_ref}")
        validated_modules.append(module)
    return validated_modules


def validate_links(graph: dict[str, Any], module_ids: set[str]) -> None:
    links = graph.get("links")
    if not isinstance(links, list):
        raise ValidationError("graph_spec.links must be a non-empty list")
    require(len(links) > 0, "graph_spec.links must be a non-empty list")
    for link in links:
        require(isinstance(link, dict), "link entries must be objects")
        link_id = link.get("link_id")
        require(isinstance(link_id, str), "link_id must be a non-empty string")
        require(bool(link_id), "link_id must be a non-empty string")
        src = link.get("src_module")
        dst = link.get("dst_module")
        require(src in module_ids, f"link {link_id} src_module unknown: {src}")
        require(dst in module_ids, f"link {link_id} dst_module unknown: {dst}")
        payload_kind = link.get("payload_kind")
        require(isinstance(payload_kind, str), f"link {link_id} missing payload_kind")
        require(bool(payload_kind), f"link {link_id} missing payload_kind")


def validate_flows(graph: dict[str, Any], module_ids: set[str]) -> None:
    flows = graph.get("flows")
    if not isinstance(flows, list):
        raise ValidationError("graph_spec.flows must be a non-empty list")
    require(len(flows) > 0, "graph_spec.flows must be a non-empty list")
    for flow in flows:
        require(isinstance(flow, dict), "flow entries must be objects")
        flow_id = flow.get("flow_id")
        require(isinstance(flow_id, str), "flow_id must be a non-empty string")
        require(bool(flow_id), "flow_id must be a non-empty string")
        ordered_modules = flow.get("ordered_modules")
        require(isinstance(ordered_modules, list), f"flow {flow_id} must contain ordered_modules")
        require(len(ordered_modules) > 0, f"flow {flow_id} must contain ordered_modules")
        for module_id in ordered_modules:
            require(module_id in module_ids, f"flow {flow_id} references unknown module: {module_id}")


def validate_graph(graph: dict[str, Any], index: dict[str, dict[str, Any]]) -> None:
    require(
        graph.get("graph_schema_version") == "qe_ic_graph_schema_system_level_v1",
        "graph_schema_version must be qe_ic_graph_schema_system_level_v1",
    )
    join_keys = graph.get("join_keys")
    if not isinstance(join_keys, dict):
        raise ValidationError("graph_spec.join_keys must be an object")
    missing_join_keys = sorted(REQUIRED_JOIN_KEYS - set(join_keys.keys()))
    require(not missing_join_keys, f"graph_spec.join_keys missing required fields: {', '.join(missing_join_keys)}")
    modules = validate_modules(graph, index)
    module_ids = {module["module_id"] for module in modules}
    validate_links(graph, module_ids)
    validate_flows(graph, module_ids)


def project_design_point(graph: dict[str, Any]) -> dict[str, Any]:
    return dict(project_system_level_v1_design_point(graph))


def project_shared_join_keys(graph: dict[str, Any]) -> dict[str, Any]:
    return project_system_level_v1_shared_join_keys(graph)


def project_system_run_config_patch(graph: dict[str, Any]) -> dict[str, Any]:
    return project_system_level_v1_system_run_config_patch(graph)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate QE IC v1 component catalog and graph seed, then print projection previews.")
    parser.add_argument("--component-catalog", type=Path, default=DEFAULT_COMPONENT_CATALOG)
    parser.add_argument("--graph-seed", type=Path, default=DEFAULT_GRAPH_SEED)
    parser.add_argument("--print-projection", action="store_true")
    args = parser.parse_args()

    try:
        catalog = load_json(args.component_catalog)
        graph = load_json(args.graph_seed)
        index = validate_catalog(catalog)
        validate_graph(graph, index)
        projected_design_point = project_design_point(graph)
        projected_system_run_config = project_system_run_config_patch(graph)
    except (OSError, json.JSONDecodeError, ValidationError, GraphProjectionError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1

    if args.print_projection:
        payload = {
            "projected_design_point": projected_design_point,
            "shared_join_keys": project_shared_join_keys(graph),
            "system_run_config_patch": projected_system_run_config,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
