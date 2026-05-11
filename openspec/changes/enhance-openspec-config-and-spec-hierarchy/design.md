## Context

The OpenSpec configuration (`openspec/config.yaml`) currently lacks project context, preventing AI assistants from understanding the DFT acceleration project's technical stack, domain constraints, and conventions. Three completed change-local specs (generic-workload-workflows, step2-architecture-mapping-workflow, step3-simulation-evidence-workflow) exist only in `openspec/changes/` and need promotion to root-level capabilities to establish a complete, stable spec hierarchy.

The DSE v2 framework has 79 passing tests covering Step1→Step2→Step3 workflows, but the spec hierarchy does not yet reflect this maturity. Root specs exist for IR contracts, architecture description, multi-fidelity evaluation, simulation backend, end-to-end workflow, and QE workload adapter—but the workflow boundary specs remain change-local.

## Goals / Non-Goals

**Goals:**
- Define a complete `openspec/config.yaml` with project context, tech stack, domain knowledge, conventions, and per-artifact rules
- Promote 3 change-local specs to root-level capabilities with stable contracts
- Ensure cross-references between root specs are consistent and machine-verifiable
- Add validation tooling to detect spec incompleteness and broken references

**Non-Goals:**
- Do not modify the 6 existing root spec requirements (only add cross-references)
- Do not reimplement DSE v2 code (spec-only change)
- Do not require new simulator builds or QE runs
- Do not change test behavior (tests validate spec compliance, not vice versa)

## Decisions

### Decision 1: Config context uses structured YAML, not free-form text

The `context` block in `config.yaml` uses structured fields (`tech_stack`, `domain`, `conventions`, `project_phase`) rather than a single prose paragraph. This enables validation tooling to check for required fields and allows AI assistants to consume context programmatically.

Rationale: Structured context is parseable and enforceable. Alternative rejected: free-form text block because it cannot be validated and may omit critical fields.

### Decision 2: Change-local specs are promoted by copy, not move

The original change-local specs remain in `openspec/changes/*/specs/` for historical provenance. Root-level copies are created in `openspec/specs/<name>/spec.md` with updated cross-references and stable schema versions.

Rationale: Preserves change history and audit trail. Alternative rejected: moving files because it breaks git history and change-level references.

### Decision 3: Root specs use schema version tags for stability

Each promoted spec includes a `schema_version` field in its metadata to enable future versioning without breaking existing references.

Rationale: Versioned specs support evolution. Alternative rejected: unversioned specs because they cannot track contract changes.

### Decision 4: Validation tooling is a Python script, not OpenSpec built-in

A standalone `scripts/validate_openspec.py` checks config completeness, spec cross-references, and orphaned files. It runs as part of the test suite.

Rationale: Project-specific validation rules need custom logic. Alternative rejected: relying solely on OpenSpec CLI because it cannot enforce project-specific constraints like DSE workflow completeness.

## Risks / Trade-offs

- [Risk] Config context becomes stale as project evolves. → Mitigation: Include `last_updated` field and validate context freshness in CI.
- [Risk] Promoted specs diverge from change-local originals. → Mitigation: Add provenance comments linking back to source changes; archive changes after promotion.
- [Risk] Cross-reference validation is brittle. → Mitigation: Use stable kebab-case identifiers and validate references against file system.
- [Risk] Per-artifact rules are too restrictive. → Mitigation: Rules are guidelines, not hard constraints; mark optional vs required.

## Migration Plan

1. Write enhanced `openspec/config.yaml` with full context and rules
2. Create root-level spec directories and copy promoted specs
3. Update cross-references in existing root specs
4. Implement `scripts/validate_openspec.py`
5. Run validation and fix any issues
6. Run DSE v2 tests to ensure no regressions
7. Archive the 3 source changes (mark as promoted)

Rollback: Revert `config.yaml` and remove new spec directories. Change-local originals remain untouched.

## Open Questions

- Should the validation script enforce spec file naming conventions (kebab-case directories)?
- Should config.yaml include AI assistant behavior hints (e.g., "prefer C++17 over C++20")?
- How often should config context be reviewed for freshness?
