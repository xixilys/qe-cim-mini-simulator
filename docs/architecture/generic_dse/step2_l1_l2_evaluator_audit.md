# Step2 L1/L2 Evaluator Evidence Audit and Rewrite Specification

Status: phase-1 audit deliverable
Date: 2026-05-13
Scope: Step2 candidate-generation evidence only

## 0. Executive verdict

The current Step2 L1/L2 path is useful as a deterministic candidate-generation prototype, but it is **not yet a research-validated performance model**.

- **L1** uses a roofline-style analytical bound plus local scheduling and energy heuristics. The roofline component can be treated as an **adapted model** from the Roofline paper, but the scheduler, power, confidence, and promotion scoring are repository-local heuristics.
- **L2** is named TLM, but the current implementation is a **custom Python formula estimator**. It is not a direct SystemC/TLM-2.0 implementation, not Aladdin, not Timeloop, and not gem5-Aladdin.
- **Promotion** uses hard-coded confidence, score, MAPE, and family thresholds. These are useful gates for controlling the prototype flow, but current formulas are **unsupported/custom heuristics** unless separately calibrated.
- **Step2 remains candidate-generation only**. Current L1/L2 artifacts must not be used for final ranking, validated speedup claims, or DFT/QE numerical correctness claims.

Phase-1 non-goals from the deep interview:

1. Do not change L1/L2 evaluator code.
2. Do not run Step3/SystemC/gem5 high-fidelity simulation.
3. Do not claim current L1/L2 are validated.
4. Do not evaluate DFT numerical correctness.

This document therefore audits the current state, gives literature-backed replacement candidates, and specifies the later rewrite without implementing it here.

## 1. What Step1 gives Step2 today

Step2 consumes serialized, generic Step1 workload artifacts and emits replayable candidate-generation artifacts. The Step2 module describes itself as the boundary between Step1 workload lowering and Step3+ simulation/evidence; it consumes serialized/generic Step1 artifacts, selects an auditable architecture instance, builds a replayable `DesignPoint`, runs mapping search, and writes artifacts that downstream simulation can reload without hidden Python state (`dse_v2/mapping/step2_workflow.py:1-8`).

The direct imports show Step2's input boundary:

- `ComputeGraph` from `dse_v2.core.ir.compute_graph` (`step2_workflow.py:39`).
- `GraphLoweringResult` / `lower_compute_graph` (`step2_workflow.py:40`).
- `WorkloadPackage` (`step2_workflow.py:41`).
- `load_step1_handoff` (`step2_workflow.py:42`).
- optional domain policy hints through `Step2DomainPolicyRegistry` / `Step2PolicyInput` (`step2_workflow.py:54-59`).

The persisted Step2 artifact list includes Step1-derived and Step2-generated artifacts (`step2_workflow.py:62-104`):

- `workload_package.json`
- `workload_graph.json`
- `graph_lowering_report.json`
- `executable_graph.json`
- mapping artifacts such as `mapping_legality_matrix.json`, `mapping_seed_set.json`, `mapping_candidate_records.json`, `mapping_selected_record.json`
- L1/L2 low-fidelity artifacts such as `l1_evaluation_result.json`, `l2_evaluation_result.json`, and promotion decisions
- Step3 queue metadata such as `architecture_candidate_set.json` and `step3_simulation_queue.json`

The architecture artifact records workload IDs, graph IDs, selected architecture, backend binding, full-workload eligibility, diagnostic boundary status, and candidate-only reasons (`step2_workflow.py:168-239`). The design-point config keeps replay metadata for the workload package, source graph, executable graph, architecture, mapping record, legality matrix, and L1/L2 artifacts, with `no_hidden_python_state_required: True` (`step2_workflow.py:1643-1728`).

## 2. Current Step2 search flow

Current Step2 candidate generation is a deterministic seed/beam screening flow, not a statistically optimized or literature-validated DSE search.

### 2.1 Architecture and mapping boundary

1. Step2 builds or selects an architecture instance from the architecture catalog.
2. It lowers the source graph into an executable graph and records full-workload eligibility and unsupported constructs.
3. It converts the selected architecture into a `SystemArchitecture` used by generic evaluators.
4. It builds a mapping legality matrix for every graph node and architecture target.
5. It generates seed mappings and screens them using simple latency/energy heuristics.
6. It selects/promotes a bounded set of mapping candidates for later high-fidelity evidence.

The mapping search module explicitly states that low-fidelity scores are candidate-generation signals only and trusted selection requires SystemC/gem5+SystemC evidence (`dse_v2/mapping/search.py:1-8`).

### 2.2 Mapping legality and seed generation

`build_legality_matrix()` checks whether each node can execute on each target, including operation support, precision support, local memory capacity, and route availability (`search.py:181-232`). `generate_seed_mappings()` emits:

- all-host baseline;
- all-accelerator legal placements;
- workflow-family balanced placement;
- streaming/locality placement;
- optional domain-policy seeds (`search.py:499-550`).

Policy hints can add phase-aware, dominant-phase offload, and host-visible review-safe seeds (`search.py:458-496`). This is the current seam for optional DFT policy influence, but the core mapping artifacts stay generic.

### 2.3 Mapping scoring

`screen_mapping()` estimates per-node latency as:

```text
node_latency_ms = max(
  estimated_flops / target_throughput,
  estimated_memory_bytes * 8 / 1e11
) * 1000
```

Then it adds a fixed movement penalty of `movement_mb * 0.002`, gives confidence `0.72` if legal and `0.35` otherwise, and ranks by `1 / latency * confidence` (`search.py:593-627`). This is a repository-local heuristic.

`run_mapping_search()` sorts legal candidates by promotion priority, predicted latency, and candidate ID; promotes the top beam; and records whether high-fidelity samples exist (`search.py:658-912`). If no high-fidelity simulation exists, convergence remains `awaiting_simulation`, and the feedback effect says high-fidelity simulation is required before trusted ranking update (`search.py:780-853`).

## 3. Current L1 algorithm

Current L1 is `EnhancedAnalyticalEvaluator` (`step2_workflow.py:667-677`, `step2_workflow.py:1038-1122`). Its source docstring says it uses roofline analysis, data movement, parallel task scheduling, and bandwidth bottleneck detection (`dse_v2/dse/analytical_evaluator.py:1-9`).

Algorithm components:

1. Build accelerator bandwidth matrix from peer and host links (`analytical_evaluator.py:82-102`).
2. Convert compute graph to a task graph (`analytical_evaluator.py:61-66`).
3. Perform roofline analysis per placed task (`analytical_evaluator.py:68-75`, `:104-158`):
   - arithmetic intensity = task FLOPs / task bytes;
   - compute bound = peak compute × efficiency;
   - memory bound = peak bandwidth × arithmetic intensity;
   - actual performance = min(compute bound, memory bound);
   - bottleneck = compute if compute bound <= memory bound else memory.
4. Schedule tasks in topological order with per-accelerator availability and dependency transfer times (`analytical_evaluator.py:160-270`).
5. Convert the execution timeline into latency, throughput, static-ish power, energy, compute efficiency, and fixed memory efficiency (`analytical_evaluator.py:272-313`).

Evidence-grade classification:

- The roofline bound is an **adapted model** from Williams, Waterman, and Patterson's Roofline model.
- The topological/resource-availability scheduler is a **custom implementation**. It may be reasonable for a prototype, but this report found no direct public-primary source embedded in code or docs.
- Power and energy estimates are **custom heuristics**. The code sums static power and adds `compute_power_per_flop * 1e12` per task start (`analytical_evaluator.py:286-296`), without a cited calibration source.
- Memory efficiency is currently hard-coded to `0.5` (`analytical_evaluator.py:309`). This is **unsupported/custom**.

## 4. Current L2 algorithm

Current L2 is `TLMEvaluator`, which wraps `PythonTLM` (`dse_v2/dse/tlm_evaluator.py:16-56`). `TLMEvaluator` converts a generic design point into a small architecture dictionary and extracts workload parameters from graph metadata or estimates them from graph total FLOPs/bytes (`tlm_evaluator.py:58-113`). It then calls `PythonTLM.run_episode()` and converts the result into a generic dict (`tlm_evaluator.py:115-137`).

`PythonTLM` is a formula model:

1. It reads family, tile counts, local memory, PCIe bandwidth, DRAM bandwidth, and workload dimensions (`python_tlm.py:40-54`).
2. It estimates dense compute FLOPs and solver FLOPs (`python_tlm.py:55-57`).
3. It estimates dense, solver, and host-device transfer times with `_compute_time_ms()` and `_transaction_time_ms()` (`python_tlm.py:58-79`, `:179-191`).
4. It applies family timing scales (`python_tlm.py:24-32`, `:81-87`).
5. It applies mapping penalty and dataflow speedup (`python_tlm.py:88-94`, `:193-218`).
6. It computes power, area, throughput, resource utilization, confidence, accuracy proxy, promotion score, and MAPE proxy (`python_tlm.py:95-121`).

Evidence-grade classification:

- The use of the name TLM is at most **conceptual inspiration** from transaction-level modeling. The current code does not implement the SystemC/TLM-2.0 standard interfaces, sockets, transport protocols, timing annotation semantics, or payload protocol.
- `_transaction_time_ms(bytes, bandwidth, transaction_bytes, latency_us)` is a simple bandwidth-plus-per-transaction-latency formula. It is not by itself SystemC/TLM-2.0.
- `FAMILY_TIMING_SCALE`, dense/solver constants, power/area formulas, confidence, `accuracy_vs_reference`, promotion score, and `mape_percent` are **unsupported/custom heuristics** unless future calibration artifacts are added.
- Current L2 must therefore be described as a custom mid-fidelity estimator, not as a validated TLM simulator.

## 5. Current promotion algorithm

Low-fidelity policy defaults require L1, require L2, enable L2, and name the evaluator classes and promotion engine (`step2_workflow.py:667-682`). `run_low_fidelity_screening()` runs L1, evaluates L1 promotion, then runs L2 if required/enabled, evaluates L2 promotion, and emits low-fidelity artifacts (`step2_workflow.py:1038-1122`).

L1 normalization computes confidence as a clamp of selected-record screening confidence, memory efficiency, and compute efficiency; promotion score is `0.55 + 0.40 * confidence` (`step2_workflow.py:707-771`). L2 normalization computes `mape_percent = max(5.0, 22.0 * (1.0 - confidence))` (`step2_workflow.py:774-827`).

`PromotionEngine`:

- evaluates L1-to-L2 if the layer is not L2 and L2-to-L3 otherwise (`dse_v2/promotion/promotion_engine.py:36-41`);
- uses per-family thresholds (`dse_v2/promotion/thresholds.py:3-14`);
- has a fallback score formula combining accuracy, efficiency, resource margin, and confidence (`promotion_engine.py:49-58`);
- requires status, resource legality, score threshold, confidence threshold, MAPE, Pareto, and budget checks (`promotion_engine.py:60-120`, `:135-226`).

Evidence-grade classification:

- Promotion rule structure is useful and auditable as a software policy, but the thresholds and scoring formulas are **unsupported/custom heuristics**.
- MAPE is a computed proxy from confidence, not measured error against a reference. It must not be reported as actual validation MAPE.
- The current Step2 artifact validator correctly enforces that Step2 cannot claim trusted-final result claims and L1/L2 artifacts must remain candidate-generator-only (`step2_workflow.py:1753-1880`).

## 6. Evidence matrix

| Component | Current location | Current algorithm | Citation relationship | Evidence gap / action |
|---|---|---|---|---|
| Step2 handoff | `step2_workflow.py:1-8`, `:39-60`, `:93-104` | Consumes serialized Step1 workload/graph/lowering artifacts; writes replayable Step2 artifacts | Direct local implementation, no external model needed | Keep as generic software contract; cite local file lines in future docs/tests. |
| Mapping legality | `search.py:181-232` | Per-node legal target matrix using op, precision, memory, route constraints | Direct local implementation | Reasonable software gate; not a published mapper. Add tests for every legality reason. |
| Mapping seeds/search | `search.py:499-550`, `:593-627`, `:658-912` | Deterministic seed generation, simple screening, beam top-K | Unsupported/custom heuristic; conceptual overlap with mapspace exploration tools | Rewrite should separate mapspace, cost model, objective, and pruning; cite Timeloop/MAESTRO where applicable. |
| L1 roofline kernel | `analytical_evaluator.py:104-158` | arithmetic intensity; min(compute roof, memory roof) | Adapted model | Cite Roofline; make units/equations explicit and test with golden compute-bound/memory-bound cases. |
| L1 scheduler | `analytical_evaluator.py:160-270` | Topological list scheduling with resource availability and transfer times | Unsupported/custom heuristic | Rewrite as explicit deterministic list scheduler with documented assumptions and validation cases. |
| L1 power/energy | `analytical_evaluator.py:286-296` | Static power sum plus per-task compute-power heuristic | Unsupported/custom heuristic | Replace or calibrate using Accelergy-style component energy model or explicit empirical calibration. |
| L1 memory efficiency | `analytical_evaluator.py:309` | Hard-coded `0.5` | Unsupported/custom heuristic | Remove as a claim; replace with measured/derived utilization or mark unknown. |
| L1 confidence/promotion score | `step2_workflow.py:707-771` | Clamp formula over selected screening confidence and efficiency | Unsupported/custom heuristic | Replace with evidence-tagged confidence/calibration status; do not synthesize validation confidence. |
| L2 wrapper | `tlm_evaluator.py:16-137` | Converts generic design point/workload into PythonTLM inputs/outputs | Direct local implementation | Keep wrapper, but rename/describe as custom unless rewritten to an explicit TLM request/response contract. |
| L2 transaction formula | `python_tlm.py:40-94`, `:179-191` | Compute + bandwidth + transaction latency + family scale | Conceptual inspiration from TLM; unsupported formula constants | Rewrite around explicit transaction graph and timing model; cite SystemC/TLM-2.0 only for transaction abstraction, not current formula accuracy. |
| L2 power/area/confidence/MAPE | `python_tlm.py:95-121` | Formula-generated power, area, confidence, accuracy proxy, promotion score, MAPE proxy | Unsupported/custom heuristic | Replace with calibrated model or mark unvalidated; measured MAPE must come only from reference comparisons. |
| Promotion thresholds | `thresholds.py:3-14`, `promotion_engine.py:60-120` | Hard-coded family thresholds, score/confidence/MAPE/Pareto gates | Unsupported/custom policy | Keep as candidate-budget policy, not validated quality gate; add calibration provenance and review flags. |
| Trusted-final guard | `step2_workflow.py:1753-1880` | Artifact validation blocks trusted final claims from Step2/L1/L2 | Direct local implementation | Preserve; extend tests to block any future evaluator from escalating claims. |

## 7. Public-primary-source reference set

Use the following sources as audit/rewrite anchors. The current code must only claim a relationship if the evidence matrix supports it.

| Source | Use in rewrite | Relationship allowed for current code |
|---|---|---|
| Williams, Waterman, Patterson, "Roofline: an insightful visual performance model for multicore architectures," CACM 2009 / DOI `10.1145/1498765.1498785`; OSTI record: <https://www.osti.gov/biblio/963540> | L1 compute-vs-memory upper-bound model | L1 roofline kernel: adapted model. Other L1 parts: not covered. |
| Accellera SystemC standards / TLM-2.0 language reference material: <https://www.accellera.org/downloads/standards/systemc> | Later L2 transaction semantics if implementing true SystemC/TLM-style contracts | Current PythonTLM: conceptual inspiration only. |
| Shao et al., "Aladdin: A Pre-RTL, Power-Performance Accelerator Simulator Enabling Large Design Space Exploration of Customized Architectures," ISCA 2014 / DOI `10.1109/ISCA.2014.6853196`; gem5-Aladdin repo: <https://github.com/harvard-acc/gem5-aladdin> | Candidate for future pre-RTL accelerator performance/energy modeling and calibration discipline | Current L1/L2: no direct implementation. |
| Timeloop project: <https://github.com/NVlabs/timeloop> | Candidate for structured mapspace/cost-model separation and accelerator mapping exploration | Current mapping search: conceptual overlap only. |
| Accelergy project: <https://github.com/Accelergy-Project/accelergy> | Candidate for architecture-level energy estimation and component/action energy tables | Current power/energy formulas: no direct implementation. |
| MAESTRO project: <https://github.com/maestro-project/maestro> | Candidate for data-centric reuse/performance/cost analysis of mappings | Current mapping/search/L1/L2: conceptual overlap only. |
| SCALE-Sim project: original Arm repo <https://github.com/ARM-software/SCALE-Sim>; maintained successor/project repo <https://github.com/scalesim-project/scale-sim-v2> | Candidate for systolic-array/CNN/tensor-style modeling where architecture family matches | Current DFT/FPGA path: likely not direct unless future workload maps to systolic tensor kernels; treat the Arm repo as archived/legacy and select the maintained project repo if current SCALE-Sim evidence is needed. |
| gem5 publications: <https://www.gem5.org/publications/> | High-fidelity simulator and future Step3/Step4 reference evidence boundary | Current Step2 L1/L2: not direct implementation. |

## 8. Literature-backed replacement candidates

### 8.1 L1 replacement candidates

#### L1-A: Explicit roofline + deterministic list scheduler

Use the Roofline model only for per-op upper-bound throughput, then use a deterministic list scheduler for dependency and resource contention. This is the smallest credible replacement because it preserves current intent while making equations, units, and unsupported assumptions explicit.

Required changes in a later phase:

- Per node/phase compute:
  - `arithmetic_intensity = flops / bytes_accessed`.
  - `effective_compute_roof = peak_flops(op, precision, target) * efficiency(op, target)`.
  - `effective_memory_roof = effective_bandwidth(target, memory_level, route) * arithmetic_intensity`.
  - `node_throughput = min(effective_compute_roof, effective_memory_roof)`.
  - `compute_time = flops / node_throughput`.
- Per edge data movement:
  - derive route from architecture links;
  - transfer time = payload bytes / route bandwidth + route latency;
  - do not hide transfer inside a fixed movement multiplier.
- Scheduler:
  - topological ready queue;
  - resource capacity constraints;
  - communication edge constraints;
  - deterministic tie-breaker.
- Evidence metadata:
  - citation refs for roofline equations;
  - assumption IDs for efficiency, bandwidth, and overlap;
  - calibration status: `uncalibrated`, `calibrated_from_step3`, or `measured`.

#### L1-B: Timeloop/MAESTRO-inspired mapping cost interface

For workloads whose generic ops map cleanly to tensor/dataflow kernels, split Step2 into explicit mapspace, mapping, and cost-model objects. Timeloop and MAESTRO should not be named as direct implementations unless integrated or faithfully reproduced; however, their decomposition can inform the rewrite.

Use when:

- ops have clear tensor loops/reuse dimensions;
- candidate architecture exposes memory hierarchy and dataflow choices;
- Step2 needs ranking stability across many mappings.

#### L1-C: Accelergy-style energy model plug-in

Replace power/energy heuristics with component/action energy records or a calibrated energy table. This can remain dependency-free in the first implementation by defining a JSON energy table seam and marking all missing action energies as `uncalibrated`.

### 8.2 L2 replacement candidates

#### L2-A: Explicit transaction graph evaluator

Rewrite L2 as a transaction graph, not a hidden formula model. It may remain Python, but it must expose:

- transaction records: initiator, target, phase/node, bytes, operation class, precision, dependency IDs;
- timing terms: compute cycles, memory service time, interconnect transfer time, transaction latency, contention model;
- policy terms: buffering, overlap, residency, DMA, host/device transfer;
- evidence terms: source of each constant and calibration status.

SystemC/TLM-2.0 may be cited for transaction-level abstraction and later interoperability, but not for formula accuracy unless the implementation follows the standard semantics.

#### L2-B: Aladdin/gem5-Aladdin-style pre-RTL candidate

For accelerator microarchitecture modeling, use Aladdin/gem5-Aladdin as a future reference candidate. A later rewrite can define an adapter from generic `ComputeGraph`/mapping to a pre-RTL trace or DDDG-like representation. Phase 1 does not implement this and must not imply current PythonTLM already does it.

#### L2-C: Domain/architecture-specific models under explicit policy seam

For DFT/FPGA Step2, support phase-aware modeling under a static domain policy seam while keeping core generic:

- phase groups from Step1 remain metadata/policy hints, not required core fields;
- DFT phase hints can influence seeds and review gates;
- L1/L2 generic artifacts remain loadable if DFT metadata is ignored;
- hard review flags must block promotion as configured.

### 8.3 Promotion/confidence replacement candidates

Promotion should be rewritten from "score looks high" to an evidence gate:

- Resource legality: hard gate.
- Critical review flags (`project_critical_conflict`, `segmentation_uncertain`): hard gate.
- Soft flags (`insufficient_evidence`, `important_input_parameter`): review required, no trusted claim.
- Calibration status: `uncalibrated` cannot produce measured MAPE or validated confidence.
- L1/L2 may select candidates for Step3 budget, but cannot declare final winners.
- Measured MAPE, rank correlation, and top-K stability may only come from Step3+ comparisons.

## 9. Rewrite specification without code

The later code rewrite should satisfy this specification before implementation starts.

### 9.1 Common evidence schema for L1/L2 outputs

Every L1/L2 result should include:

```json
{
  "candidate_generation_only": true,
  "trusted_final_claim": false,
  "model_identity": {
    "layer": "L1|L2",
    "algorithm_id": "...",
    "algorithm_version": "...",
    "overall_citation_relationship": "mixed|direct_implementation|adapted_model|conceptual_inspiration|unsupported_custom_heuristic"
  },
  "model_components": [
    {
      "component_id": "roofline_bound|scheduler|transaction_timing|energy_model|confidence_model",
      "role": "compute_bound|scheduling|data_movement|energy|promotion_confidence",
      "equations_or_constants": ["..."],
      "source": {
        "kind": "paper|standard|official_project|repo_local|calibration|default",
        "citation": "...",
        "url_or_doi": "..."
      },
      "citation_relationship": "direct_implementation|adapted_model|conceptual_inspiration|unsupported_custom_heuristic",
      "calibration_status": "uncalibrated|calibrated_from_step3|measured",
      "review_flags": []
    }
  ],
  "assumptions": [
    {"assumption_id": "...", "value": "...", "source": "paper|catalog|step1|calibration|default", "review_required": true}
  ],
  "calibration": {
    "status": "uncalibrated|calibrated_from_step3|measured",
    "reference_artifacts": [],
    "measured_mape_percent": null,
    "rank_correlation": null
  },
  "review_flags": []
}
```

A result may expose a `confidence` field only when its derivation is stated. If confidence is heuristic, it must be labeled `heuristic_confidence` and must not be used as measured validation confidence. Component-level evidence is mandatory because one evaluator can mix citation tiers: for example, L1 may contain an adapted Roofline component, a custom scheduler, and unsupported energy constants in the same result.

### 9.2 L1 required behavior

Input:

- `DesignPoint` with `SystemArchitecture`.
- executable `ComputeGraph`.
- selected mapping.
- optional Step2 domain policy hints.

Algorithm:

1. Build route/bandwidth table from architecture links.
2. For each mapped node, compute roofline-derived compute time with explicit units.
3. For each edge crossing resources, compute transfer time from payload size and route latency/bandwidth.
4. Schedule ready nodes with deterministic list scheduling.
5. Emit latency, throughput, data movement, resource bottleneck, and evidence metadata.
6. If energy constants are missing, emit energy as `null` or `uncalibrated_estimate`, not as validated energy.

Required tests:

- single-node compute-bound golden case;
- single-node memory-bound golden case;
- two-node same-resource no-transfer case;
- two-node cross-resource transfer case;
- missing bandwidth/efficiency assumptions produce review flags;
- no L1 output can set `trusted_final_claim: true`.

### 9.3 L2 required behavior

Input:

- same generic Step2 inputs as L1;
- L1 result may seed L2 but cannot be blindly trusted;
- optional policy hints and phase groups.

Algorithm:

1. Build transaction graph from nodes and inter-resource edges.
2. Assign each transaction a type: compute, memory read/write, DMA, host-device, synchronization, or control.
3. Compute timing using explicit terms:
   - compute cycles / clock;
   - bytes / bandwidth;
   - transaction count × transaction latency;
   - contention/overlap model with named assumptions.
4. Emit a full transaction breakdown so Step3/SystemC can later calibrate it.
5. Do not report measured MAPE unless compared against Step3+ reference artifacts.

Required tests:

- transaction-count golden case;
- overlap disabled/enabled cases;
- host-device transfer case;
- phase-aware DFT metadata pass-through while generic consumer ignores it;
- no L2 output can claim SystemC/TLM-2.0 direct implementation unless the standard-compatible implementation exists.

### 9.4 Promotion rewrite required behavior

Promotion into Step3 queue is allowed only as candidate-generation scheduling.

Hard blocks:

- illegal selected mapping;
- `project_critical_conflict`;
- `segmentation_uncertain`;
- missing required L1/L2 artifacts when policy says they are required;
- any attempt to set trusted-final flags in Step2.

Review-required but not necessarily hard-blocked:

- `insufficient_evidence`;
- `important_input_parameter`;
- uncalibrated constants used in high-impact phases;
- unsupported/custom heuristic in a promotion-critical metric.

Metrics for future validation:

- MAPE/relative error against Step3 latency, energy, and data movement;
- Spearman rank correlation across candidates;
- top-K overlap and top-1 stability;
- calibration/holdout split by architecture family and workload family;
- confidence calibration curves if confidence is retained.

## 10. Test and validation plan

### 10.1 Phase-1 doc/report checks

- Confirm the audit report includes code-to-algorithm evidence matrix.
- Confirm every public-source claim has a URL/DOI/project link.
- Confirm every current unsupported formula is marked unsupported/custom.
- Confirm report does not instruct running Step3 or claim validation.

### 10.2 Later implementation tests

- Unit tests for L1 roofline golden cases.
- Unit tests for L1 route/data-movement accounting.
- Unit tests for deterministic scheduler tie-breaking.
- Unit tests for L2 transaction graph construction.
- Unit tests that current/future `mape_percent` cannot be marked measured without reference artifacts.
- Policy tests for hard review flags and soft review flags.
- Core-boundary tests that generic consumers ignore DFT metadata and still load Step2 artifacts.
- Leakage guards: Step2 outputs no final winner, no runtime descriptor execution result, no SystemC/gem5 simulation result, and no trusted-final claim.

### 10.3 Future calibration protocol

1. Select a calibration set across workload family, architecture family, and mapping class.
2. Run Step3/SystemC or Step4/gem5+SystemC only after candidate-generation gates pass.
3. Store reference artifacts with immutable input hashes.
4. Fit or tune constants only on calibration split.
5. Report holdout MAPE, rank correlation, top-K overlap, and confidence calibration.
6. Promote a model from `uncalibrated` to `calibrated_from_step3` only when the metrics and provenance are written into artifacts.

## 11. ADR

Decision: treat current Step2 L1/L2 as candidate-generation prototypes and produce an evidence-grade audit plus rewrite specification before any evaluator rewrite.

Drivers:

- The user requires rigorous research-grade evidence, not "basically runnable" behavior.
- Step2 must remain candidate-generation only.
- Public primary sources are required for algorithmic claims.
- DFT-specific behavior must stay under optional policy/plugin boundaries.

Alternatives rejected:

- Calling current PythonTLM a validated TLM simulator: rejected because it is a custom formula model.
- Rewriting L1/L2 immediately: rejected for phase 1 because audit/report comes first.
- Running Step3/gem5 to validate now: rejected by phase-1 non-goals.
- Using literature names as vague inspiration without tiering: rejected because it overclaims citation support.

Consequences:

- The prototype can still generate candidates and Step3 queues.
- Any paper/report must clearly separate current implementation, conceptual inspiration, and future replacement candidates.
- Later implementation should start from the rewrite specification and tests above.
