import argparse
import os

import m5
from m5.objects import *


IO_ADDRESS_SPACE_BASE = 0x8000000000000000
PCI_CONFIG_ADDRESS_SPACE_BASE = 0xC000000000000000
INTERRUPTS_ADDRESS_SPACE_BASE = 0xA000000000000000
APIC_RANGE_SIZE = 1 << 12


def default_binary():
    """Return a local x86 static binary suitable for a runtime smoke."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    gem5_root = os.path.abspath(os.path.join(script_dir, "..", "gem5"))
    hello = os.path.join(gem5_root, "tests", "test-progs", "hello", "bin", "x86", "linux", "hello")
    if os.path.exists(hello):
        return hello
    return os.path.abspath(os.path.join(script_dir, "..", "qe_test_program", "fpga_test"))


def create_bridge(system):
    """Route x86 IO, PCI config, and PCI MMIO ranges through the IO bus."""
    system.bridge = Bridge(delay="50ns")
    system.bridge.cpu_side_port = system.membus.mem_side_ports
    system.bridge.mem_side_port = system.iobus.cpu_side_ports
    system.bridge.ranges = [
        AddrRange(0xC0000000, 0xFFFF0000),
        AddrRange(IO_ADDRESS_SPACE_BASE, INTERRUPTS_ADDRESS_SPACE_BASE - 1),
        AddrRange(PCI_CONFIG_ADDRESS_SPACE_BASE, Addr.max),
    ]

    system.apicbridge = Bridge(delay="50ns")
    system.apicbridge.cpu_side_port = system.iobus.mem_side_ports
    system.apicbridge.mem_side_port = system.membus.cpu_side_ports
    system.apicbridge.ranges = [
        AddrRange(
            INTERRUPTS_ADDRESS_SPACE_BASE,
            INTERRUPTS_ADDRESS_SPACE_BASE + APIC_RANGE_SIZE - 1,
        )
    ]


def create_test_system(binary_path):
    """Create a minimal SE-mode x86 system with a real PCI FPGA endpoint.

    gem5 25.1 routes PCI devices through the x86 Pc platform's PcPciHost and
    PciBus helpers.  Instantiating a bare GenericPciHost with a generic
    Platform leaves the host's platform Param unresolved at C++ construction
    time, so this smoke intentionally uses Pc.attachIO() and
    Pc.attachPciDevice().
    """
    system = System()

    if "SystemC_Kernel" in globals():
        system.systemc_kernel = SystemC_Kernel()

    system.clk_domain = SrcClockDomain()
    system.clk_domain.clock = "3GHz"
    system.clk_domain.voltage_domain = VoltageDomain()

    system.mem_mode = "timing"
    system.mem_ranges = [AddrRange("512MiB")]

    system.cpu = X86TimingSimpleCPU()
    system.cpu.createInterruptController()

    system.membus = SystemXBar()
    system.iobus = IOXBar()
    create_bridge(system)

    system.cpu.icache_port = system.membus.cpu_side_ports
    system.cpu.dcache_port = system.membus.cpu_side_ports
    system.cpu.interrupts[0].pio = system.membus.mem_side_ports
    system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
    system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports

    system.mem_ctrl = MemCtrl()
    system.mem_ctrl.dram = DDR3_1600_8x8()
    system.mem_ctrl.dram.range = system.mem_ranges[0]
    system.mem_ctrl.port = system.membus.mem_side_ports

    print("Creating x86 Pc platform and PCI host bridge...")
    system.pc = Pc()
    system.pc.pci_bus.frontend_latency = 0
    system.pc.pci_bus.forward_latency = 0
    system.pc.pci_bus.response_latency = 0
    system.pc.attachIO(system.iobus)

    print("Creating FPGAAccelerator PCI endpoint...")
    system.fpga = FPGAAccelerator(
        upstream=system.pc.pci_host,
        pci_dev=8,
        pci_func=0,
        VendorID=0x10EE,
        DeviceID=0x9038,
        SubsystemVendorID=0x0000,
        SubsystemID=0x0000,
        Revision=0x00,
        ProgIF=0x00,
        SubClassCode=0x00,
        ClassCode=0x12,
        InterruptLine=0x0B,
        InterruptPin=0x01,
    )
    system.pc.attachPciDevice(system.fpga)

    system.system_port = system.membus.cpu_side_ports

    system.workload = SEWorkload.init_compatible(binary_path)
    process = Process()
    process.cmd = [binary_path]
    system.cpu.workload = process
    system.cpu.createThreads()

    return system


if __name__ == "__m5_main__":
    parser = argparse.ArgumentParser(description="Test FPGA PCI device instantiation")
    parser.add_argument(
        "--binary",
        type=str,
        default=default_binary(),
        help="Path to an x86 Linux test binary. Defaults to gem5's static hello.",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=1000000000,
        help="Bound runtime smoke ticks; use 0 for an unbounded simulation.",
    )
    args = parser.parse_args()
    binary = os.path.abspath(args.binary)
    if not os.path.exists(binary):
        raise FileNotFoundError(f"test binary not found: {binary}")

    print("=" * 60)
    print("gem5 FPGA PCI Device Runtime Smoke")
    print("=" * 60)
    print(f"Binary: {binary}")
    print(f"Max ticks: {args.max_ticks if args.max_ticks else 'unbounded'}")

    system = create_test_system(binary)
    root = Root(full_system=False, system=system)

    print("\nInstantiating system...")
    m5.instantiate()
    print("System instantiated successfully.")

    print("\nFPGA Device Information:")
    print(f"  Device object: {system.fpga}")
    print(f"  Device type: {type(system.fpga).__name__}")
    print(f"  PCI upstream: {system.fpga.upstream}")
    print(f"  PCI bus: {system.pc.pci_bus}")

    print("\nBeginning simulation...")
    if args.max_ticks:
        exit_event = m5.simulate(args.max_ticks)
    else:
        exit_event = m5.simulate()

    print("\n" + "=" * 60)
    print("Simulation completed.")
    print(f"Exit @ tick {m5.curTick()} because {exit_event.getCause()}")
    print("=" * 60)
