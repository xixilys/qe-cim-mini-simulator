#!/usr/bin/env python3
"""SE-mode GenericAccel L4 descriptor/request/microarchitecture/completion run.

This config is intentionally narrow: it maps a guest-visible command workspace
and a high MMIO window, then runs generic_accel_l4_driver against the vendored
GenericAccel SimObject.  Completion is only meaningful when the GenericAccel
DPRINTF log shows descriptor_read/uarch_request_decode/microarchitecture_execute/
completion_writeback verified and the guest driver observes the completion
descriptor.
"""

import argparse
import os
from pathlib import Path

import m5
from m5.objects import *

REPO_ROOT = Path(__file__).resolve().parents[2]
MMIO_BASE = 0xF0000000
MMIO_SIZE = 0x10000
WORK_BASE = 0x08000000
WORK_SIZE = 0x240000


def default_driver():
    return REPO_ROOT / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver"


def default_simulator():
    return REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path(os.environ.get("GSIM_L4_DRIVER", default_driver())))
    parser.add_argument("--request", type=Path, required=True, help="Simulation request JSON passed to the guest driver")
    parser.add_argument("--simulator", type=Path, default=Path(os.environ.get("GSIM_L4_SIMULATOR", default_simulator())))
    parser.add_argument("--max-ticks", type=int, default=int(os.environ.get("GSIM_L4_MAX_TICKS", "10000000000")))
    parser.add_argument("--cpu-type", choices=["timing", "atomic"], default=os.environ.get("GSIM_L4_CPU", "timing"))
    return parser.parse_args()


def create_system(args):
    if not args.binary.exists():
        raise FileNotFoundError(f"L4 driver binary not found: {args.binary}")
    if not args.request.exists():
        raise FileNotFoundError(f"simulation request JSON not found: {args.request}")
    system = System()
    system.clk_domain = SrcClockDomain()
    system.clk_domain.clock = "1GHz"
    system.clk_domain.voltage_domain = VoltageDomain()
    system.mem_mode = "atomic" if args.cpu_type == "atomic" else "timing"
    system.mem_ranges = [AddrRange("512MiB")]

    system.cpu = AtomicSimpleCPU() if args.cpu_type == "atomic" else X86TimingSimpleCPU()
    system.membus = SystemXBar()

    system.cpu.icache_port = system.membus.cpu_side_ports
    system.cpu.dcache_port = system.membus.cpu_side_ports
    system.cpu.createInterruptController()
    system.cpu.interrupts[0].pio = system.membus.mem_side_ports
    system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
    system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports

    system.mem_ctrl = MemCtrl()
    system.mem_ctrl.dram = DDR3_1600_8x8()
    system.mem_ctrl.dram.range = system.mem_ranges[0]
    system.mem_ctrl.port = system.membus.mem_side_ports
    system.system_port = system.membus.cpu_side_ports

    system.generic_accel = GenericAccel(
        pio_addr=MMIO_BASE,
        pio_size=MMIO_SIZE,
        use_systemc=False,
        systemc_lib_path=str(args.simulator.resolve()),
    )
    system.generic_accel.pio = system.membus.mem_side_ports

    system.workload = SEWorkload.init_compatible(str(args.binary.resolve()))
    process = Process()
    process.cmd = [str(args.binary.resolve()), str(args.request.resolve())]
    system.cpu.workload = process
    system.cpu.createThreads()
    return system


def main():
    args = parse_args()
    system = create_system(args)
    root = Root(full_system=False, system=system)
    m5.instantiate()

    # SE-mode mappings: high MMIO -> GenericAccel PIO, fixed workspace -> DRAM.
    system.cpu.workload[0].map(MMIO_BASE, MMIO_BASE, MMIO_SIZE, False)
    system.cpu.workload[0].map(WORK_BASE, WORK_BASE, WORK_SIZE, True)

    print("GenericAccel L4 Test Starting...")
    print(f"Driver: {args.binary.resolve()}")
    print(f"Request: {args.request.resolve()}")
    print(f"Execution engine: gem5 GenericAccel microarchitecture model")
    print(f"Reference simulator argument (not required by L4 uarch path): {args.simulator.resolve()}")
    print(f"MMIO map: vaddr=0x{MMIO_BASE:X} paddr=0x{MMIO_BASE:X} size=0x{MMIO_SIZE:X}")
    print(f"Workspace map: vaddr=0x{WORK_BASE:X} paddr=0x{WORK_BASE:X} size=0x{WORK_SIZE:X}")
    print(f"CPU: {args.cpu_type}; max_ticks={args.max_ticks}")

    exit_event = m5.simulate(args.max_ticks)
    print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")


if __name__ == "__m5_main__":
    main()
