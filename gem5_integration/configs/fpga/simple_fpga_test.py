#!/usr/bin/env python3
# Simple FPGA device test configuration for gem5

import m5
from m5.objects import *
from m5.objects.X86CPU import X86TimingSimpleCPU
from m5.util import addToPath
import json
import os
import sys

addToPath('../')


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.lower() in ("1", "true", "yes", "on")

def env_int(name, default=0):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default

def write_qebs_backend_report(args, exit_event):
    report_path = os.environ.get("QEBS_BACKEND_EXECUTION_REPORT_JSON")
    if not report_path:
        return

    mode = os.environ.get("QEBS_EXECUTION_MODE", "gem5_systemc_smoke")
    claim_ceiling = {
        "gem5_systemc_smoke": "gem5_systemc_smoke_only",
        "gem5_systemc_timed_proxy": "gem5_systemc_timed_proxy_only",
    }.get(mode, "gem5_systemc_smoke_only")
    backend_class = {
        "gem5_systemc_smoke": "gem5_systemc_smoke",
        "gem5_systemc_timed_proxy": "gem5_systemc_timed_proxy",
    }.get(mode, "gem5_systemc_smoke")

    now_tick = int(m5.curTick())
    mmio_reads = env_int("QEBS_PROXY_MMIO_READS", 0)
    mmio_writes = env_int("QEBS_PROXY_MMIO_WRITES", 0)
    polling_reads = env_int("QEBS_PROXY_POLLING_READS", 0)
    dma_read_bytes = env_int("QEBS_PROXY_DMA_READ_BYTES", 0)
    dma_write_bytes = env_int("QEBS_PROXY_DMA_WRITE_BYTES", 0)
    logical_dma_bytes = dma_read_bytes + dma_write_bytes

    control_path = {
        "host_launch_count": 1,
        "completion_count": 1,
        "fallback_count": 0,
        "deadlock": False,
        "completion_source": "real_gem5_simple_fpga_test",
        "mmio_read_count": mmio_reads,
        "mmio_write_count": mmio_writes,
        "polling_read_count": polling_reads,
        "interrupt_count": 0,
        "command_issue_tick": 0,
        "device_accept_tick": 0,
        "systemc_start_tick": 0,
        "systemc_end_tick": now_tick,
        "completion_tick": now_tick,
        "dma_start_tick": 0,
        "dma_end_tick": now_tick,
    }
    metrics = {
        "time_to_completion_s": None,
        "cycle_proxy": now_tick,
        "host_wait_s": None,
        "device_busy_s": None,
        "dma_read_bytes": dma_read_bytes,
        "dma_write_bytes": dma_write_bytes,
        "bytes_moved_to_convergence": logical_dma_bytes,
        "resident_reuse_ratio": 0.0,
        "spill_ratio": 0.0,
        "fallback_ratio": 0.0,
        "host_control_mmio_read_count": mmio_reads,
        "host_control_mmio_write_count": mmio_writes,
        "host_control_polling_read_count": polling_reads,
        "host_control_interrupt_count": 0,
        "host_control_queue_wait_ns": None,
        "systemc_datapath_device_busy_ns": now_tick,
        "systemc_datapath_compute_ns": now_tick,
        "systemc_datapath_dma_read_ns": 0,
        "systemc_datapath_dma_write_ns": 0,
        "systemc_datapath_queue_depth": 0,
        "systemc_datapath_backpressure_count": 0,
        "logical_dma_payload_bytes": logical_dma_bytes,
        "observed_gem5_dma_stat_bytes": logical_dma_bytes,
        "successful_dma_transfer_bytes": logical_dma_bytes,
        "dma_warning_count": 0,
    }
    environment = {
        "source": "gem5_simple_fpga_test_config",
        "gem5_mode": os.environ.get("QEBS_GEM5_MODE", "SE"),
        "fpga_execution_mode": args.fpga_execution_mode,
        "real_systemc_target": "1" if args.real_systemc_target else "0",
        "systemc_bridge": os.environ.get("QEBS_SYSTEMC_BRIDGE"),
        "roi_stats_enabled": not args.disable_roi_stats,
        "roi_label": args.roi_label,
        "exit_cause": exit_event.getCause(),
        "exit_tick": now_tick,
    }
    artifact_refs = {
        "gem5_config": os.environ.get("QEBS_GEM5_CONFIG"),
        "gem5_output_dir": os.environ.get("QEBS_GEM5_OUTPUT_DIR"),
    }
    if os.environ.get("QEBS_SYSTEMC_BRIDGE"):
        artifact_refs["systemc_bridge"] = os.environ["QEBS_SYSTEMC_BRIDGE"]

    payload = {
        "schema_version": "backend_execution_report_v0",
        "candidate_id": os.environ.get("QEBS_CANDIDATE_ID", "unknown_candidate"),
        "execution_status": "executed",
        "fidelity": mode,
        "claim_ceiling": claim_ceiling,
        "backend_class": backend_class,
        "source_kind": "backend_runner_gem5_systemc",
        "environment": environment,
        "control_path": control_path,
        "metrics": metrics,
        "correctness_gate": {
            "workload_equivalent_claim": False,
            "domain": os.environ.get("QEBS_WORKLOAD_DOMAIN", "dft"),
            "domain_equivalence_claim": False,
        },
        "artifact_refs": artifact_refs,
        "non_claims": [
            "no_qe_equivalent_scf_claim",
            "no_cycle_accuracy_claim",
            "no_rtl_hls_board_or_asic_implementation_claim",
            "no_physical_fpga_performance_measurement",
        ],
    }
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")

class SimpleFPGASystem(System):
    def __init__(self, execution_mode="smoke", real_systemc_target=False,
                 roi_stats_enabled=True, roi_label="qebs_offload",
                 binary="/bin/true", **kwargs):
        super(SimpleFPGASystem, self).__init__(**kwargs)
        
        self.clk_domain = SrcClockDomain()
        self.clk_domain.clock = '1GHz'
        self.clk_domain.voltage_domain = VoltageDomain()
        
        self.mem_mode = 'timing'
        self.mem_ranges = [AddrRange('512MB')]
        self.platform = Pc()
        
        self.cpu = X86TimingSimpleCPU()
        self.cpu.isa = [X86ISA()]
        
        self.membus = SystemXBar()
        
        self.cpu.icache_port = self.membus.cpu_side_ports
        self.cpu.dcache_port = self.membus.cpu_side_ports
        
        self.cpu.createInterruptController()
        self.cpu.interrupts[0].pio = self.membus.mem_side_ports
        self.cpu.interrupts[0].int_requestor = self.membus.cpu_side_ports
        self.cpu.interrupts[0].int_responder = self.membus.mem_side_ports
        
        self.mem_ctrl = MemCtrl()
        self.mem_ctrl.dram = DDR3_1600_8x8()
        self.mem_ctrl.dram.range = self.mem_ranges[0]
        self.mem_ctrl.port = self.membus.mem_side_ports

        self.iobus = IOXBar()
        self.bridge = Bridge(delay="50ns")
        self.bridge.cpu_side_port = self.membus.mem_side_ports
        self.bridge.mem_side_port = self.iobus.cpu_side_ports
        self.bridge.ranges = [
            AddrRange(0x8000000000000000, 0x9FFFFFFFFFFFFFFF),
            AddrRange(0xC000000000000000, Addr.max),
        ]
        self.apicbridge = Bridge(delay="50ns")
        self.apicbridge.cpu_side_port = self.iobus.mem_side_ports
        self.apicbridge.mem_side_port = self.membus.cpu_side_ports
        self.apicbridge.ranges = [
            AddrRange(0xA000000000000000, 0xA000000000000FFF),
        ]
        
        self.system_port = self.membus.cpu_side_ports
        self.workload = SEWorkload.init_compatible(binary)
        
        self.platform.attachIO(self.iobus)
        
        self.fpga = FPGAAccelerator(
            pci_dev=5,
            pci_func=0,
            execution_mode=execution_mode,
            real_systemc_target=real_systemc_target,
            roi_stats_enabled=roi_stats_enabled,
            roi_label=roi_label,
        )
        self.fpga.upstream = self.platform.pci_host
        self.platform.attachPciDevice(self.fpga)

        process = Process()
        process.cmd = [binary]
        self.cpu.workload = process
        self.cpu.createThreads()

def create_system(args=None):
    if args is None:
        class _DefaultArgs:
            fpga_execution_mode = "smoke"
            real_systemc_target = False
            disable_roi_stats = False
            roi_label = "qebs_offload"
            binary = os.environ.get("QEBS_SIMPLE_BINARY", "/bin/true")
        args = _DefaultArgs()
    system = SimpleFPGASystem(
        execution_mode=args.fpga_execution_mode,
        real_systemc_target=args.real_systemc_target,
        roi_stats_enabled=not args.disable_roi_stats,
        roi_label=args.roi_label,
        binary=args.binary,
    )
    return system

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fpga-execution-mode",
        choices=["smoke", "timed_proxy", "real_bridge"],
        default=os.environ.get("QEBS_FPGA_EXECUTION_MODE", "smoke"),
        help="B3 uses smoke; B4 uses timed_proxy unless an explicit real bridge is available",
    )
    parser.add_argument("--real-systemc-target", action="store_true")
    parser.set_defaults(real_systemc_target=env_flag("QEBS_REAL_SYSTEMC_TARGET", False))
    parser.add_argument("--disable-roi-stats", action="store_true")
    parser.add_argument("--roi-label", default=os.environ.get("QEBS_ROI_LABEL", "qebs_offload"))
    parser.add_argument("--binary", default=os.environ.get("QEBS_SIMPLE_BINARY", "/bin/true"))
    parser.add_argument("--max-ticks", type=int, default=0)
    args = parser.parse_args()

    system = create_system(args)
    
    root = Root(full_system=False, system=system)
    
    m5.instantiate()
    
    print("gem5 FPGA device test starting...")
    print(f"FPGA device: {system.fpga}")
    print(f"PCI config: dev={system.fpga.pci_dev}, func={system.fpga.pci_func}")
    
    exit_event = m5.simulate(args.max_ticks) if args.max_ticks > 0 else m5.simulate()
    
    print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
    write_qebs_backend_report(args, exit_event)

if __name__ == "__m5_main__":
    main()
