# QE-IC Real GPU-Baseline Opportunity Analysis

## What Question This Layer Answers

This layer asks whether FPGA-only or GPU+FPGA hybrid candidates have a claim-gated opportunity against a real GPU-only QE baseline for a specific workload family, motif, and candidate architecture.

## Why True GPU Baseline Is Required

A GPU-vs-FPGA or GPU-vs-hybrid statement is only meaningful when the GPU-only baseline is measured for the same workload family and carries `measurements_are_real=true` plus `evidence_status=measured`.

## Why L1 And Synthetic Replay Are Insufficient

L1 and synthetic replay are insufficient for final GPU-vs-FPGA claims because they are search, screening, or calibration evidence. They do not replace measured GPU timing or high-fidelity candidate execution evidence.

## How speedup_vs_gpu Is Computed

`speedup_vs_gpu_mean = gpu_baseline.runtime_seconds_mean / candidate.workflow_runtime_seconds_mean`. Conservative CI speedup uses the GPU low confidence bound divided by the candidate high confidence bound.

## Accepted Evidence Levels

Accepted evidence levels are `systemc_timing`, `gem5_systemc`, `vivado_resource_timing`, `trace_replay`, and `real_qe_run` when they include workflow-level runtime where required. `l1_estimate_only` is accepted for ingestion but blocked from opportunity claims.

## Claim Gates

Claim gates require a matching measured GPU baseline, real measured or high-fidelity candidate evidence with provenance, workflow-level runtime, minimum repeated runs, speedup above threshold, conservative CI above 1.0 when configured, resource feasibility, timing feasibility, and no L1-only or synthetic-only evidence.

## evidence_missing

`evidence_missing` means the report could not find the exact baseline, workflow runtime, repeated-run data, provenance, or candidate evidence needed to adjudicate the opportunity claim.

## GPU Is Dominant

`gpu_dominant_no_fpga_opportunity` means the supplied measured evidence does not pass the speedup gate and GPU utilization is high enough that the report classifies GPU-only as the practical dominant baseline for that record.

## FPGA/Hybrid Opportunity Is Found

`fpga_opportunity_found` or `hybrid_opportunity_found` means the candidate passed all configured claim gates. The conclusion identifies the candidate, workload family, motif, architecture family, speedup, bottlenecks, and feasibility summary.

## Replace Fixture Evidence

To replace fixture evidence, edit the config input paths for `gpu_baseline_measurements` and `candidate_high_fidelity_results` so they point at measured GPU baseline records and real measured or high-fidelity candidate result records with explicit tool provenance.

## No Final Claim Is Made Unless Claim Gates Pass

No final claim is made unless claim gates pass. Fixture evidence, L1-only estimates, synthetic labels, kernel-only timing, missing workflow overhead, or infeasible resource/timing records remain progress evidence only.

## Current Report Answer

Current repository evidence is insufficient to conclude FPGA/hybrid is stronger or weaker than GPU under real GPU baseline.
