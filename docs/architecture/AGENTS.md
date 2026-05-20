# AGENTS Guide - docs/architecture/

## Purpose

Architecture docs define the generic accelerator DSE system: design-space axes, architecture templates, mapping boundaries, and promotion/evidence contracts.  Scoped proof-path manuals, such as the active DFT/QE full-SCF hardware DSE manual, may live here when they keep adapter/profile boundaries explicit and do not redefine reusable core contracts.

## Active content

- `generic_dse_framework_design_spec_v2.md` — current generic framework spec.
- `generic_dse_global_system_design_v0.md` — system-level DSE organization.
- `generic_dse_architecture_catalog_p2.md` — architecture-family catalog.
- `generic_dse/` — design-point, evaluation-result, and promotion notes.
- `architecture_templates/` — reusable architecture candidate JSON templates.
- `architecture_template_schema_v1.json` — schema for architecture templates.
- `dft_scf_hardware_dse_design_manual.md` — active DFT/QE full-SCF proof-path manual and claim-gate guide.

## Editing rules

- Keep architecture templates reusable across workload families.
- Do not encode one application’s correctness tolerance as a global requirement.
- If a template has a domain-specific assumption, put it in `metadata.adapter_notes` or keep it out of the active template set.
- Keep JSON valid and avoid generated result blobs in this directory.

## Validation

```bash
python3 - <<'PY'
import json, pathlib
for path in pathlib.Path('docs/architecture').rglob('*.json'):
    json.load(open(path, encoding='utf-8'))
print('architecture json ok')
PY
```
