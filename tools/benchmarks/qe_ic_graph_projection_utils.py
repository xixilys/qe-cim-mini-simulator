from __future__ import annotations

"""Pure projection helper boundary for QE IC benchmark graph adapters.

This module intentionally contains only import-safe constants, lightweight types,
and explicit schema-aware adapters shared by the benchmark-layer checker and
frontdoor scripts. It does not own consumer formatting or runtime-side code.
"""

from collections.abc import Mapping
from typing import Any, NamedTuple, TypedDict


JsonMapping = Mapping[str, Any]

DESIGN_POINT_AUTHORITY_KEYS = (
    'family',
    'diag_policy',
    'offload_scope',
    'resident_policy',
    'partition_strategy',
)

SYSTEM_LEVEL_V1_ADAPTER_ID = 'system_level_v1'
SYSTEM_LEVEL_V1_GRAPH_SCHEMA_VERSION = 'qe_ic_graph_schema_system_level_v1'
SYSTEM_LEVEL_V1_SHARED_JOIN_KEY_EXCLUSIONS = frozenset(DESIGN_POINT_AUTHORITY_KEYS)
SYSTEM_LEVEL_V1_REQUIRED_SHARED_JOIN_KEYS = (
    'fairness_policy_id',
    'observability_contract_id',
    'qe_tolerance_schema_id',
    'workload_group_id',
    'workload_id',
)
SYSTEM_LEVEL_V1_CLUSTER_STAGE_ORDER = (
    'operator_apply',
    'reduced_build',
    'diag',
    'refresh_residual',
)
SYSTEM_LEVEL_V1_REQUIRED_TOP_LEVEL_KEYS = frozenset(
    {
        'graph_schema_version',
        'graph_id',
        'workload_class',
        'join_keys',
        'modules',
        'flows',
        'placement',
        'constraints',
    }
)
SYSTEM_LEVEL_V1_COMPONENT_REF_ALIASES = {
    'system_container': 'system_container',
    'host_scf_controller': 'host_scf_controller',
    'policy_planner': 'policy_planner',
    'outer_state_update_engine': 'outer_state_update_engine',
    'host_diag_assist': 'host_diag_assist',
    'host_memory_window': 'host_memory_window',
    'transfer_fabric': 'transfer_fabric',
    'device_runtime': 'device_runtime',
    'hardware_datapath_container': 'hardware_datapath_container',
    'episode_schedule_controller': 'episode_schedule_controller',
    'residency_near_memory_subsystem': 'residency_near_memory_subsystem',
    'operator_apply_engine': 'operator_apply_engine',
    'fft_support_unit': 'fft_support_unit',
    'reduced_build_closure_unit': 'reduced_build_closure_unit',
    'diag_fallback_unit': 'diag_fallback_unit',
    'refresh_residual_unit': 'refresh_residual_unit',
}
SYSTEM_LEVEL_V1_STAGE_ID_ALIASES = {
    'rho_to_Veff': (),
    'resident_preload': (),
    'operator_apply_to_reduced_build': ('operator_apply', 'reduced_build'),
    'diag': ('diag',),
    'refresh_residual_to_mix': ('refresh_residual',),
    'operator_apply_stage': ('operator_apply',),
    'reduced_build_stage': ('reduced_build',),
    'diag_stage': ('diag',),
    'refresh_residual_stage': ('refresh_residual',),
    'untracked_stage': (),
}

FRONTDOOR_V0_ADAPTER_ID = 'frontdoor_v0'
FRONTDOOR_V0_GRAPH_SCHEMA_VERSION = 'qe_ic_graph_schema_v0'
FRONTDOOR_V0_REQUIRED_TOP_LEVEL_KEYS = frozenset(
    {
        'graph_schema_version',
        'graph_id',
        'seed_template_id',
        'workload_class',
        'join_keys',
        'modules',
        'links',
        'flows',
        'placement',
        'estimation_profile',
        'constraints',
        'observability_requirements',
    }
)
FRONTDOOR_V0_COMPONENT_REF_ALIASES = {
    'system_container': 'system_container',
    'host_controller': 'host_controller',
    'dma_channel': 'dma_channel',
    'chip_execution_facade': 'chip_execution_facade',
    'cluster_flow_executor': 'cluster_flow_executor',
    'episode_controller': 'episode_controller',
    'command_scheduler': 'command_scheduler',
    'near_memory_domain': 'near_memory_domain',
    'near_sram_support': 'near_sram_support',
    'context_loader': 'context_loader',
    'digit_serial_input_boundary': 'digit_serial_input_boundary',
    'conjugate_sign_selector': 'conjugate_sign_selector',
    'cim_operator_subchain': 'cim_operator_subchain',
    'cim_array_core': 'cim_array_core',
    'residue_3m_core': 'residue_3m_core',
    'coefficient_accumulator': 'coefficient_accumulator',
    'near_sram_coeff_buffer': 'near_sram_coeff_buffer',
    'near_sram_row_buffer': 'near_sram_row_buffer',
    'row_merge_tree': 'row_merge_tree',
    'fft_unit': 'fft_unit',
    'cim_array': 'cim_array',
    'reduction_closure_engine': 'reduction_closure_engine',
    'reduction_unit': 'reduction_unit',
    'diag_unit': 'diag_unit',
    'vector_diag_companion': 'vector_diag_companion',
    'refresh_unit': 'refresh_unit',
}
FRONTDOOR_V0_CLUSTER_STAGE_COMPONENT_ALIASES = {
    'A': frozenset(
        {
            'near_memory_domain',
            'near_sram_support',
            'context_loader',
            'digit_serial_input_boundary',
            'conjugate_sign_selector',
            'cim_operator_subchain',
            'cim_array_core',
            'residue_3m_core',
            'coefficient_accumulator',
            'near_sram_coeff_buffer',
            'near_sram_row_buffer',
            'row_merge_tree',
            'fft_unit',
            'cim_array',
        }
    ),
    'B': frozenset({'reduction_closure_engine', 'reduction_unit'}),
    'C': frozenset({'diag_unit', 'vector_diag_companion'}),
    'D': frozenset({'refresh_unit'}),
}
FRONTDOOR_V0_LEAF_COMPONENT_ALIASES = frozenset(
    {
        'near_sram_support',
        'context_loader',
        'digit_serial_input_boundary',
        'conjugate_sign_selector',
        'cim_operator_subchain',
        'cim_array_core',
        'residue_3m_core',
        'coefficient_accumulator',
        'near_sram_coeff_buffer',
        'near_sram_row_buffer',
        'row_merge_tree',
        'reduction_closure_engine',
    }
)
FRONTDOOR_V0_PRIMARY_FLOW_ID = 'main'
FRONTDOOR_V0_LEAF_HOTPATH_FLOW_ID = 'leaf_hotpath_chain'


class GraphProjectionError(RuntimeError):
    pass


class DesignPoint(TypedDict):
    family: str
    diag_policy: str
    offload_scope: str
    resident_policy: str
    partition_strategy: str


class ProjectionBundle(TypedDict, total=False):
    projected_design_point: DesignPoint
    shared_join_keys: dict[str, Any]
    system_run_config_patch: dict[str, Any]


class FrontdoorExecutionPlanSummaryFields(TypedDict, total=False):
    requested_cluster_sequence: str
    resolved_cluster_sequence: str
    executed_cluster_sequence: str
    execution_plan_source: str
    sequence_constraints: str


class NormalizedGraphSemanticState(TypedDict):
    adapter_id: str
    graph_schema_version: str
    graph_frontdoor_mode: str
    graph_id: str
    graph_topology_style: str
    graph_module_count: int
    graph_flow_count: int
    graph_leaf_component_count: int
    graph_has_fft_unit: bool
    graph_has_reduction_unit: bool
    graph_has_diag_unit: bool
    graph_has_vector_diag_companion: bool
    graph_has_refresh_unit: bool
    graph_has_leaf_hotpath_flow: bool
    graph_prefers_diag_before_reduction: bool
    graph_prefers_refresh_before_diag: bool
    graph_requested_cluster_sequence: str
    graph_resolved_cluster_sequence: str
    graph_sequence_constraints: str


class GraphProjectionAdapterBoundary(NamedTuple):
    adapter_id: str
    graph_schema_version: str
    authority_keys: tuple[str, ...] = DESIGN_POINT_AUTHORITY_KEYS


SYSTEM_LEVEL_V1_BOUNDARY = GraphProjectionAdapterBoundary(
    adapter_id=SYSTEM_LEVEL_V1_ADAPTER_ID,
    graph_schema_version=SYSTEM_LEVEL_V1_GRAPH_SCHEMA_VERSION,
)

FRONTDOOR_V0_BOUNDARY = GraphProjectionAdapterBoundary(
    adapter_id=FRONTDOOR_V0_ADAPTER_ID,
    graph_schema_version=FRONTDOOR_V0_GRAPH_SCHEMA_VERSION,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GraphProjectionError(message)


def _require_mapping(value: Any, message: str) -> JsonMapping:
    _require(isinstance(value, Mapping), message)
    return value


def _require_list(value: Any, message: str) -> list[Any]:
    _require(isinstance(value, list), message)
    return value


def _require_non_empty_string(value: Any, message: str) -> str:
    if not isinstance(value, str) or not value:
        raise GraphProjectionError(message)
    return value


def _require_supported_schema(graph: JsonMapping, expected_schema_version: str, entry_point: str) -> None:
    actual_schema_version = graph.get('graph_schema_version')
    _require(
        actual_schema_version == expected_schema_version,
        f'{entry_point} requires graph_schema_version={expected_schema_version}, got {actual_schema_version!r}',
    )


def _require_top_level_keys(graph: JsonMapping, required_keys: frozenset[str], entry_point: str) -> None:
    missing = [key for key in sorted(required_keys) if key not in graph]
    _require(not missing, f'{entry_point} missing required keys: {", ".join(missing)}')


def _require_mapping_field(mapping: JsonMapping, key: str, entry_point: str) -> Any:
    if key not in mapping:
        raise GraphProjectionError(f'{entry_point} missing required field: {key}')
    return mapping[key]


def _string_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ''


def _normalize_component_refs(
    modules: list[Any],
    *,
    entry_point: str,
    id_key: str,
    schema_name: str,
    alias_map: Mapping[str, str],
) -> tuple[dict[str, str], set[str]]:
    id_to_component_ref: dict[str, str] = {}
    component_refs: set[str] = set()
    for module in modules:
        module_mapping = _require_mapping(module, f'{entry_point} module entries must be objects')
        module_id = _require_non_empty_string(module_mapping.get(id_key), f'{entry_point} module missing {id_key}')
        _require(module_id not in id_to_component_ref, f'{entry_point} duplicate {id_key}: {module_id}')
        component_alias = _require_non_empty_string(
            module_mapping.get('component_ref'),
            f'{entry_point} module {module_id} missing component_ref',
        )
        canonical_component_ref = alias_map.get(component_alias)
        _require(
            canonical_component_ref is not None,
            f'{entry_point} unknown {schema_name} component alias: {component_alias}',
        )
        resolved_component_ref = _require_non_empty_string(
            canonical_component_ref,
            f'{entry_point} unknown {schema_name} component alias: {component_alias}',
        )
        id_to_component_ref[module_id] = resolved_component_ref
        component_refs.add(resolved_component_ref)
    return id_to_component_ref, component_refs


def _validate_flow_steps(
    flows: list[Any],
    *,
    entry_point: str,
    step_key: str,
    flow_id_key: str,
) -> tuple[dict[str, list[str]], set[str]]:
    flow_steps_by_id: dict[str, list[str]] = {}
    flow_ids: set[str] = set()
    for flow in flows:
        flow_mapping = _require_mapping(flow, f'{entry_point} flow entries must be objects')
        flow_id = _require_non_empty_string(flow_mapping.get(flow_id_key), f'{entry_point} flow missing {flow_id_key}')
        _require(flow_id not in flow_steps_by_id, f'{entry_point} duplicate {flow_id_key}: {flow_id}')
        flow_ids.add(flow_id)
        steps = _require_list(flow_mapping.get(step_key), f'{entry_point} flow {flow_id} missing {step_key}')
        _require(len(steps) > 0, f'{entry_point} flow {flow_id} missing {step_key}')
        normalized_steps: list[str] = []
        for step in steps:
            normalized_steps.append(
                _require_non_empty_string(
                    step,
                    f'{entry_point} flow {flow_id} contains empty {step_key} entry',
                )
            )
        flow_steps_by_id[flow_id] = normalized_steps
    _require(len(flow_steps_by_id) > 0, f'{entry_point} requires at least one flow with {step_key}')
    return flow_steps_by_id, flow_ids


def _require_frontdoor_v0_primary_flow_steps(flow_steps_by_id: Mapping[str, list[str]], entry_point: str) -> list[str]:
    main_steps = flow_steps_by_id.get(FRONTDOOR_V0_PRIMARY_FLOW_ID)
    _require(
        main_steps is not None,
        f'{entry_point} requires {FRONTDOOR_V0_PRIMARY_FLOW_ID} flow for frontdoor_v0 graphs',
    )
    resolved_main_steps = flow_steps_by_id[FRONTDOOR_V0_PRIMARY_FLOW_ID]
    return list(resolved_main_steps)


def _first_index_for_component(main_steps: list[str], id_to_component_ref: Mapping[str, str], component_ref: str) -> int | None:
    for index, step in enumerate(main_steps):
        if id_to_component_ref.get(step) == component_ref:
            return index
    return None


def _topology_style(payload: JsonMapping) -> str:
    placement = payload.get('placement')
    if isinstance(placement, Mapping):
        style = placement.get('style')
        if isinstance(style, str) and style:
            return style
    return 'unset'


def normalize_frontdoor_v0_graph_payload(
    graph: JsonMapping,
    *,
    source_hint: str | None = None,
) -> dict[str, Any]:
    entry_point = 'normalize_frontdoor_v0_graph_payload'
    normalized = dict(graph)
    normalized.setdefault('graph_schema_version', FRONTDOOR_V0_GRAPH_SCHEMA_VERSION)
    if 'graph_id' not in normalized:
        graph_id = normalized.get('seed_template_id')
        if not isinstance(graph_id, str) or not graph_id:
            graph_id = source_hint
        graph_id = _require_non_empty_string(
            graph_id,
            f'{entry_point} requires graph_id or seed_template_id/source_hint for frontdoor_v0 graphs',
        )
        normalized['graph_id'] = graph_id
    _require_supported_schema(normalized, FRONTDOOR_V0_GRAPH_SCHEMA_VERSION, entry_point)
    _require_top_level_keys(normalized, FRONTDOOR_V0_REQUIRED_TOP_LEVEL_KEYS, entry_point)
    return normalized


def normalize_system_level_v1_semantic_state(graph: JsonMapping) -> NormalizedGraphSemanticState:
    entry_point = 'normalize_system_level_v1_semantic_state'
    _require_supported_schema(graph, SYSTEM_LEVEL_V1_GRAPH_SCHEMA_VERSION, entry_point)
    _require_top_level_keys(graph, SYSTEM_LEVEL_V1_REQUIRED_TOP_LEVEL_KEYS, entry_point)

    modules = _require_list(graph.get('modules'), f'{entry_point} requires modules list')
    flows = _require_list(graph.get('flows'), f'{entry_point} requires flows list')
    constraints = _require_mapping(graph.get('constraints'), f'{entry_point} requires constraints object')

    module_id_to_component_ref, component_refs = _normalize_component_refs(
        modules,
        entry_point=entry_point,
        id_key='module_id',
        schema_name=SYSTEM_LEVEL_V1_ADAPTER_ID,
        alias_map=SYSTEM_LEVEL_V1_COMPONENT_REF_ALIASES,
    )

    present_cluster_stages: set[str] = set()
    for flow in flows:
        flow_mapping = _require_mapping(flow, f'{entry_point} flow entries must be objects')
        flow_id = _require_non_empty_string(flow_mapping.get('flow_id'), f'{entry_point} flow missing flow_id')
        stage_id = _require_non_empty_string(
            flow_mapping.get('stage_id'),
            f'{entry_point} flow {flow_id} missing stage_id',
        )
        ordered_modules_value = flow_mapping.get('ordered_modules')
        if ordered_modules_value is not None:
            ordered_modules = _require_list(
                ordered_modules_value,
                f'{entry_point} flow {flow_id} missing ordered_modules',
            )
            _require(len(ordered_modules) > 0, f'{entry_point} flow {flow_id} missing ordered_modules')
            for module_id in ordered_modules:
                normalized_module_id = _require_non_empty_string(
                    module_id,
                    f'{entry_point} flow {flow_id} references unknown module_id: {module_id}',
                )
                _require(
                    normalized_module_id in module_id_to_component_ref,
                    f'{entry_point} flow {flow_id} references unknown module_id: {normalized_module_id}',
                )
        canonical_stage_aliases = SYSTEM_LEVEL_V1_STAGE_ID_ALIASES.get(stage_id)
        _require(
            canonical_stage_aliases is not None,
            f'{entry_point} unknown {SYSTEM_LEVEL_V1_ADAPTER_ID} stage alias: {stage_id}',
        )
        resolved_stage_aliases = SYSTEM_LEVEL_V1_STAGE_ID_ALIASES[stage_id]
        present_cluster_stages.update(resolved_stage_aliases)

    requested_cluster_sequence = ','.join(
        stage for stage in SYSTEM_LEVEL_V1_CLUSTER_STAGE_ORDER if stage in present_cluster_stages
    )
    sequence_rules = _require_list(
        constraints.get('host_fpga_split_rules', []),
        f'{entry_point} host_fpga_split_rules must be a list',
    ) + _require_list(
        constraints.get('fallback_rules', []),
        f'{entry_point} fallback_rules must be a list',
    )

    return {
        'adapter_id': SYSTEM_LEVEL_V1_ADAPTER_ID,
        'graph_schema_version': SYSTEM_LEVEL_V1_GRAPH_SCHEMA_VERSION,
        'graph_frontdoor_mode': 'system_level_graph_v1',
        'graph_id': _string_or_empty(graph.get('graph_id')),
        'graph_topology_style': _topology_style(graph),
        'graph_module_count': len(modules),
        'graph_flow_count': len(flows),
        'graph_leaf_component_count': 0,
        'graph_has_fft_unit': 'fft_support_unit' in component_refs,
        'graph_has_reduction_unit': 'reduced_build_closure_unit' in component_refs,
        'graph_has_diag_unit': 'diag_fallback_unit' in component_refs,
        'graph_has_vector_diag_companion': False,
        'graph_has_refresh_unit': 'refresh_residual_unit' in component_refs,
        'graph_has_leaf_hotpath_flow': False,
        'graph_prefers_diag_before_reduction': False,
        'graph_prefers_refresh_before_diag': False,
        'graph_requested_cluster_sequence': requested_cluster_sequence,
        'graph_resolved_cluster_sequence': 'A,B,C,D' if requested_cluster_sequence else '',
        'graph_sequence_constraints': ';'.join(str(rule) for rule in sequence_rules),
    }


def normalize_frontdoor_v0_semantic_state(
    graph: JsonMapping,
    *,
    source_hint: str | None = None,
) -> NormalizedGraphSemanticState:
    entry_point = 'normalize_frontdoor_v0_semantic_state'
    normalized_graph = normalize_frontdoor_v0_graph_payload(graph, source_hint=source_hint)
    modules = _require_list(normalized_graph.get('modules'), f'{entry_point} requires modules list')
    flows = _require_list(normalized_graph.get('flows'), f'{entry_point} requires flows list')

    instance_id_to_component_ref, component_refs = _normalize_component_refs(
        modules,
        entry_point=entry_point,
        id_key='instance_id',
        schema_name=FRONTDOOR_V0_ADAPTER_ID,
        alias_map=FRONTDOOR_V0_COMPONENT_REF_ALIASES,
    )
    flow_steps_by_id, flow_ids = _validate_flow_steps(
        flows,
        entry_point=entry_point,
        step_key='steps',
        flow_id_key='flow_id',
    )
    for flow_id, flow_steps in flow_steps_by_id.items():
        for step in flow_steps:
            _require(
                step in instance_id_to_component_ref,
                f'{entry_point} flow {flow_id} references unknown instance_id: {step}',
            )
    main_steps = _require_frontdoor_v0_primary_flow_steps(flow_steps_by_id, entry_point)

    cluster_stage_by_instance: dict[str, str] = {}
    for instance_id, component_ref in instance_id_to_component_ref.items():
        for cluster_stage, cluster_components in FRONTDOOR_V0_CLUSTER_STAGE_COMPONENT_ALIASES.items():
            if component_ref in cluster_components:
                cluster_stage_by_instance[instance_id] = cluster_stage
                break

    requested_cluster_sequence_list: list[str] = []
    for step in main_steps:
        cluster_stage = cluster_stage_by_instance.get(step)
        if cluster_stage is not None and cluster_stage not in requested_cluster_sequence_list:
            requested_cluster_sequence_list.append(cluster_stage)

    stage_token = {
        'B': 'B' if 'reduction_unit' in component_refs else 'B_bypass',
        'C': 'C' if 'diag_unit' in component_refs else 'C_bypass',
        'D': 'D' if 'refresh_unit' in component_refs else 'D_bypass',
    }
    resolved_cluster_sequence_list = ['A']
    for requested_stage in requested_cluster_sequence_list:
        if requested_stage == 'A':
            continue
        if requested_stage == 'B' and stage_token['B'] not in resolved_cluster_sequence_list:
            resolved_cluster_sequence_list.append(stage_token['B'])
        elif requested_stage == 'C':
            if stage_token['B'] not in resolved_cluster_sequence_list:
                resolved_cluster_sequence_list.append(stage_token['B'])
            if stage_token['C'] not in resolved_cluster_sequence_list:
                resolved_cluster_sequence_list.append(stage_token['C'])
        elif requested_stage == 'D':
            if stage_token['B'] not in resolved_cluster_sequence_list:
                resolved_cluster_sequence_list.append(stage_token['B'])
            if stage_token['C'] not in resolved_cluster_sequence_list:
                resolved_cluster_sequence_list.append(stage_token['C'])
            if stage_token['D'] not in resolved_cluster_sequence_list:
                resolved_cluster_sequence_list.append(stage_token['D'])
    for cluster_stage in ('B', 'C', 'D'):
        token = stage_token[cluster_stage]
        if token not in resolved_cluster_sequence_list:
            resolved_cluster_sequence_list.append(token)

    requested_cluster_sequence = '>'.join(requested_cluster_sequence_list)
    resolved_cluster_sequence = '>'.join(resolved_cluster_sequence_list)
    sequence_constraint_notes: list[str] = []
    if requested_cluster_sequence_list and requested_cluster_sequence_list != resolved_cluster_sequence_list:
        sequence_constraint_notes.append(f'requested={requested_cluster_sequence}')
        sequence_constraint_notes.append(f'resolved={resolved_cluster_sequence}')

    diag_index = _first_index_for_component(main_steps, instance_id_to_component_ref, 'diag_unit')
    reduction_index = _first_index_for_component(main_steps, instance_id_to_component_ref, 'reduction_unit')
    refresh_index = _first_index_for_component(main_steps, instance_id_to_component_ref, 'refresh_unit')

    return {
        'adapter_id': FRONTDOOR_V0_ADAPTER_ID,
        'graph_schema_version': FRONTDOOR_V0_GRAPH_SCHEMA_VERSION,
        'graph_frontdoor_mode': 'frontdoor_graph_v0',
        'graph_id': _string_or_empty(normalized_graph.get('graph_id')),
        'graph_topology_style': _topology_style(normalized_graph),
        'graph_module_count': len(modules),
        'graph_flow_count': len(flows),
        'graph_leaf_component_count': sum(
            1 for component_ref in component_refs if component_ref in FRONTDOOR_V0_LEAF_COMPONENT_ALIASES
        ),
        'graph_has_fft_unit': 'fft_unit' in component_refs,
        'graph_has_reduction_unit': 'reduction_unit' in component_refs,
        'graph_has_diag_unit': 'diag_unit' in component_refs,
        'graph_has_vector_diag_companion': 'vector_diag_companion' in component_refs,
        'graph_has_refresh_unit': 'refresh_unit' in component_refs,
        'graph_has_leaf_hotpath_flow': FRONTDOOR_V0_LEAF_HOTPATH_FLOW_ID in flow_ids,
        'graph_prefers_diag_before_reduction': (
            diag_index is not None and reduction_index is not None and diag_index < reduction_index
        ),
        'graph_prefers_refresh_before_diag': (
            refresh_index is not None and diag_index is not None and refresh_index < diag_index
        ),
        'graph_requested_cluster_sequence': requested_cluster_sequence,
        'graph_resolved_cluster_sequence': resolved_cluster_sequence,
        'graph_sequence_constraints': ' | '.join(sequence_constraint_notes),
    }


def project_system_level_v1_design_point(graph: JsonMapping) -> DesignPoint:
    entry_point = 'project_system_level_v1_design_point'
    _require_supported_schema(graph, SYSTEM_LEVEL_V1_GRAPH_SCHEMA_VERSION, entry_point)
    join_keys = _require_mapping(
        graph.get('join_keys'),
        f'{entry_point} requires join_keys object',
    )
    return {
        'family': _require_mapping_field(join_keys, 'family', entry_point),
        'diag_policy': _require_mapping_field(join_keys, 'diag_policy', entry_point),
        'offload_scope': _require_mapping_field(join_keys, 'offload_scope', entry_point),
        'resident_policy': _require_mapping_field(join_keys, 'resident_policy', entry_point),
        'partition_strategy': _require_mapping_field(join_keys, 'partition_strategy', entry_point),
    }


def project_system_level_v1_shared_join_keys(graph: JsonMapping) -> dict[str, Any]:
    entry_point = 'project_system_level_v1_shared_join_keys'
    _require_supported_schema(graph, SYSTEM_LEVEL_V1_GRAPH_SCHEMA_VERSION, entry_point)
    join_keys = _require_mapping(
        graph.get('join_keys'),
        f'{entry_point} requires join_keys object',
    )
    return {
        key: _require_mapping_field(join_keys, key, entry_point)
        for key in SYSTEM_LEVEL_V1_REQUIRED_SHARED_JOIN_KEYS
    }


def project_system_level_v1_system_run_config_patch(graph: JsonMapping) -> dict[str, Any]:
    entry_point = 'project_system_level_v1_system_run_config_patch'
    semantic_state = normalize_system_level_v1_semantic_state(graph)
    workload_class = _require_mapping(
        graph.get('workload_class'),
        f'{entry_point} requires workload_class object',
    )
    signature_hints = _require_mapping(
        workload_class.get('signature_hints', {}),
        f'{entry_point} signature_hints must be an object',
    )
    join_keys = _require_mapping(
        graph.get('join_keys'),
        f'{entry_point} requires join_keys object',
    )
    patch = {
        'software_family': _require_mapping_field(workload_class, 'software_family', entry_point),
        'flow_family': _require_mapping_field(workload_class, 'flow_family', entry_point),
        'case_id': _require_mapping_field(workload_class, 'workload_id', entry_point),
        'architecture_family': _require_mapping_field(join_keys, 'family', entry_point),
        'projector_pressure': signature_hints.get('projector_pressure', ''),
        'generalized_ratio_bucket': signature_hints.get('generalized_ratio_bucket', ''),
        'diag_dominance': signature_hints.get('diag_dominance', ''),
        'fft_grid_pressure': signature_hints.get('fft_grid_pressure', ''),
        'offload_scope_override': _require_mapping_field(join_keys, 'offload_scope', entry_point),
        'resident_policy_override': _require_mapping_field(join_keys, 'resident_policy', entry_point),
        'graph_frontdoor_mode': semantic_state['graph_frontdoor_mode'],
        'graph_id': semantic_state['graph_id'],
        'graph_topology_style': semantic_state['graph_topology_style'],
        'graph_module_count': semantic_state['graph_module_count'],
        'graph_flow_count': semantic_state['graph_flow_count'],
        'graph_leaf_component_count': semantic_state['graph_leaf_component_count'],
        'graph_has_fft_unit': semantic_state['graph_has_fft_unit'],
        'graph_has_reduction_unit': semantic_state['graph_has_reduction_unit'],
        'graph_has_diag_unit': semantic_state['graph_has_diag_unit'],
        'graph_has_vector_diag_companion': semantic_state['graph_has_vector_diag_companion'],
        'graph_has_refresh_unit': semantic_state['graph_has_refresh_unit'],
        'graph_has_leaf_hotpath_flow': semantic_state['graph_has_leaf_hotpath_flow'],
        'graph_prefers_diag_before_reduction': semantic_state['graph_prefers_diag_before_reduction'],
        'graph_prefers_refresh_before_diag': semantic_state['graph_prefers_refresh_before_diag'],
        'graph_requested_cluster_sequence': semantic_state['graph_requested_cluster_sequence'],
        'graph_resolved_cluster_sequence': semantic_state['graph_resolved_cluster_sequence'],
        'graph_sequence_constraints': semantic_state['graph_sequence_constraints'],
    }
    signature_id = workload_class.get('signature_id')
    if isinstance(signature_id, str) and signature_id:
        patch['signature_id'] = signature_id
    return patch


def derive_frontdoor_v0_execution_hints(graph: JsonMapping) -> dict[str, Any]:
    semantic_state = normalize_frontdoor_v0_semantic_state(graph)
    join_keys = _require_mapping(
        normalize_frontdoor_v0_graph_payload(graph).get('join_keys'),
        'derive_frontdoor_v0_execution_hints requires join_keys object',
    )
    diag_policy = _string_or_empty(join_keys.get('diag_policy'))
    return {
        'graph_id': semantic_state['graph_id'],
        'topology_style': semantic_state['graph_topology_style'],
        'graph_module_count': semantic_state['graph_module_count'],
        'graph_flow_count': semantic_state['graph_flow_count'],
        'leaf_component_count': semantic_state['graph_leaf_component_count'],
        'has_fft_unit': semantic_state['graph_has_fft_unit'],
        'has_reduction_unit': semantic_state['graph_has_reduction_unit'],
        'has_diag_unit': semantic_state['graph_has_diag_unit'],
        'has_vector_diag_companion': semantic_state['graph_has_vector_diag_companion'],
        'has_refresh_unit': semantic_state['graph_has_refresh_unit'],
        'has_leaf_hotpath_flow': semantic_state['graph_has_leaf_hotpath_flow'],
        'prefers_diag_before_reduction': semantic_state['graph_prefers_diag_before_reduction'],
        'prefers_refresh_before_diag': semantic_state['graph_prefers_refresh_before_diag'],
        'requested_cluster_sequence': semantic_state['graph_requested_cluster_sequence'],
        'resolved_cluster_sequence': semantic_state['graph_resolved_cluster_sequence'],
        'sequence_constraint_notes': semantic_state['graph_sequence_constraints'],
        'enable_fft': semantic_state['graph_has_fft_unit'],
        'device_diag_max_dim': max(
            8,
            min(
                64,
                8
                + semantic_state['graph_module_count'] // 2
                + semantic_state['graph_flow_count'] * 2
                + (6 if semantic_state['graph_has_vector_diag_companion'] else 0)
                + (4 if semantic_state['graph_has_refresh_unit'] else 0),
            ),
        ),
        'allow_cpu_diag_fallback': (
            diag_policy != 'aggressive_device'
            and (semantic_state['graph_has_vector_diag_companion'] or diag_policy == 'cpu_only')
        ),
        'force_host_diag': diag_policy == 'cpu_only' and not semantic_state['graph_has_diag_unit'],
        'execution_mode': 'projected_design_point_only',
    }


def build_frontdoor_v0_execution_plan_summary(
    requested: str | None,
    resolved: str | None,
    *,
    executed: str | None = None,
    source: str | None = None,
    constraints: str | None = None,
) -> str | None:
    parts: list[str] = []
    if requested:
        parts.append(f'requested={requested}')
    if resolved:
        parts.append(f'resolved={resolved}')
    if executed:
        parts.append(f'executed={executed}')
    if source:
        parts.append(f'source={source}')
    if constraints:
        parts.append(f'constraints={constraints}')
    return ' | '.join(parts) if parts else None


def build_frontdoor_v0_execution_plan_summary_from_candidate(
    candidate_payload: JsonMapping | None,
) -> str | None:
    if not isinstance(candidate_payload, Mapping):
        return None
    profile = candidate_payload.get('graph_frontdoor_profile')
    if not isinstance(profile, Mapping):
        return None
    return build_frontdoor_v0_execution_plan_summary(
        profile.get('requested_cluster_sequence'),
        profile.get('resolved_cluster_sequence'),
        executed=profile.get('executed_cluster_sequence'),
        source=profile.get('execution_plan_source'),
        constraints=profile.get('sequence_constraints'),
    )


__all__ = [
    'DESIGN_POINT_AUTHORITY_KEYS',
    'DesignPoint',
    'FRONTDOOR_V0_ADAPTER_ID',
    'FRONTDOOR_V0_BOUNDARY',
    'FRONTDOOR_V0_COMPONENT_REF_ALIASES',
    'FRONTDOOR_V0_GRAPH_SCHEMA_VERSION',
    'FRONTDOOR_V0_LEAF_COMPONENT_ALIASES',
    'FrontdoorExecutionPlanSummaryFields',
    'GraphProjectionAdapterBoundary',
    'GraphProjectionError',
    'JsonMapping',
    'NormalizedGraphSemanticState',
    'ProjectionBundle',
    'SYSTEM_LEVEL_V1_ADAPTER_ID',
    'SYSTEM_LEVEL_V1_BOUNDARY',
    'SYSTEM_LEVEL_V1_COMPONENT_REF_ALIASES',
    'SYSTEM_LEVEL_V1_GRAPH_SCHEMA_VERSION',
    'SYSTEM_LEVEL_V1_REQUIRED_SHARED_JOIN_KEYS',
    'SYSTEM_LEVEL_V1_SHARED_JOIN_KEY_EXCLUSIONS',
    'SYSTEM_LEVEL_V1_STAGE_ID_ALIASES',
    'build_frontdoor_v0_execution_plan_summary',
    'build_frontdoor_v0_execution_plan_summary_from_candidate',
    'derive_frontdoor_v0_execution_hints',
    'normalize_frontdoor_v0_graph_payload',
    'normalize_frontdoor_v0_semantic_state',
    'normalize_system_level_v1_semantic_state',
    'project_system_level_v1_design_point',
    'project_system_level_v1_shared_join_keys',
    'project_system_level_v1_system_run_config_patch',
]
