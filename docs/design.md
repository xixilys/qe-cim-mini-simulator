# QE Subspace Diagonalization CIM Accelerator Design

## Scope

This document describes a first-pass hardware and software split for accelerating
the small dense eigenproblems generated inside the Quantum ESPRESSO `pw.x`
subspace solvers.

The target is not the full plane-wave Hamiltonian. The target is the projected
problem built inside Davidson / related eigensolvers:

- Standard problem: `H_sub c = lambda c`
- Generalized problem: `H_sub c = lambda S_sub c`

where:

- `H_sub = V^H H V`
- `S_sub = V^H S V`
- `V` is the current reduced basis

For general `k` points, `H_sub` is complex Hermitian. For `Gamma-only`,
`H_sub` is real symmetric. For ultrasoft / PAW calculations, `S_sub` is
Hermitian positive definite and the problem is generalized.

This design therefore prioritizes:

- Small dense complex Hermitian matrices
- Repeated solve of only the lowest `m` eigenpairs
- Tight coupling to a complex matrix-vector or matrix-block-vector engine
- A software path that remains compatible with QE's existing outer Davidson flow

## Constraints From QE

The hardware target should be derived from QE behavior, not from a fixed
mathematical toy problem.

- The reduced basis dimension is solver dependent.
- For Davidson in `pw.x`, the subspace dimension grows from roughly `nbnd` to
  `nbndx`, with `nbndx = diago_david_ndim * nbnd`.
- With QE defaults, `diago_david_ndim = 2`, so a common upper bound is
  about `2 * nbnd`.
- This means the practical dimension is not universally `N <= 100`; for some
  systems it can be a few hundred or larger.

The first implementation should therefore define an explicit operating envelope,
for example:

- Preferred fast path: `N <= 128`
- Degraded or fallback path: `128 < N <= 256`
- Software fallback above hardware capacity

If the deployed hardware is physically capped at `N <= 100`, then the runtime
must include a guard that declines unsupported QE subspace sizes.

## Problem Formulation

The accelerator should be built around these primitives:

- Complex matrix-vector multiply: `y = H_sub x`
- Optional complex matrix-vector multiply: `z = S_sub x`
- Block form:
  `Y = H_sub X`, `Z = S_sub X`

These are the dominant structured operations that recur inside subspace methods.
The accelerator should not try to perform arbitrary matrix rewriting in place.
That rules out schemes whose inner loop repeatedly updates matrix elements
through rotations.

## Recommended Algorithm Direction

### Standard problem

For the standard Hermitian problem, the most compatible outer methods are block
subspace iterations that repeatedly consume:

- `H_sub X`
- orthogonalization
- small Ritz or Rayleigh-Ritz projection

Examples:

- Block Davidson
- LOBPCG-style updates
- block power or filtered subspace iteration

For this hardware, the useful observation is that the expensive part is the
repeated dense complex multiply, while the control-heavy part remains small.

### Generalized problem

For the generalized Hermitian problem, there are two viable implementation
strategies:

1. Transform to a standard problem in near-memory logic:
   - factor `S_sub = L L^H`
   - form `A = L^{-1} H_sub L^{-H}`
   - solve `A y = lambda y`
2. Keep the problem in generalized form and build the iteration around
   repeated evaluation of:
   - `H_sub x`
   - `S_sub x`

For a first hardware generation, option 2 is often cleaner if the system
already has efficient support for both `H_sub x` and `S_sub x`, while option 1
is cleaner if the near-memory logic can comfortably handle dense factorizations
at the supported matrix size.

The key requirement is that the design must not assume `S_sub = I`. In QE,
that assumption is invalid for ultrasoft and PAW runs.

## Hardware / Software Split

### CIM array

The CIM block should only handle the dense linear algebra kernels that match its
strengths:

- complex dense matrix-vector multiply
- complex dense matrix-block-vector multiply

It should store:

- `H_sub`
- optionally `S_sub`

depending on the pseudopotential path and current solver mode.

### Near-memory logic

The near-memory logic should handle:

- vector normalization
- orthogonalization or QR
- residual formation
- Rayleigh quotient evaluation
- construction of small projected problems
- convergence checks
- optional Cholesky / triangular solves for generalized problems

This keeps matrix reads mostly static and avoids turning the CIM into a slow
random-update engine.

### Host side

The host runtime should handle:

- receiving `H_sub` and `S_sub` from the QE side
- dispatch policy
- size guardrails
- fallback to CPU when the matrix is outside supported bounds
- result marshaling back into the QE solver

## Data Representation

For a first implementation, use explicit full-matrix storage.

Reasons:

- the matrices are small
- full storage simplifies control and validation
- first silicon risk is lower

Although Hermitian symmetry can eventually be used to halve storage, that
optimization should be deferred until the baseline path is stable.

For complex data layout, keep real and imaginary parts in a regular,
address-stable format that minimizes packing overhead. Whether that is
row-interleaved or bank-split is an implementation detail, but the interface
must expose deterministic complex matrix and vector reads and writes.

## Non-goals For First Revision

The first revision should not attempt to be:

- a full dense LAPACK replacement
- a full-spectrum eigensolver
- a generic matrix-rotation engine
- a large-scale sparse solver
- a direct substitute for all QE diagonalization paths

The target remains narrow:

- repeated small dense Hermitian or generalized Hermitian subspace problems
- lowest `m` eigenpairs only
- complex `k`-point path first, `Gamma-only` as a natural simplification

## Integration Notes For QE

The QE-facing interface should be designed around the projected matrices, not
around the full `H|psi>` path.

That means the preferred insertion point is after the reduced matrices are built
and before the local dense eigensolver call, for example around the existing
`diaghg` usage in the subspace solvers.

This has two advantages:

- it minimizes intrusion into the much larger `h_psi` and FFT machinery
- it gives a well-bounded dense problem with stable dimensions

If the hardware path later proves more effective for repeated `H_sub x` and
`S_sub x` than for one-shot dense diagonalization, a second-stage integration
can move upward into the iterative small-matrix solve itself.

## Validation Plan

The first validation milestone should check:

1. Correct eigenvalues against QE CPU reference for standard Hermitian cases.
2. Correct eigenvalues and eigenvectors against QE CPU reference for generalized
   Hermitian cases.
3. Stability under complex `k`-point matrices.
4. Proper fallback when the subspace size exceeds hardware capacity.
5. End-to-end reintegration into a QE-like reduced solver harness before any
   direct QE patching.

## Summary

The correct design target is not "general small-matrix diagonalization" in the
abstract. It is:

- QE reduced subspace matrices
- complex Hermitian first
- generalized Hermitian included in the design boundary
- lowest `m` eigenpairs only
- repeated invocation inside an outer eigensolver

Under that framing, the CIM should be treated as a dense complex MVM engine,
while the near-memory logic retains the factorization, orthogonalization, and
control-heavy tasks that do not map well to static in-memory arrays.
