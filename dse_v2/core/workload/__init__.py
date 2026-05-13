"""Profile-driven workload ingestion contracts for generic DSE."""

from dse_v2.core.workload.fixtures import (
    create_dynamic_custom_graph,
    create_graph_analytics_graph,
    create_sparse_spmv_graph,
    create_stencil_streaming_graph,
    create_tensor_chain_graph,
    create_vector_search_graph,
)
from dse_v2.core.workload.importers import (
    GenericJsonImporter,
    ImporterRegistry,
    WorkloadImporter,
    default_importer_registry,
)
from dse_v2.core.workload.characterization import WORKLOAD_CHARACTERIZATION_SCHEMA, characterize_workload
from dse_v2.core.workload.lowering import GraphLoweringResult, lower_compute_graph, write_graph_lowering_artifacts
from dse_v2.core.workload.package import WorkloadPackage, package_from_graph
from dse_v2.core.workload.profiles import (
    DEFAULT_WORKLOAD_PROFILES,
    DEFAULT_WORKLOAD_PROFILES as DEFAULT_WORKLOAD_WORKFLOWS,
    ProfileRegistry,
    WorkloadProfile,
    WorkloadProfile as WorkloadWorkflow,
    canonical_workload_family,
    default_profile_registry,
    default_profile_dict,
    get_workload_profile,
    required_coverage_from_profile,
    resolve_profile_metadata,
)
from dse_v2.core.workload.step1_workflow import (
    STEP1_INGESTION_REQUEST_SCHEMA,
    Step1HandoffError,
    Step1WorkflowResult,
    load_step1_handoff,
    load_step1_workload_package,
    run_step1_ingestion_request_workflow,
    run_step1_workload_ingestion_workflow,
    verify_step1_artifact_validation,
)
from dse_v2.core.workload.workflows import (
    default_workflow_registry,
    get_workload_workflow,
    required_coverage_from_workflow,
    resolve_workflow_metadata,
)

__all__ = [
    "GenericJsonImporter",
    "GraphLoweringResult",
    "ImporterRegistry",
    "ProfileRegistry",
    "Step1HandoffError",
    "Step1WorkflowResult",
    "STEP1_INGESTION_REQUEST_SCHEMA",
    "WorkloadImporter",
    "WorkloadPackage",
    "WORKLOAD_CHARACTERIZATION_SCHEMA",
    "WorkloadProfile",
    "WorkloadWorkflow",
    "DEFAULT_WORKLOAD_PROFILES",
    "DEFAULT_WORKLOAD_WORKFLOWS",
    "canonical_workload_family",
    "characterize_workload",
    "create_dynamic_custom_graph",
    "create_graph_analytics_graph",
    "create_sparse_spmv_graph",
    "create_stencil_streaming_graph",
    "create_tensor_chain_graph",
    "create_vector_search_graph",
    "default_importer_registry",
    "default_profile_dict",
    "default_profile_registry",
    "default_workflow_registry",
    "get_workload_profile",
    "get_workload_workflow",
    "lower_compute_graph",
    "load_step1_handoff",
    "load_step1_workload_package",
    "package_from_graph",
    "required_coverage_from_profile",
    "required_coverage_from_workflow",
    "resolve_profile_metadata",
    "resolve_workflow_metadata",
    "run_step1_ingestion_request_workflow",
    "run_step1_workload_ingestion_workflow",
    "verify_step1_artifact_validation",
    "write_graph_lowering_artifacts",
]
