# QE runtime adapter boundary

This directory is the QE-specific adapter boundary for the backend proxy runtime.

The backend core remains domain-neutral:

- `runtime_api/command_descriptor.h`
- `runtime_api/offload_runtime.h`
- `runtime_api/offload_runtime.c`
- `proxy_programs/generic_scf_proxy.c`

QE-specific hooks, Fortran wrappers, and `c_bands`/`electrons` patches belong here or
under `gem5_integration/qe_integration/`; they should translate QE data into the
domain-neutral `qebs_command_descriptor` instead of changing the backend execution
service schema.  A proxy-only QE entry point is provided at
`proxy_programs/qe_cbands_proxy.c`.

Claim boundary: proxy runtime output is control/runtime evidence only.  It does not
claim QE-equivalent SCF correctness, RTL/cycle-accurate timing, or board/ASIC
measurement.
