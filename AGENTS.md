# AGENTS Guide

## Purpose

This repository is a **domain-neutral DSE control-plane + multi-level simulation prototype** for heterogeneous accelerators.  The active work is design-space exploration, Campaign/Trial-ledger orchestration, promotion across L1/L2/L3/L4 fidelity, generic SystemC-style timing simulation, evidence adjudication, reporting/claim boundaries, and gem5 GenericAccel descriptor/request/microarchitecture/completion evidence.

The core control plane must remain **domain-neutral**: workload-family-specific facts belong in profiles, importers, adapters, or reference fixtures, not in core IR/control-plane contracts.  The current primary proof scenario is **DFT/QE full-SCF hardware DSE and co-design** through a DFT reference profile/adapter/schema, with FPGA/gem5/IC-EDA evidence used as proof paths.  DFT is used to close the research-grade proof path, while reusable core contracts must stay valid for future workload families.

Historical application-specific material should not be restored wholesale.  Restore or recreate only the scoped reference fixtures needed for the DFT primary proof path or for explicit multi-workload validation, and keep claim boundaries clear.

For the current DFT primary proof path, the required target is not a model-only or h_psi-only slice.  The intended closure is a full-SCF accelerator prototype and DSE loop over representative SCF workloads, realistic hardware template families, search algorithms, and real HLS/RTL/FPGA/IC-EDA PPA evidence for all major SCF kernels.

The first prototype target is **full-SCF evaluated hybrid**, not full-SCF device-resident.  Hardware acceleration claims are limited to gated FFT/transpose/Hψ/projector/reduction/DMA paths unless additional stages pass the same promotion gates.  CPU may retain I/O, SCF control, convergence checks, diagonalization, and mixing, but those host-bound stages plus synchronization and transfer costs must be included in end-to-end SCF timing/energy models and must not be counted as hardware acceleration benefits.

## Active layout

```
.
├── dse_v2/                         # DSE orchestration, workload IR, mapping, evidence, reports
├── model/generic_sim_backend/       # Generic JSON-driven simulator executable: generic_sim
├── gem5_integration/                # GenericAccel gem5 model, configs, L4 driver
├── runtime_api/                     # Domain-neutral C offload/proxy ABI
├── docs/                            # Current generic design/runbook docs
└── tools/                           # Supporting local analysis tools, when present
```

## Quick navigation

- DSE implementation: `dse_v2/AGENTS.md`
- Generic simulator: `model/AGENTS.md` and `model/generic_sim_backend/README.md`
- gem5 L4 path: `gem5_integration/AGENTS.md`
- Architecture docs: `docs/architecture/AGENTS.md`
- Benchmark/evidence docs: `docs/benchmarks/AGENTS.md`
- Runtime proxy ABI: `runtime_api/AGENTS.md`

## Build and validation

```bash
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j
python3 -m pytest -q dse_v2/tests
python3 dse_v2/scripts/dse/run_full_flow_pilot.py --backend systemc --out runs/dse/generic_systemc_pilot
```

For C++ simulator edits, rebuild `model/generic_sim_backend/build/generic_sim` and run `ctest --test-dir model/generic_sim_backend/build --output-on-failure` when tests are built.

For Python DSE edits, run the smallest relevant `dse_v2/tests` target, then `python3 -m compileall dse_v2` if imports changed.

For system-restructure work, keep documentation and implementation synchronized in the same iteration.  When code, schemas, artifacts, state machines, evidence gates, or run contracts change, update the design manual/runbook material before claiming completion.  A separate documentation auto-generation feature is not required unless explicitly requested; the agent is responsible for keeping the manual current while editing.


## Local IC/EDA access

When FPGA/EDA evidence is relevant, first try the local `ic` launcher if it exists; otherwise use the verified SSH aliases before classifying the IC/EDA path as unavailable.  Current verified route:

```bash
ssh ic-eda
# alias: HostName 192.168.16.1, Port 1266, User ICer
# key: ~/.ssh/ic_eda_ed25519 (private key stays local; do not store passwords in repo files or scripts)
source ~/.bashrc
which dc_shell || true; dc_shell -version || true
which vcs || true; vcs -ID || true
which vivado || true; LC_ALL=C LANG=C vivado -version || true
```

Known verified host/tool facts from the 2026-05-19 key-auth probe:
- Host: `IC_EDA`; user: `ICer`; OS family: CentOS 7 / Linux 3.10.
- `dc_shell`: `/home/synopsys/syn/O-2018.06-SP1/bin/dc_shell`, version O-2018.06-SP1.
- `vcs`: `/home/synopsys/vcs-mx/O-2018.09-1/bin/vcs`, version family O-2018.09.
- `vivado`: `/home/Xilinx/Vivado/2019.1/bin/vivado`, version 2019.1; use `LC_ALL=C LANG=C` for version/probe commands when needed.

IC/EDA remains side evidence unless a task explicitly enters RTL/FPGA/EDA closure; it cannot substitute for QE/gem5 L4 actual-compute value gates.

## Workspace rules

- Do not modify external upstream workspaces such as `/Users/xixilys/project/qe-7.5`.
- Do not recreate historical application-specific directories unless the task explicitly requires a scoped reference fixture.
- Expect a dirty working tree.  Do not revert unrelated user changes.
- Avoid committing generated caches, local simulator builds, gem5 m5out directories, and scratch `tmp*/` outputs.

## Anti-downgrade completion discipline

Do not silently downgrade broad architecture/research/system goals into a
small vertical slice and call it complete.

- Always distinguish **vertical slice**, **MVP**, and **deliverable-complete**
  status in progress and final reports.
- Passing tests, green manifests, or runnable demos are evidence only; they are
  not sufficient proof that the requested system is complete.
- Before claiming completion, build a prompt-to-artifact checklist that maps
  every explicit requirement and core semantic requirement to concrete files,
  artifacts, reports, tests, or command output.
- If any core requirement is missing, partial, weakly verified, or only covered
  by a fixed/manual placeholder, report **partial** and continue or state the
  blocker.  Do not mark a goal complete.
- Do not treat hard-coded fixed candidates as a real search system when the
  user asked for architecture/search/design-space exploration.  Fixed instances
  may be seeds or a vertical slice, but they are not completion by themselves.
- For Step2 architecture-search work, real completion requires, unless the user
  explicitly narrows scope:
  - architecture family/search-space definitions;
  - parameterized candidate generation;
  - workload-aware screening/pruning;
  - generated candidate records with parameters and provenance;
  - explicit promotion/blocker reasons;
  - replayable artifacts such as `architecture_search_space.json`,
    `architecture_candidate_generation_report.json`, and
    `architecture_screening_report.json` when applicable.
- Keep Step boundaries precise:
  - Step1 describes workload facts/summaries/hints only.
  - Step2 owns architecture candidate generation, architecture screening,
    mapping/co-design candidate generation, and promotion decisions.
  - Step3 executes Step2-promoted candidates and records raw simulation requests/results/logs only.
  - Step4 adjudicates evidence, calibration/feedback, claim validation, and canonical L4 metrics from Step3/L4-adapter outputs.
- Use precise eligibility names: prefer `step2_screenable`,
  `step3_evaluable`, `simulation_eligible`, and `simulation_blockers` over
  ambiguous terms such as `step3_searchable`.
- For large architecture or DSE tasks, run an adversarial self-audit before
  finalizing: ask whether the result is only a shallow vertical slice, whether
  placeholders are being presented as search, and whether tests actually cover
  the user's real objective.  Use delegated verifier/critic review only when
  permitted by the active orchestration rules.
- If the user's real objective is broader than the written acceptance checklist,
  do not exploit the checklist minimum.  Surface the gap and keep the completion
  status honest.
- For the current research-grade system-restructure objective, do not stop at a
  P0-only or documentation-only slice.  The target is full-system closure around
  a domain-neutral control plane with DFT as the primary proof path: canonical
  artifacts/schemas, Campaign/Trial ledger, Step3/Step4/Step5 separation,
  evidence adjudication, calibration/feedback records, DFT profile schema, L4
  software-visible evidence, and required real-tool validation attempts.
- Breaking cleanup is allowed for canonical contract migration: new code may
  replace legacy artifact names/contracts instead of preserving old run
  compatibility.  Document removed legacy names and claim boundaries rather than
  silently dual-writing stale formats.
- Required hard gates for final claims include Python tests/compileall,
  SystemC backend build/ctest/full-flow pilot, DFT full-flow evidence, gem5/L4
  proof evidence, and IC/EDA tool attempts when FPGA/EDA numeric evidence is
  implicated.  If a hard gate has not truly passed, keep working; do not claim
  completion through blockers, mocks, placeholders, or downgraded substitutes.
- For the DFT/QE full-SCF hardware DSE objective, final completion additionally
  requires descriptor-plus-runnable-bundle workload inputs, the six representative
  SCF workload classes, multi-template hardware candidate families, replayable
  search provenance, full-SCF descriptor/runtime scheduling, and per-major-kernel
  HLS/RTL/PPA evidence.  Model-level SystemC/gem5 closure, h_psi-only numerical
  evidence, fixed hand-picked candidates, or unavailable-tool logs are progress
  evidence only and must not be reported as final system completion.
- Rolling latest source-flow map auto-discovery and ready-candidate counts are
  scheduling/provenance evidence only.  They may identify all-eight ready
  source-flow roots and assemble a `source_flow_map.json` (for example via
  `build_dft_hardware_closure_latest_source_flow_map.py`), but they do not prove
  parser output, hard-gate adjudication, Vivado/DC closure, full-SCF evaluated
  hybrid completion, or deliverable completion.  A partial latest map with
  missing candidate×kernel rows must be reported as partial/blocked, not
  release-complete.
- For DFT hardware candidate claims, apply claim-specific tool gates.  Any
  kernel claimed as accelerated must pass golden correctness, HLS C-sim or RTL
  sim, HLS C-synth or RTL synth, then Vivado synthesis/implementation for FPGA
  claims and DC synthesis/timing/area for ASIC claims.  DC-only evidence cannot
  satisfy an FPGA acceleration claim; Vivado-only evidence cannot satisfy an ASIC
  claim.  Host-bound stages must be explicitly labeled with cost and claim
  boundaries.

## Style

- Python: 4 spaces, standard library first, explicit error returns for CLI scripts.
- C++: C++17, direct loops are fine, keep simulator contracts JSON-visible and testable.
- Keep core names domain-neutral: workload family, compute graph, adapter, mapping, evidence, simulator, descriptor.
- If a domain-specific adapter is needed, keep it out of core IR and mark claim boundaries explicitly.
