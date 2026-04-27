#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / 'model/qe_band_solver_model'
CATALOG_PATH = ROOT / 'docs/architecture/qe_ic_component_catalog_seed_v0.json'
GRAPH_SEEDS_PATH = ROOT / 'docs/architecture/qe_ic_graph_seed_templates_v0.json'
CMAKE_PATH = MODEL_DIR / 'CMakeLists.txt'
README_PATH = MODEL_DIR / 'README.md'
DEFAULT_OUTPUT = ROOT / 'docs/benchmarks/results/qe_ic_component_registry_v0.json'

COMPONENT_EXPECTED_CLASSES = {
    'system_container': ['DFTHybridSystem'],
    'host_controller': ['HostSCF'],
    'device_orchestrator': ['FPGAOrchestrator'],
    'chip_execution_facade': ['ChipTop'],
    'cluster_flow_executor': ['ClusterGraphExecutor'],
    'cim_operator_subchain': ['CIMEligibleOperatorSubchain'],
    'cim_array_core': ['CIMArrayCore'],
    'residue_3m_core': ['Residue3MCore'],
    'coefficient_accumulator': ['CoefficientAccumulator'],
    'row_merge_tree': ['RowMergeTree'],
    'context_loader': ['ContextLoader'],
    'digit_serial_input_boundary': ['DigitSerialInputBoundary'],
    'conjugate_sign_selector': ['ConjugateSignSelector'],
    'near_sram_coeff_buffer': ['NearSRAMCoeffBuffer'],
    'near_sram_row_buffer': ['NearSRAMRowBuffer'],
    'near_sram_support': ['NearSRAMSupport'],
    'reduction_closure_engine': ['ReductionClosureEngine'],
    'interconnect_fabric': ['Interconnect'],
    'cim_array': ['ClusterAOperatorSweep'],
    'fft_unit': ['FFTCompanion'],
    'reduction_unit': ['ClusterBReducedBuild'],
    'diag_unit': ['ClusterCHardwareDiag'],
    'refresh_unit': ['ClusterDRefreshResidual'],
    'resident_buffer': ['ResidentContextController'],
    'dma_channel': ['Interconnect'],
    'episode_controller': ['EpisodeController'],
    'command_scheduler': ['CommandScheduler'],
    'vector_diag_companion': ['VectorDiagCompanion'],
    'near_memory_domain': ['NearMemoryDomain'],
}

STRICT_BACKBONE_COMPONENTS = [
    'system_container',
    'host_controller',
    'device_orchestrator',
    'chip_execution_facade',
    'cluster_flow_executor',
    'interconnect_fabric',
    'cim_array',
    'fft_unit',
    'reduction_unit',
    'diag_unit',
    'refresh_unit',
    'resident_buffer',
    'dma_channel',
    'episode_controller',
    'command_scheduler',
    'vector_diag_companion',
    'near_memory_domain',
]

INTENTIONAL_UNMAPPED_ACTIVE_SOURCES = {
    'model/qe_band_solver_model/src/architecture_template.cpp': (
        'architecture-family scaffold and reporting helper, not a release-facing v0 component'
    ),
}


class RegistryValidationError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def load_cmake_active_sources(path: Path) -> list[str]:
    text = path.read_text(encoding='utf-8')
    match = re.search(r'add_executable\s*\(\s*qe_band_solver_model(?P<body>.*?)\n\)', text, re.S)
    if match is None:
        raise RegistryValidationError(f'cannot parse add_executable(qe_band_solver_model ...) from {path}')
    body = match.group('body')
    sources: list[str] = []
    for token in re.findall(r'([A-Za-z0-9_./-]+\.cpp)', body):
        source_path = (MODEL_DIR / token).resolve()
        sources.append(str(source_path.relative_to(ROOT)))
    return sorted(dict.fromkeys(sources))


def infer_header_from_anchor(anchor: str) -> str | None:
    if '/src/' not in anchor or not anchor.endswith('.cpp'):
        return None
    return anchor.replace('/src/', '/include/').rsplit('.', 1)[0] + '.hpp'


def extract_class_names(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding='utf-8')
    classes = re.findall(r'class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::|\{)', text)
    return sorted(dict.fromkeys(classes))


def classify_unmapped_active_source(path: str) -> dict[str, str]:
    if path in INTENTIONAL_UNMAPPED_ACTIVE_SOURCES:
        return {
            'path': path,
            'category': 'intentional_v0_container_gap',
            'note': INTENTIONAL_UNMAPPED_ACTIVE_SOURCES[path],
        }
    if '/src/onchip/' in path:
        return {
            'path': path,
            'category': 'future_component_seed_candidate',
            'note': 'active on-chip leaf is compiled today but not yet promoted into the v0 seed catalog',
        }
    if '/src/clusters/' in path:
        return {
            'path': path,
            'category': 'future_flow_component_seed_candidate',
            'note': 'active cluster/flow block is compiled today but not yet represented as a seed component',
        }
    return {
        'path': path,
        'category': 'runtime_support_not_seeded_yet',
        'note': 'active runtime/support source not yet mapped into the v0 component seed catalog',
    }


def build_component_entries(catalog: dict[str, Any], active_sources: list[str]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    active_source_set = set(active_sources)
    anchor_to_components: dict[str, list[str]] = {}
    entries: list[dict[str, Any]] = []
    for component in catalog.get('components', []):
        component_id = str(component['component_id'])
        anchor = str(component.get('brownfield_anchor', ''))
        header = infer_header_from_anchor(anchor)
        header_path = ROOT / header if header is not None else None
        header_classes = extract_class_names(header_path) if header_path is not None else []
        expected_classes = COMPONENT_EXPECTED_CLASSES.get(component_id, [])
        symbol_match_pass = bool(expected_classes) and any(cls in header_classes for cls in expected_classes)
        entry = {
            'component_id': component_id,
            'component_type': component['component_type'],
            'role': component['role'],
            'default_placement': component['default_placement'],
            'brownfield_anchor': anchor,
            'anchor_exists': (ROOT / anchor).exists(),
            'anchor_in_active_build': anchor in active_source_set,
            'inferred_header': header,
            'header_exists': bool(header_path and header_path.exists()),
            'header_classes': header_classes,
            'expected_classes': expected_classes,
            'symbol_match_pass': symbol_match_pass,
            'observability_keys': component.get('observability_keys', []),
            'supported_ops': component.get('supported_ops', []),
            'latency_model_ref': component.get('latency_model_ref'),
            'power_model_ref': component.get('power_model_ref'),
        }
        entries.append(entry)
        anchor_to_components.setdefault(anchor, []).append(component_id)
    anchor_to_components = {anchor: sorted(component_ids) for anchor, component_ids in anchor_to_components.items()}
    return entries, dict(sorted(anchor_to_components.items()))


def validate_graph_seed_templates(
    graph_seeds: dict[str, Any],
    component_ids: set[str],
) -> dict[str, Any]:
    per_template: list[dict[str, Any]] = []
    unresolved_refs: list[dict[str, str]] = []
    for template in graph_seeds.get('templates', []):
        seed_template_id = str(template.get('seed_template_id'))
        refs = [str(module.get('component_ref')) for module in template.get('modules', [])]
        missing = sorted(ref for ref in refs if ref not in component_ids)
        if missing:
            unresolved_refs.extend(
                {
                    'seed_template_id': seed_template_id,
                    'component_ref': ref,
                }
                for ref in missing
            )
        per_template.append(
            {
                'seed_template_id': seed_template_id,
                'module_component_refs': refs,
                'resolved_component_refs': sorted(ref for ref in refs if ref in component_ids),
                'unresolved_component_refs': missing,
                'resolution_pass': not missing,
            }
        )
    return {
        'templates': per_template,
        'all_component_refs_resolved': not unresolved_refs,
        'unresolved_component_refs': unresolved_refs,
    }


def build_registry(
    catalog: dict[str, Any],
    graph_seeds: dict[str, Any],
    active_sources: list[str],
    *,
    catalog_path: Path,
    graph_seeds_path: Path,
    cmake_path: Path,
    readme_path: Path,
) -> dict[str, Any]:
    component_entries, anchor_to_components = build_component_entries(catalog, active_sources)
    component_ids = {entry['component_id'] for entry in component_entries}
    graph_seed_validation = validate_graph_seed_templates(graph_seeds, component_ids)
    covered_anchors = {entry['brownfield_anchor'] for entry in component_entries}
    unmapped_active_sources = [
        classify_unmapped_active_source(path)
        for path in active_sources
        if path not in covered_anchors
    ]
    strict_backbone_anchors = sorted(
        {
            str(next(entry['brownfield_anchor'] for entry in component_entries if entry['component_id'] == component_id))
            for component_id in STRICT_BACKBONE_COMPONENTS
            if component_id in component_ids
        }
    )
    strict_backbone_coverage_pass = all(anchor in covered_anchors for anchor in strict_backbone_anchors)
    anchor_exists_pass = all(entry['anchor_exists'] for entry in component_entries)
    active_build_anchor_pass = all(entry['anchor_in_active_build'] for entry in component_entries)
    header_resolution_pass = all(entry['header_exists'] for entry in component_entries)
    symbol_match_pass = all(entry['symbol_match_pass'] for entry in component_entries)
    intentional_gap_count = sum(1 for item in unmapped_active_sources if item['category'] == 'intentional_v0_container_gap')
    future_expansion_count = len(unmapped_active_sources) - intentional_gap_count
    active_source_categories: dict[str, int] = {}
    for item in unmapped_active_sources:
        category = item['category']
        active_source_categories[category] = active_source_categories.get(category, 0) + 1
    validation = {
        'anchor_exists_pass': anchor_exists_pass,
        'active_build_anchor_pass': active_build_anchor_pass,
        'header_resolution_pass': header_resolution_pass,
        'symbol_match_pass': symbol_match_pass,
        'graph_component_ref_pass': graph_seed_validation['all_component_refs_resolved'],
        'strict_backbone_coverage_pass': strict_backbone_coverage_pass,
        'strict_backbone_component_count': len(strict_backbone_anchors),
        'component_count': len(component_entries),
        'active_build_source_count': len(active_sources),
        'shared_anchor_count': sum(1 for ids in anchor_to_components.values() if len(ids) > 1),
        'intentional_unmapped_active_source_count': intentional_gap_count,
        'future_catalog_expansion_candidate_count': future_expansion_count,
        'active_source_gap_categories': active_source_categories,
        'all_strict_checks_pass': all(
            [
                anchor_exists_pass,
                active_build_anchor_pass,
                header_resolution_pass,
                symbol_match_pass,
                graph_seed_validation['all_component_refs_resolved'],
                strict_backbone_coverage_pass,
            ]
        ),
    }
    return {
        'schema_version': 'qe_ic_component_registry_v0',
        'catalog_version': catalog.get('catalog_version'),
        'seed_template_version': graph_seeds.get('seed_template_version'),
        'catalog_path': str(catalog_path),
        'graph_seed_templates_path': str(graph_seeds_path),
        'cmake_path': str(cmake_path),
        'readme_path': str(readme_path),
        'active_build_sources': active_sources,
        'anchor_to_components': anchor_to_components,
        'strict_backbone_anchors': strict_backbone_anchors,
        'component_registry': component_entries,
        'graph_seed_validation': graph_seed_validation,
        'unmapped_active_sources': unmapped_active_sources,
        'validation': validation,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Build and validate a brownfield component registry for the QE IC graph-DSE seed catalog.'
    )
    parser.add_argument('--catalog', type=Path, default=CATALOG_PATH)
    parser.add_argument('--graph-seeds', type=Path, default=GRAPH_SEEDS_PATH)
    parser.add_argument('--cmake', type=Path, default=CMAKE_PATH)
    parser.add_argument('--readme', type=Path, default=README_PATH)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = load_json(args.catalog)
    graph_seeds = load_json(args.graph_seeds)
    active_sources = load_cmake_active_sources(args.cmake)
    registry = build_registry(
        catalog,
        graph_seeds,
        active_sources,
        catalog_path=args.catalog,
        graph_seeds_path=args.graph_seeds,
        cmake_path=args.cmake,
        readme_path=args.readme,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(registry, indent=2) + '\n', encoding='utf-8')
    summary = registry['validation']
    print(
        '[ok] wrote component registry: '
        f"{args.output} | strict_checks={summary['all_strict_checks_pass']} | "
        f"future_expansion_candidates={summary['future_catalog_expansion_candidate_count']}"
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
