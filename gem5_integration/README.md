# gem5 GenericAccel Integration

This directory contains the generic gem5 co-simulation lane for the DSE stack.

## Active pieces

- `src/dev/generic_accel/` — GenericAccel SimObject and MMIO/descriptor protocol.
- `configs/generic_accel_l4_test.py` — SE-mode L4 descriptor/request/microarchitecture/completion config.
- `test_programs/generic_accel/generic_accel_l4_driver.c` — guest driver used by the L4 harness.
- `gem5/` — local vendored/build workspace, ignored by git.

## L4 evidence boundary

A trusted L4 result requires all of the following:

1. guest driver writes a GSIM command descriptor;
2. GenericAccel reads the descriptor and request payload;
3. GenericAccel decodes the request and executes the in-gem5 microarchitecture schedule;
4. completion/result data is written back to guest-visible memory;
5. `gem5.log`, stdout/stderr, and descriptor artifacts are captured.

If any required artifact is missing, the adapter must emit a blocked result rather than fabricating passed evidence.

## Typical paths

```bash
# L4 pilot via DSE wrapper
python3 dse_v2/scripts/dse/run_full_flow_pilot.py \
  --backend gem5_systemc \
  --gem5-real-l4 \
  --gem5-binary gem5_integration/gem5/build/X86/gem5.opt \
  --gem5-config gem5_integration/configs/generic_accel_l4_test.py \
  --gem5-driver gem5_integration/test_programs/generic_accel/generic_accel_l4_driver \
  --out runs/dse/generic_l4_pilot
```

`generic_sim` remains the L3 backend and an optional diagnostic fallback input;
the trusted L4 path above does not require it.
