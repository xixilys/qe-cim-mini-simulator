# QE-IC Seven-Day Preliminary FPGA/Hybrid vs GPU Report

- Preliminary label: `fpga_hybrid_weaker`
- Confidence: `medium`
- Evidence tier: `high_fidelity_preliminary`
- Final hardware claim allowed: `False`

## Direct answer

Current seven-day generated-stub/tool-backed FPGA/hybrid candidates are slower than the measured GPU-only QE baseline on the generated IC/EDA benchmark cases.

## What this can and cannot claim

- Can say: We can report a preliminary current-implementation-limited weaker-than-GPU result for the generated benchmark suite.
- Cannot say: We cannot make a final FPGA/hybrid hardware superiority or no-opportunity claim without real kernel correctness, board/implementation closure, and representative real-device workloads.
- Board limit: No physical FPGA board measurement was required or collected; this prevents final hardware superiority wording.

## Evidence summary

- Generated/admitted QE cases: `3`
- GPU baseline measured: `True`
- GPU baseline records: `3`
- Candidate high-fidelity/tool-backed records: `9`
- Classifier blockers: `[]`

## Cases

- `ic_si_bulk_2atom_scf_v0` — Two-atom silicon diamond primitive cell; IC substrate/channel proxy.
  - input hash: `sha256:78c7b2a0feba57c3a53be85535cf7f6fc0d96c9996a8b3c628a7bac53be30add`
  - scope: `performance_benchmark_only`
- `ic_sio2_dielectric_6atom_scf_v0` — Small Si/O dielectric proxy; gate-oxide/interlayer-dielectric style workload.
  - input hash: `sha256:21c1eab685215149cb71d9e11f105b1d40c2fff4a2ffd9e010f4a623fa2b5302`
  - scope: `performance_benchmark_only`
- `ic_al_interconnect_4atom_scf_v0` — Four-atom Al metallic interconnect proxy with smearing; stresses memory/FFT plus metallic SCF behavior.
  - input hash: `sha256:575f3717ecfca149ce4dbc0be35ccc660df483c641704de645d3b51f04509d98`
  - scope: `performance_benchmark_only`

## Required next evidence

- check whether alternative candidate families or overlap schedules can reduce transfer/workflow overhead before final rejection
- measure or model host-device/interconnect transfer costs at full-SCF granularity
- account for SCF control, diagonalization, mixing, synchronization, and launch overheads end-to-end

## Claim boundary

not_final_hardware_superiority_claim: preliminary labels summarize current GPU-baseline and FPGA/hybrid evidence for triage only. Final FPGA/hybrid claims still require workload-representative full-SCF accounting plus the tool-specific correctness, synthesis, implementation, and timing gates.
