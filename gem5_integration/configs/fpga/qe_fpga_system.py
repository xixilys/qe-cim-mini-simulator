import m5
from m5.objects import *
from m5.objects.X86CPU import X86AtomicSimpleCPU, X86TimingSimpleCPU
from m5.util import addToPath
import argparse
import os
import shlex

addToPath('../')


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.lower() in ("1", "true", "yes", "on")

def create_fpga_system(args):
    system = System()
    
    system.clk_domain = SrcClockDomain()
    system.clk_domain.clock = '3GHz'
    system.clk_domain.voltage_domain = VoltageDomain()
    
    system.mem_mode = 'atomic' if args.cpu_type == 'atomic' else 'timing'
    system.mem_ranges = [AddrRange('8GB')]
    system.platform = Pc()
    
    if args.cpu_type == 'atomic':
        system.cpu = X86AtomicSimpleCPU()
    else:
        system.cpu = X86TimingSimpleCPU()
    system.cpu.isa = [X86ISA()]
    system.cpu.createInterruptController()
    
    system.membus = SystemXBar()
    system.cpu.icache_port = system.membus.cpu_side_ports
    system.cpu.dcache_port = system.membus.cpu_side_ports
    system.cpu.interrupts[0].pio = system.membus.mem_side_ports
    system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
    system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports
    
    system.mem_ctrl = MemCtrl()
    system.mem_ctrl.dram = DDR4_2400_16x4()
    system.mem_ctrl.dram.range = system.mem_ranges[0]
    system.mem_ctrl.port = system.membus.mem_side_ports
    
    system.iobus = IOXBar()
    system.bridge = Bridge(delay="50ns")
    system.bridge.cpu_side_port = system.membus.mem_side_ports
    system.bridge.mem_side_port = system.iobus.cpu_side_ports
    system.bridge.ranges = [
        AddrRange(0x8000000000000000, 0x9FFFFFFFFFFFFFFF),
        AddrRange(0xC000000000000000, Addr.max),
    ]
    system.apicbridge = Bridge(delay="50ns")
    system.apicbridge.cpu_side_port = system.iobus.mem_side_ports
    system.apicbridge.mem_side_port = system.membus.cpu_side_ports
    system.apicbridge.ranges = [
        AddrRange(0xA000000000000000, 0xA000000000000FFF),
    ]

    system.platform.attachIO(system.iobus)
    
    system.fpga = FPGAAccelerator(
        pci_dev=5,
        pci_func=0,
        execution_mode=args.fpga_execution_mode,
        real_systemc_target=args.real_systemc_target,
        roi_stats_enabled=not args.disable_roi_stats,
        roi_label=args.roi_label,
    )
    system.fpga.upstream = system.platform.pci_host
    system.platform.attachPciDevice(system.fpga)
    
    system.system_port = system.membus.cpu_side_ports
    
    process = Process()
    process.cmd = [args.binary] + shlex.split(args.options)
    system.workload = SEWorkload.init_compatible(args.binary)
    system.cpu.workload = process
    system.cpu.createThreads()
    
    return system

if __name__ == "__m5_main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=str, required=True,
                       help="Path to binary to execute")
    parser.add_argument("--options", type=str, default="",
                       help="Options to pass to binary")
    parser.add_argument(
        "--fpga-execution-mode",
        choices=["smoke", "timed_proxy", "real_bridge"],
        default=os.environ.get("QEBS_FPGA_EXECUTION_MODE", "smoke"),
        help="Use smoke for B3, timed_proxy for guarded B4 proxy, real_bridge only with an actual SystemC target",
    )
    parser.add_argument(
        "--real-systemc-target",
        action="store_true",
        default=env_flag("QEBS_REAL_SYSTEMC_TARGET", False),
        help="Permit real_bridge mode only when the external SystemC transactor is really bound",
    )
    parser.add_argument(
        "--disable-roi-stats",
        action="store_true",
        help="Disable device-local ROI counters; guest m5_reset_stats/m5_dump_stats remain the external ROI authority",
    )
    parser.add_argument("--roi-label", default="qebs_offload")
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=0,
        help="Bound SE proxy/smoke runs; 0 keeps gem5 default unbounded simulate()",
    )
    parser.add_argument(
        "--cpu-type",
        choices=["timing", "atomic"],
        default=os.environ.get("QEBS_GEM5_CPU_TYPE", "timing"),
        help=(
            "CPU model for SE smoke. timing preserves the original config; "
            "atomic is intended for bounded real-QE smoke completion without "
            "cycle/performance claims."
        ),
    )
    args = parser.parse_args()
    
    system = create_fpga_system(args)
    root = Root(full_system=False, system=system)
    m5.instantiate()
    
    print("Beginning simulation!")
    exit_event = m5.simulate(args.max_ticks) if args.max_ticks > 0 else m5.simulate()
    print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
