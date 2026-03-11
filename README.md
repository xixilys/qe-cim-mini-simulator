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
- The current design document is in [docs/design.md](/Volumes/remote/phd/year_2/project/dft加速/docs/design.md).
- QE-specific benchmark helpers and tiny example inputs are kept under `docs/`.
