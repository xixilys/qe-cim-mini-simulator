#!/usr/bin/env python3
"""Verify FPGAAccelerator objects through gem5's embedded Python runtime.

gem5 25.x keeps generated SimObject bindings inside the gem5 executable rather
than as ordinary importable files under build/X86/python/m5/objects.  A direct
standalone `python3 -c "from m5.objects import *"` check can therefore report
false negatives even when gem5 can instantiate the objects from a config file.
"""

import os
import subprocess
import sys
import tempfile
import textwrap


def main():
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    gem5_opt = os.path.join(repo_dir, "gem5", "build", "X86", "gem5.opt")
    if not os.path.exists(gem5_opt):
        print(f"✗ gem5.opt not found: {gem5_opt}")
        return 1

    config = textwrap.dedent(
        """
        from m5.objects import *

        print("Testing FPGA SimObject availability inside gem5...")
        print(f"✓ FPGAAccelerator class: {FPGAAccelerator}")
        print(f"✓ FPGAAcceleratorSE class: {FPGAAcceleratorSE}")

        pci_dev = FPGAAccelerator(pci_dev=8, pci_func=0)
        se_dev = FPGAAcceleratorSE(pio_addr=0xF0000000)

        print(f"✓ FPGAAccelerator Python object instantiated: {pci_dev}")
        print(f"✓ FPGAAcceleratorSE Python object instantiated: {se_dev}")
        print("\\n✓ All FPGA SimObject availability checks passed!")
        """
    )

    with tempfile.NamedTemporaryFile("w", suffix="_fpga_object_check.py", delete=False) as handle:
        handle.write(config)
        config_path = handle.name

    try:
        completed = subprocess.run(
            [gem5_opt, config_path],
            cwd=repo_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    finally:
        os.unlink(config_path)

    print(completed.stdout, end="")
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
