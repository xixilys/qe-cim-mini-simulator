## 1. Config Enhancement

- [ ] 1.1 Write enhanced `openspec/config.yaml` with project context, tech stack, domain knowledge, conventions, and per-artifact rules
- [ ] 1.2 Validate config.yaml syntax and structure
- [ ] 1.3 Verify config content covers all spec requirements (project identity, tech stack, domain, conventions, rules, testing, documentation)

## 2. Spec Promotion

- [ ] 2.1 Create `openspec/specs/generic-workload-workflows/spec.md` from change-local spec
- [ ] 2.2 Create `openspec/specs/step2-architecture-mapping-workflow/spec.md` from change-local spec
- [ ] 2.3 Create `openspec/specs/step3-simulation-evidence-workflow/spec.md` from change-local spec
- [ ] 2.4 Update cross-references in existing root specs (end-to-end-dse-workflow, multi-fidelity-dse-evaluation)
- [ ] 2.5 Verify promoted specs have stable schema versions and provenance links

## 3. Validation Tooling

- [ ] 3.1 Implement `scripts/validate_openspec.py` to check config completeness
- [ ] 3.2 Add spec cross-reference validation
- [ ] 3.3 Add orphaned file detection
- [ ] 3.4 Run validation script and fix any issues

## 4. Testing and Verification

- [ ] 4.1 Run DSE v2 test suite (79 tests) to ensure no regressions
- [ ] 4.2 Run OpenSpec validation script
- [ ] 4.3 Verify all spec files are readable and well-formed
- [ ] 4.4 Archive source changes after successful promotion

## 5. Documentation

- [ ] 5.1 Update architecture handbook with new spec hierarchy
- [ ] 5.2 Update traceability matrix with promoted specs
- [ ] 5.3 Document validation script usage in README
