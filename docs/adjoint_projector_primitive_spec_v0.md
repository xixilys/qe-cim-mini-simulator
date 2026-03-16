# Adjoint-Aware Projector Primitive Spec v0

## 1. Purpose

This document defines the primitive we want to explore as the next main hardware direction.

It is **not**:

- a generic `GEMM` replacement
- a full eigensolver
- a precision-only story
- a paper title yet

It **is**:

- a workload-native primitive for projector / basis / subspace style operators
- a hardware contract that sits between plain `GEMM` and a full iterative solver
- a candidate circuit-level innovation point for `QE / VASP / PySCF`-like workloads

The core idea is to capture a recurring pattern:

```text
project -> small transform -> back-project
```

instead of treating every step as disconnected `GEMM` or `transpose` support.

## 2. Primitive Name

Working name:

- `Adjoint-Aware Projector Primitive`

Short aliases:

- `AAP primitive`
- `Bra-Ket fused primitive`

The name emphasizes that the hardware must support:

- a resident projector/basis `P`
- both `P` and `P^H`
- optional local reduction
- a small center transform `M`

The name deliberately does **not** emphasize:

- `FP64`
- `transpose`
- `Davidson`
- `QE`

because those are implementation choices or upper-layer use cases, not the primitive itself.

## 3. Core Mathematical Semantics

## 3.1 Main operator

The primitive is centered on the operator

```text
Y = P M P^H X
```

where:

- `P ∈ C^(N×K)`
  - resident projector / basis / ACE vectors / beta projectors / subspace basis
- `X ∈ C^(N×B)`
  - streamed input block
- `M ∈ C^(K×K)`
  - a small center matrix stored locally near the macro
- `Y ∈ C^(N×B)`
  - output block

The operation is decomposed as:

```text
C = P^H X      (forward projection)
T = M C        (small center transform)
Y = P T        (adjoint/back projection)
```

This is the fundamental semantic contract.

## 3.2 Optional reduced output

Many workloads do not need only `Y`; they also need a reduced matrix.

The primitive therefore also supports:

```text
G = X^H Y = X^H P M P^H X
```

Since `C = P^H X`, this can be rewritten as:

```text
G = C^H M C
```

This matters because it means the reduced result can often be built **without writing back the full `Y`**.

## 3.3 Real and complex cases

For the real case:

```text
P^H = P^T
```

For the complex case:

```text
P^H = conj(P)^T
```

This distinction is important.  
The primitive is **adjoint-aware**, not merely transpose-aware.

That is why “support transpose” is only one hardware mechanism inside this story, not the story itself.

## 4. Operand Roles

## 4.1 Resident operand: `P`

`P` is the key resident operand.

Typical meanings:

- `QE` nonlocal projector bank `vkb`
- `QE` ACE projector `xi`
- subspace basis `Q`
- localized basis blocks
- compressed low-rank basis or screened auxiliary basis

The primitive only makes sense if `P` has strong temporal reuse across many `X`.

## 4.2 Streamed operand: `X`

`X` is the moving operand.

Typical meanings:

- a wavefunction block `psi`
- a trial subspace block
- a residual/update block
- a batch of orbitals
- a density-pair or orbital-pair block

The hardware assumption is that `X` changes much more frequently than `P`.

## 4.3 Local center operand: `M`

`M` is intentionally small and local.

Typical meanings:

- nonlocal pseudopotential coefficient block `D`
- a reduced rotation matrix `U`
- a reduced basis transform
- a small diagonal or block-diagonal weight
- a compact screened kernel block

`M` is **not** the resident large matrix.  
If `M` becomes large and dynamic, the primitive collapses back toward generic `GEMM`.

## 5. Primitive Family

The fully fused primitive is `Y = P M P^H X`, but hardware should expose a small family of modes around the same resident data organization.

## 5.1 `FWD_PROJ`

```text
C = P^H X
```

Meaning:

- forward projection
- bra-side contraction
- coefficient extraction

Typical use:

- `<vkb|psi>`
- `<xi|phi>`
- `Q^H Z`

## 5.2 `CENTER_APPLY`

```text
T = M C
```

Meaning:

- local dense transform in the small projected space

Typical use:

- `D * becp`
- local rotation/update on reduced coefficients
- applying small block transforms without leaving the near-macro domain

## 5.3 `BACK_PROJ`

```text
Y = P T
```

Meaning:

- ket-side synthesis
- back-projection to the large space

Typical use:

- `vkb * ps`
- `xi * coeff`
- `X <- QY`

## 5.4 `FUSED_APPLY`

```text
Y = P M P^H X
```

Meaning:

- full projector sandwich

This is the most important fused mode because it avoids exposing the large intermediate tensors `C` and `T` off-macro.

## 5.5 `FUSED_REDUCE`

```text
G = X^H P M P^H X = C^H M C
```

Meaning:

- reduced matrix build
- Gram/overlap/projection result generation

This mode is critical for subspace workloads because it can eliminate a writeback-and-readback round trip.

## 6. Hardware Boundary

## 6.1 What the primitive is responsible for

The primitive is responsible for:

- resident storage of `P`
- reading `P` in both forward and adjoint views
- optional on-the-fly conjugation
- streamed input consumption for `X`
- local formation of `C = P^H X`
- local application of small `M`
- local synthesis of `Y = P T`
- optional reduced accumulation for `G`

## 6.2 What the primitive is not responsible for

The primitive is not responsible for:

- outer-loop convergence
- residual generation policy
- orthogonalization policy
- full eigensolver control
- host runtime decisions
- global scheduling across the entire application

Those belong to the engine/controller level above the primitive.

## 7. Abstract Hardware Interface

One possible abstract interface is:

```text
bind_projector(tag_P, N, K, layout, datatype)
load_projector(tag_P, P)

bind_center(tag_M, K, datatype)
load_center(tag_M, M)

run_aap(
    mode,
    tag_P,
    tag_M,
    X_desc,
    output_mask,
    flags
)
```

where:

- `mode`
  - `FWD_PROJ`
  - `BACK_PROJ`
  - `FUSED_APPLY`
  - `FUSED_REDUCE`
- `output_mask`
  - emit `C`
  - emit `Y`
  - emit `G`
- `flags`
  - real vs complex
  - conjugate enable
  - triangular compression enable
  - reduced-only writeback

This interface is intentionally neutral with respect to analog/digital CIM implementation.

## 8. Minimal Microarchitecture

## 8.1 Resident projector banks

Need:

- storage for `P`
- stable indexing by row/column tile
- the ability to feed both projection and back-projection phases

This may be implemented using:

- single stored copy plus dual-view read support
- or explicitly stored layout variants if the cost model says that is better

The architectural point is:

- the primitive must expose both `P` and `P^H`
- not necessarily that it stores two full physical copies

## 8.2 Adjoint/transpose access path

This is where “transpose support” actually lives.

Required capabilities:

- read the resident projector in forward view for `P T`
- read the same resident projector in adjoint view for `P^H X`
- apply conjugation when complex mode is enabled

This block is a **mechanism**, not the final innovation claim.

## 8.3 Projection accumulator

This block forms:

```text
C = P^H X
```

It must support:

- blockwise accumulation over the large dimension `N`
- local retention of `C`
- optional compression if only a subset is needed

## 8.4 Small center matrix engine

This block applies:

```text
T = M C
```

Requirements:

- optimized for small `K×K`
- low setup overhead
- able to consume local `C` directly

This can live in:

- near-memory logic
- a compact digital dense unit
- or a local specialized datapath

It does not need a large matrix engine.

## 8.5 Back-projection engine

This block forms:

```text
Y = P T
```

It reuses the resident `P` bank, now in forward mode.

## 8.6 Reduced-result accumulator

This optional block forms:

```text
G = X^H Y
```

or, when `C` is already present:

```text
G = C^H M C
```

This block should exploit:

- Hermitian symmetry when applicable
- triangular writeout
- local accumulation and reduced writeback

## 9. Dataflow

## 9.1 Full fused flow

The intended full fused flow is:

```text
X stream in
-> adjoint-view read of P
-> local projection C = P^H X
-> local center transform T = M C
-> forward-view read of P
-> back-project Y = P T
-> optional reduced accumulation G
-> selective writeback of Y and/or G
```

## 9.2 Why this matters

Compared with a naive decomposition into separate kernels:

1. `C = P^H X`
2. write `C`
3. `T = M C`
4. write `T`
5. `Y = P T`
6. write `Y`
7. read `Y`
8. build `G = X^H Y`

the fused primitive can save:

- repeated input encoding
- repeated projector fetch
- repeated intermediate writeback
- repeated intermediate readback
- unnecessary full-size output traffic

This is the main reason the primitive could be worth defining at all.

## 10. Detailed Relation to QE / VASP / PySCF

## 10.1 QE nonlocal pseudopotential / PAW-like path

The nonlocal path in `QE` looks like:

```text
becp = <vkb | psi>
ps   = D * becp
hpsi = hpsi + vkb * ps
```

This maps directly to:

- `P = vkb`
- `X = psi`
- `M = D`
- `Y = vkb * D * vkb^H * psi`

This is the cleanest example of the primitive.

## 10.2 QE ACE / EXX path

The ACE-style path has the same outer shape:

```text
coeff = <xi | phi>
vv    = xi * coeff
```

This is the special case:

```text
Y = P I P^H X
```

with:

- `P = xi`
- `M = I` or a small coefficient transform near identity

The key hardware lesson is the same:

- very high reuse of a resident projector bank
- streamed input block
- local coefficient generation
- back-projection

## 10.3 QE / VASP subspace rotation and basis update

For subspace work, the primitive is not always used as a single full `P M P^H X` kernel, but the same hardware family still applies.

Examples:

```text
X <- QY
```

is just:

```text
BACK_PROJ with P = Q
```

and:

```text
Q^H Z
```

is:

```text
FWD_PROJ with P = Q
```

Reduced builds such as:

```text
Q^H H Q
Q^H S Q
```

can be formed by composing:

1. an operator-apply primitive producing `Z = H Q` or `Z = S Q`
2. this primitive in `FWD_PROJ` / reduced mode to build `Q^H Z`

So the primitive is still relevant even when the full sandwich is split across two hardware stages.

## 10.4 PySCF FFTDF / pair-density style path

PySCF does not always match the full `P M P^H X` form exactly, but it repeatedly exhibits the same skeleton:

- build projected/pair coefficients
- apply a small/structured kernel
- use conjugate-related inverse/adjoint reconstruction
- accumulate a reduced result

Therefore the primitive family is still relevant, especially the ideas of:

- adjoint-aware resident data
- local center transform
- reduced-only writeback

## 11. Why This Is Not “Just Transpose Support”

If the claim is only:

- “the macro supports transpose”

then the hardware contribution is too shallow.

The actual intended claim is:

- the macro supports a fused projector sandwich
- with resident `P`
- shared data movement for forward and adjoint phases
- local center transform
- optional reduced-result emission

In this story:

- transpose/adjoint access is necessary
- but it is only one sub-mechanism

## 12. Why This Is Not “Just GEMM”

Generic `GEMM` can of course implement this pattern.

But the primitive is still distinct because it assumes and exploits:

- one large operand `P` is resident and heavily reused
- the center matrix `M` is small
- intermediate coefficient blocks `C` and `T` are local
- reduced result `G` is often more valuable than the full output `Y`
- Hermitian and conjugate structure can be exploited

When these assumptions hold, `GEMM` is functionally sufficient but not semantically efficient.

## 13. Where the Cost Advantage Must Come From

For the primitive to be worth building, its measured or modeled advantages must come from at least some of the following:

1. fewer projector reads than a decomposed implementation
2. fewer intermediate SRAM/DRAM writes
3. fewer intermediate SRAM/DRAM reads
4. lower activation cost through shared forward/adjoint scheduling
5. lower output traffic when only `G` is needed
6. smaller energy per useful reduced result

If none of these hold, the primitive should be rejected and the design should stay at `GEMM + transpose support`.

## 14. Required Comparators

Any future paper built on this primitive should compare against:

1. `GEMM baseline`
   - decompose into explicit `P^H X`, `M C`, `P T`

2. `GEMM + transpose-aware macro`
   - same algebraic decomposition, but with improved transpose support

3. `Fused AAP primitive`
   - local `C/T`
   - local reduced accumulation
   - selective writeback

This is critical because it isolates whether the gain comes from:

- better transpose support
- or from primitive-level fusion

## 15. Non-goals for v0

To keep this primitive manageable, v0 should **not** try to solve:

- full FFT-integrated flow
- global sparse/dense mixed scheduling
- full host runtime and compiler stack
- all DFT kernels at once
- all possible projector families

v0 only needs to make the primitive precise and testable.

## 16. v0 Research Questions

The next concrete questions should be:

1. Which `QE` paths most cleanly instantiate `P M P^H X`?
2. Can we quantify reuse for `vkb`, `xi`, and `Q` on real traces?
3. What is the best resident layout for supporting both `P` and `P^H`?
4. Is local reduced accumulation more valuable than full-output writeback?
5. Does the primitive remain beneficial once realistic buffer and control cost are included?

## 17. One-Sentence Definition

The primitive can be summarized in one sentence as:

```text
An adjoint-aware resident-projector primitive that maps streamed blocks X to
Y = P M P^H X, with optional reduced output G = X^H P M P^H X and local
retention of the projected coefficients.
```

That is the definition we should treat as the current working contract.
