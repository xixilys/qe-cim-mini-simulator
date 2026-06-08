 Produce a defensible seven-day preliminary QE-IC FPGA/hybrid-vs-GPU opportunity conclusion by generating several more complex IC/EDA-relevant QE full-SCF benchmark workloads, upgrading FPGA/hybrid candidate evidence
  beyond generated proxy where possible using SystemC/trace/gem5/VCS/Vivado/Vivado-HLS/DC, and classifying the result as fpga_hybrid_stronger, fpga_hybrid_weaker, gpu_dominant, fundamental_no_opportunity, or
  insufficient_evidence with exact evidence and blockers.

  First action: read AGENTS.md, dse_v2/AGENTS.md, docs/goal.md, docs/architecture/qe_ic_real_opportunity_campaign_v1.md, docs/architecture/dft_scf_hardware_dse_design_manual.md sections on claim gates, the current artifacts
  under artifacts/qe_ic_real_opportunity_campaign_real_run/, and the EDA smoke log under artifacts/qe_ic_7day_prelim/eda_preflight/. Then write artifacts/qe_ic_7day_prelim/initial_resource_map.md summarizing detected GPU/QE/EDA/
  SystemC/gem5 availability and the current evidence gap. Do not wait for user acknowledgement; continue automatically.

  Scope:
    - Primary code/artifacts: dse_v2/evidence/qe_ic/, dse_v2/experiments/qe_ic_real_opportunity/, dse_v2/scripts/dse/run_qe_ic_real_opportunity_campaign.py, relevant QE-IC/HLS/RTL/SystemC/gem5 scripts under dse_v2/scripts/dse/,
    dse_v2/tests/test_qe_ic_preliminary_opportunity_classifier.py, dse_v2/tests/test_qe_ic_real_opportunity_campaign.py.
    - Workload generation: add or use scoped generated QE full-SCF benchmark inputs under artifacts/qe_ic_7day_prelim/generated_inputs/ and/or dse_v2/experiments/qe_ic_real_opportunity/ helpers. Generate at least 3 IC/EDA-
    relevant full-SCF benchmark cases if real representative decks are absent.
    - Primary output directory: artifacts/qe_ic_7day_prelim/.
    - Documentation allowed: docs/architecture/qe_ic_real_opportunity_campaign_v1.md and artifacts/qe_ic_7day_prelim/seven_day_preliminary_report.md.
    - Do not modify external upstream workspaces such as /Users/xixilys/project/qe-7.5. Do not erase prior artifacts except run-local scratch files created by this goal.

  Constraints:
    - Continue autonomously through recoverable blockers. Do not stop because input decks, candidate source, SystemC configs, EDA scripts, or profile logs are missing; generate bounded benchmark inputs/stubs/configs where
    allowed, ingest existing artifacts, then continue.
    - Generate several more complex IC/EDA-relevant QE full-SCF workloads if real decks are not provided. Prefer small but nontrivial semiconductor/material cases relevant to IC design such as Si bulk SCF, Si/SiO2-like proxy,
    doped/strained silicon proxy, metal interconnect proxy, or dielectric/oxide proxy, constrained to run on RTX 3070 within a practical time budget. Each generated input must include input deck hash, pseudo hash when
    applicable, workload_family_id, case_origin=generated_benchmark, and scientific_claim_scope=performance_benchmark_only.
    - Use the detected real GPU path if available: /home/xixilys/project/qe_gpu_build/q-e/build_gpu_serial_nvhpc_cuda_no_gomp/bin/pw.x with CUDA/NVHPC runtime env from existing
    qe_ic_real_opportunity_campaign_real_gpu_config.json. If that path fails, probe /usr/bin/pw.x only as CPU/QE availability evidence and do not substitute CPU for GPU.
    - No physical FPGA board is required for this goal. Use simulation and tool evidence first: SystemC/generic_sim, trace replay, gem5 if available, VCS compile/simulation, Vivado HLS C-sim/C-synth, Vivado synthesis/
    implementation/resource/timing, and DC timing/area. Report clearly that no board measurement means no final hardware superiority claim.
    - Use EDA through ssh ic-eda. Known working smoke result: Vivado 2019.1 rc=0, vivado_hls rc=0, VCS compile/sim rc=0, dc_shell rc=0. Known remote tools include /home/Xilinx/Vivado/2019.1/bin/vivado, /home/Xilinx/
    Vivado/2019.1/bin/vivado_hls, /home/synopsys/vcs-mx/O-2018.09-1/bin/vcs, and /home/synopsys/syn/O-2018.06-SP1/bin/dc_shell. Locale warnings such as LC_ALL C.UTF-8 are not failures if the tool command succeeds.
    - Do not fabricate measured QE, GPU, FPGA, ASIC, timing, resource, or correctness evidence. Generated/proxy evidence must remain explicitly labeled generated/proxy/performance_benchmark_only.
    - Final hardware superiority claims are not required for this seven-day preliminary report. final_claim_allowed must remain false unless existing claim gates genuinely pass.
    - Do not classify fundamental_no_opportunity from generated proxy/stub evidence. It requires measured GPU baseline, workflow-level candidate evidence, implementation-quality pass, resource/timing evidence, and a documented
    structural upper bound.
    - Keep the core DSE control plane domain-neutral; QE/DFT-specific facts stay in adapters, evidence, scripts, docs, or scoped artifacts.
    - No new dependencies unless already available locally. No test deletion or skip/xfail changes to hide failures.
    - Use Codex native subagents when useful for independent lanes, always with OMX agent_type such as explore, executor, test-engineer, verifier, or critic.
    - Run as long as needed within the token/time budget; do not stop with a human handoff for ordinary recoverable failures.

  Done when:
    1. artifacts/qe_ic_7day_prelim/initial_resource_map.md exists and records GPU, QE, EDA-over-ssh, SystemC/generic_sim, and gem5 availability or exact failure reasons, including command/log references.
    2. At least 3 generated or real QE full-SCF benchmark cases exist, preferably IC/EDA-relevant semiconductor/interconnect/dielectric proxies. Each case has input deck hash, pseudo hash when applicable, workload_family_id,
    case_origin, scientific_claim_scope, QE command provenance, and clear runtime feasibility notes.
    3. A real GPU-only baseline has been run or revalidated for each admitted case with at least 3 repetitions where feasible, measurements_are_real=true, evidence_status=measured, runtime statistics, command provenance, stdout/
    stderr logs, and no CPU substitution. If a case fails GPU QE, classify that case with exact logs and continue with other cases.
    4. Layer-4 FPGA-only and GPU+FPGA hybrid candidates are selected or generated for the admitted cases, with candidate IDs, target type, motif/kernel binding, implementation maturity, and workflow accounting boundary.
    5. Candidate-side evidence is upgraded beyond plain generated_trace_proxy where feasible: at least one of SystemC/generic_sim timing, trace replay, gem5/SystemC, VCS simulation, Vivado HLS C-sim/C-synth, Vivado synthesis/
    implementation/resource/timing, or DC timing/area is attempted per selected candidate family. If a path fails, raw logs and parsed reason are recorded.
    6. EDA evidence is attempted through ssh ic-eda for selected kernels/candidates: at minimum VCS compile/simulation plus Vivado or Vivado-HLS resource/timing when possible; DC timing/area when ASIC-side comparison is useful.
    Tool failure is distinguished from design failure; design failure becomes implementation_limited or resource_invalid, not a global blocker.
    7. The comparison includes full-SCF/end-to-end accounting: host work, transfer, synchronization, SCF control, diagonalization, mixing, launch overheads, and kernel/runtime separation. Kernel-only speedup is never used as
    whole-workflow speedup.
    8. The final artifact artifacts/qe_ic_7day_prelim/seven_day_preliminary_report.md and a JSON report contain a direct conclusion label: fpga_hybrid_stronger, fpga_hybrid_weaker, gpu_dominant, fundamental_no_opportunity, or
    insufficient_evidence. The report explains why the label is supported, what evidence tier it rests on, what cannot be claimed, whether no-board-measurement limits finality, and the next evidence needed for a final claim.
    9. If the label remains insufficient_evidence, do not mark complete until the report proves that GPU/QE, candidate high-fidelity, EDA, SystemC/gem5/trace replay, and implementation-quality fallback paths were attempted or
    found unavailable with concrete logs.
    10. Validation passes with exact fresh commands and pasted summaries:
        - python3 -m pytest -q dse_v2/tests/test_qe_ic_preliminary_opportunity_classifier.py dse_v2/tests/test_qe_ic_real_opportunity_campaign.py
        - python3 -m compileall -q dse_v2
        - python3 -m json.tool artifacts/qe_ic_7day_prelim/<final-json-report>.json >/dev/null
        - git diff --check
    11. Git status is clean except for explicitly reported generated run artifacts, or the final response lists exactly which files remain uncommitted and why. If committing is safe and no unrelated dirty files exist, create a
    semantic commit for the seven-day preliminary conclusion work.

  Stop if:
    - The next action would modify external upstream workspaces, delete non-goal artifacts, overwrite unrelated user changes, or require destructive filesystem operations outside this repo.
    - Noninteractive GPU/QE or ssh ic-eda access requires missing credentials or license setup after at least three distinct recovery/probe attempts; before stopping, write artifacts/qe_ic_7day_prelim/resource_blocker_report.md
    with exact commands, exit codes, and the weakest defensible preliminary conclusion.
    - Existing tests begin failing because of this goal’s changes and cannot be repaired without editing tests to hide regressions; revert or repair own changes first, then report the exact failing command.
    - A new OS/package dependency, Python version change, or paid tool installation is required; use existing tools or a lower-fidelity fallback first, and stop only if no non-destructive fallback remains.
    - The user explicitly cancels.
