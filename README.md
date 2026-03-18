# QE CIM Mini Simulator

System-level prototype and design notes for accelerating Quantum ESPRESSO
subspace diagonalization and related dense kernels with a CIM-oriented backend.

## Repository Scope

This repository currently contains:

- `model/`: a SystemC-based mini QE / CIM co-simulation prototype
- `docs/`: design notes, benchmark helpers, and minimal QE inputs

It intentionally excludes:

- vendored QE source trees
- raw QE runtime dumps
- temporary wavefunction / density files
- large benchmark archives and presentation artifacts

## Build

The simulator currently builds via:

```bash
cd model
make
```

This requires a working SystemC installation. The existing `Makefile` expects
headers and libraries to be reachable from a local toolchain configuration.

## Notes

- The code in `model/` is a prototype, not a drop-in QE plugin.
- The current project development document is in [docs/project_development_timeline.md](/Volumes/remote/phd/year_2/project/dft加速/docs/project_development_timeline.md).
- The complex subspace behavioral validation flow is documented in [model/docs/complex_subspace_validation.md](/Volumes/remote/phd/year_2/project/dft加速/model/docs/complex_subspace_validation.md).
- The full FP64 complex Ozaki-II emulation flow is documented in [model/docs/complex_ozaki_fp64_validation.md](/Volumes/remote/phd/year_2/project/dft加速/model/docs/complex_ozaki_fp64_validation.md).
- The dedicated validation executable is `model/bin/complex_subspace_eval`.
- The dedicated FP64 complex Ozaki-II executable is `model/bin/complex_ozaki_eval`.
- QE-specific benchmark helpers and tiny example inputs are kept under `docs/`.
