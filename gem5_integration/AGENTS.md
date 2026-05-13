# AGENTS Guide - gem5_integration/

## Scope

This directory owns the generic gem5 L4 path for DSE evidence.  The mainline device is `src/dev/generic_accel/`.

## Active files

- `src/dev/generic_accel/` — GenericAccel SimObject implementation.
- `configs/generic_accel_l4_test.py` — L4 config.
- `test_programs/generic_accel/generic_accel_l4_driver.c` — guest driver.

## Rules

- Do not revive legacy app-specific offload hooks without an explicit scoped request.
- Keep logs and `m5out*` outputs out of git.
- L4 claims must be evidence-gated: descriptor read, request decode, in-gem5 microarchitecture execution, completion writeback, and guest status must all be observable.
- If gem5 or the driver binary is missing, return blocked evidence rather than a synthetic pass.

## Validation

For Python/config changes:

```bash
python3 -m py_compile gem5_integration/configs/generic_accel_l4_test.py
python3 -m compileall gem5_integration/src/dev/generic_accel
```
