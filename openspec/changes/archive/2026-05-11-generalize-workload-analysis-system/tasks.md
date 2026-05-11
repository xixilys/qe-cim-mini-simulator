## 1. OpenSpec and Contract Validation

- [x] 1.1 Validate the `generalize-workload-analysis-system` OpenSpec change with strict validation and fix any artifact/schema issues.
- [x] 1.2 Confirm the new broad workload analysis capability and affected delta specs are present in the change status output.

## 2. Generic Workload Implementation

- [x] 2.1 Strengthen workload registry tests so built-in non-QE families are treated as acceptance paths with complete workflow metadata.
- [x] 2.2 Strengthen adapter/package tests so generated non-QE workload packages enter the pipeline without QE-only fields or QE coverage.
- [x] 2.3 Strengthen Step2 mapping tests so non-QE executable graphs produce mapping artifacts without QE node ids or SCF phase assumptions.
- [x] 2.4 Strengthen Step3/reporting tests so generic timing/resource claims are separated from adapter-owned domain correctness claims.

## 3. Documentation Reframing

- [x] 3.1 Update `dse_v2/README.md` to present DSE v2 as a broad workload analysis and DSE framework with QE as a reference adapter.
- [x] 3.2 Update the main DSE v2 quick/run documentation that still frames the workflow as QE-first, while preserving existing QE example commands as adapter examples.

## 4. Verification

- [x] 4.1 Run focused workload, Step2, Step3, and reporting tests that cover non-QE and QE regression paths.
- [x] 4.2 Run OpenSpec validation for the change after implementation.
- [x] 4.3 Run a manual generic workload workflow command or test entry point and record the observed output.
