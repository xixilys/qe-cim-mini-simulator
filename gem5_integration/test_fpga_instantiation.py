#!/usr/bin/env python3
"""
Test script to verify FPGAAccelerator can be instantiated in gem5
"""

import sys
sys.path.insert(0, '/Volumes/remote/phd/year_2/project/dft加速/gem5_integration/gem5/build/X86/python')

import m5
from m5.objects import *

print("=" * 60)
print("Testing FPGAAccelerator Instantiation")
print("=" * 60)

# Test 1: Check if FPGAAccelerator is available
print("\n[Test 1] Checking if FPGAAccelerator is in m5.objects...")
if hasattr(m5.objects, 'FPGAAccelerator'):
    print("✓ FPGAAccelerator found in m5.objects")
else:
    print("✗ FPGAAccelerator NOT found")
    sys.exit(1)

# Test 2: Try to instantiate FPGAAccelerator
print("\n[Test 2] Instantiating FPGAAccelerator...")
try:
    fpga = FPGAAccelerator()
    print(f"✓ FPGAAccelerator instantiated successfully")
    print(f"  Type: {fpga.type}")
    print(f"  BAR0: {fpga.BAR0}")
    print(f"  PIO Latency: {fpga.pio_latency}")
except Exception as e:
    print(f"✗ Failed to instantiate: {e}")
    sys.exit(1)

# Test 3: Check PCI configuration
print("\n[Test 3] Checking PCI configuration...")
try:
    print(f"  Vendor ID: {fpga.VendorID}")
    print(f"  Device ID: {fpga.DeviceID}")
    print(f"  Class Code: {fpga.ClassCode}")
    print("✓ PCI configuration accessible")
except Exception as e:
    print(f"✗ Failed to access PCI config: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("All tests passed! FPGAAccelerator is ready to use.")
print("=" * 60)
