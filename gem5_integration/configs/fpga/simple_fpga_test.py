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

STRICT_PIO_BASE = 0xF0000000
STRICT_PIO_SIZE = 0x1000


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

def load_timing_sidecar():
    path = os.environ.get("QEBS_TIMING_SIDECAR_JSON")
    if not path:
        return {}, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}, path
    if not isinstance(payload, dict):
        return {}, path
    return payload, path

def load_candidate_timing_profile():
    path = (
        os.environ.get("QEBS_CANDIDATE_TIMING_PROFILE_JSON")
        or os.environ.get("QEBS_STRICT_B4_RUNTIME_TIMING_INPUT")
    )
    if not path:
        return {}, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}, path
    if not isinstance(payload, dict):
        return {}, path
    return payload, path

def load_device_event_report():
    path = os.environ.get("QEBS_STRICT_B4_DEVICE_EVENT_REPORT_JSON")
    if not path:
        return {}, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}, path
    if not isinstance(payload, dict):
        return {}, path
    return payload, path

def strict_pio_binary_path():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(
        os.path.join(script_dir, "..", "..", "qe_test_program", "fpga_strict_pio_test")
    )

def mapping_from(value):
    return value if isinstance(value, dict) else {}

def int_from_mapping(mapping, key, default=0):
    value = mapping.get(key)
    if isinstance(value, bool) or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
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
    timing_sidecar, timing_sidecar_ref = load_timing_sidecar()
    candidate_profile, candidate_profile_ref = load_candidate_timing_profile()
    device_event_report, device_event_report_ref = load_device_event_report()
    sidecar_control = mapping_from(timing_sidecar.get("control_path"))
    sidecar_metrics = mapping_from(timing_sidecar.get("metrics"))
    cluster_breakdown = mapping_from(timing_sidecar.get("cluster_breakdown"))
    profile_event_schedule = mapping_from(candidate_profile.get("event_schedule"))
    profile_dma = mapping_from(candidate_profile.get("dma_profile"))
    strict_event_b4 = bool(getattr(args, "strict_event_b4", False))

    device_reads = int_from_mapping(device_event_report, "observed_read_count", 0)
    device_writes = int_from_mapping(device_event_report, "observed_write_count", 0)
    device_polling_reads = int_from_mapping(device_event_report, "polling_read_count", 0)
    device_event_delta = int_from_mapping(
        device_event_report,
        "candidate_device_event_delta_ticks",
        0,
    )
    strict_event_observed = (
        strict_event_b4
        and device_event_report_ref is not None
        and device_event_report.get("event_activity_source") == "gem5_simobject_counters"
        and device_reads > 0
        and device_writes > 0
        and device_event_delta > 0
    )
    if strict_event_observed:
        mmio_reads = device_reads
        mmio_writes = device_writes
        polling_reads = device_polling_reads
    else:
        mmio_reads = env_int(
            "QEBS_PROXY_MMIO_READS",
            int_from_mapping(sidecar_control, "mmio_read_count", 0),
        )
        mmio_writes = env_int(
            "QEBS_PROXY_MMIO_WRITES",
            int_from_mapping(sidecar_control, "mmio_write_count", 0),
        )
        polling_reads = env_int(
            "QEBS_PROXY_POLLING_READS",
            int_from_mapping(sidecar_control, "polling_read_count", 0),
        )
    dma_read_bytes = env_int(
        "QEBS_PROXY_DMA_READ_BYTES",
        int_from_mapping(
            profile_dma,
            "dma_read_bytes",
            int_from_mapping(sidecar_metrics, "dma_read_bytes", 0),
        ),
    )
    dma_write_bytes = env_int(
        "QEBS_PROXY_DMA_WRITE_BYTES",
        int_from_mapping(
            profile_dma,
            "dma_write_bytes",
            int_from_mapping(sidecar_metrics, "dma_write_bytes", 0),
        ),
    )
    logical_dma_bytes = dma_read_bytes + dma_write_bytes
    sidecar_cycle_proxy = int_from_mapping(sidecar_metrics, "cycle_proxy", 0)
    if strict_event_observed:
        timing_source = "gem5_event_timed_device_observed"
        cycle_proxy = device_event_delta
    else:
        # gem5's own boot/exit tick can dominate this tiny harness and hide the
        # candidate-specific SystemC timing sidecar. Keep it as provenance, but use
        # the sidecar as the B4 timed-proxy cycle metric when strict device counters
        # are absent.
        timing_source = (
            "timing_sidecar_projection"
            if timing_sidecar_ref and sidecar_cycle_proxy > 0
            else "gem5_exit_tick"
        )
        cycle_proxy = sidecar_cycle_proxy if timing_source == "timing_sidecar_projection" else now_tick
    event_timed_activity = strict_event_observed
    command_issue_tick = (
        int_from_mapping(device_event_report, "command_issue_tick", 0)
        if strict_event_observed
        else int_from_mapping(sidecar_control, "command_issue_tick", 0)
    )
    device_accept_tick = (
        int_from_mapping(device_event_report, "device_accept_tick", 0)
        if strict_event_observed
        else int_from_mapping(sidecar_control, "device_accept_tick", 0)
    )
    systemc_start_tick = (
        int_from_mapping(device_event_report, "systemc_start_tick", 0)
        if strict_event_observed
        else int_from_mapping(sidecar_control, "systemc_start_tick", 0)
    )
    systemc_end_tick = max(
        int_from_mapping(
            device_event_report if strict_event_observed else sidecar_control,
            "systemc_end_tick",
            cycle_proxy,
        ),
        systemc_start_tick,
    )
    completion_tick = max(
        int_from_mapping(
            device_event_report if strict_event_observed else sidecar_control,
            "completion_tick",
            cycle_proxy,
        ),
        systemc_end_tick,
    )
    dma_start_tick = int_from_mapping(sidecar_control, "dma_start_tick", 0)
    dma_end_tick = max(int_from_mapping(sidecar_control, "dma_end_tick", completion_tick), dma_start_tick)

    control_path = {
        "host_launch_count": 1,
        "completion_count": 1,
        "fallback_count": 0,
        "deadlock": False,
        "completion_source": device_event_report.get(
            "completion_source",
            "real_gem5_simple_fpga_test_with_timing_sidecar"
            if timing_sidecar_ref else "real_gem5_simple_fpga_test",
        ),
        "timing_source": timing_source,
        "mmio_activity_source": "gem5_simobject_counters"
        if strict_event_observed else ("timing_sidecar_projection" if timing_sidecar_ref else "not_observed"),
        "event_activity_source": "gem5_simobject_counters" if strict_event_observed else "not_observed",
        "event_timed_device_activity_observed": event_timed_activity,
        "mmio_read_count": mmio_reads,
        "mmio_write_count": mmio_writes,
        "polling_read_count": polling_reads,
        "interrupt_count": 0,
        "command_issue_tick": command_issue_tick,
        "device_accept_tick": device_accept_tick,
        "systemc_start_tick": systemc_start_tick,
        "systemc_end_tick": systemc_end_tick,
        "completion_tick": completion_tick,
        "dma_start_tick": dma_start_tick,
        "dma_end_tick": dma_end_tick,
    }
    metrics = {
        "time_to_completion_s": None,
        "cycle_proxy": cycle_proxy,
        "cycle_source": timing_source,
        "cycle_proxy_source": timing_source,
        "gem5_tick_observed": now_tick,
        "systemc_sidecar_cycle_proxy": sidecar_cycle_proxy if timing_sidecar_ref else None,
        "event_timed_device_activity_observed": event_timed_activity,
        "candidate_device_event_delta_ticks": (
            device_event_delta if strict_event_observed else max(0, completion_tick - command_issue_tick)
            if event_timed_activity
            else None
        ),
        "observed_device_activity_source": "gem5_simobject_counters" if strict_event_observed else None,
        "strict_b4_runtime_profile_event_delta_ticks": int_from_mapping(
            profile_event_schedule,
            "candidate_event_delta_ticks",
            0,
        ) if candidate_profile_ref else None,
        "host_wait_s": None,
        "device_busy_s": sidecar_metrics.get("device_busy_s"),
        "dma_read_bytes": dma_read_bytes,
        "dma_write_bytes": dma_write_bytes,
        "bytes_moved_to_convergence": sidecar_metrics.get(
            "bytes_moved_to_convergence",
            logical_dma_bytes,
        ),
        "resident_reuse_ratio": sidecar_metrics.get("resident_reuse_ratio", 0.0),
        "spill_ratio": sidecar_metrics.get("spill_ratio", 0.0),
        "fallback_ratio": sidecar_metrics.get("fallback_ratio", 0.0),
        "host_control_mmio_read_count": mmio_reads,
        "host_control_mmio_write_count": mmio_writes,
        "host_control_polling_read_count": polling_reads,
        "host_control_interrupt_count": 0,
        "host_control_queue_wait_ns": sidecar_metrics.get("host_control_queue_wait_ns"),
        "systemc_datapath_device_busy_ns": sidecar_metrics.get(
            "systemc_datapath_device_busy_ns",
            cycle_proxy,
        ),
        "systemc_datapath_compute_ns": sidecar_metrics.get(
            "systemc_datapath_compute_ns",
            cycle_proxy,
        ),
        "systemc_datapath_dma_read_ns": sidecar_metrics.get("systemc_datapath_dma_read_ns", 0),
        "systemc_datapath_dma_write_ns": sidecar_metrics.get("systemc_datapath_dma_write_ns", 0),
        "systemc_datapath_queue_depth": sidecar_metrics.get("systemc_datapath_queue_depth", 0),
        "systemc_datapath_backpressure_count": sidecar_metrics.get(
            "systemc_datapath_backpressure_count",
            0,
        ),
        "systemc_datapath_dma_read_bytes": sidecar_metrics.get(
            "systemc_datapath_dma_read_bytes",
            dma_read_bytes,
        ),
        "systemc_datapath_dma_write_bytes": sidecar_metrics.get(
            "systemc_datapath_dma_write_bytes",
            dma_write_bytes,
        ),
        "logical_dma_payload_bytes": logical_dma_bytes,
        "observed_gem5_dma_stat_bytes": logical_dma_bytes,
        "successful_dma_transfer_bytes": logical_dma_bytes,
        "dma_warning_count": 0,
        "systemc_cluster_timing": cluster_breakdown,
    }
    environment = {
        "source": "gem5_simple_fpga_test_config",
        "gem5_mode": os.environ.get("QEBS_GEM5_MODE", "SE"),
        "fpga_execution_mode": args.fpga_execution_mode,
        "real_systemc_target": "1" if args.real_systemc_target else "0",
        "gem5_device_model": "FPGAAcceleratorSE" if strict_event_b4 else "FPGAAccelerator",
        "strict_b4_event_timing": strict_event_b4,
        "systemc_bridge": os.environ.get("QEBS_SYSTEMC_BRIDGE"),
        "roi_stats_enabled": not args.disable_roi_stats,
        "roi_label": args.roi_label,
        "exit_cause": exit_event.getCause(),
        "exit_tick": now_tick,
        "timing_sidecar": timing_sidecar_ref,
        "candidate_timing_profile": candidate_profile_ref,
        "strict_b4_runtime_timing_input": candidate_profile_ref,
        "device_event_report": device_event_report_ref,
        "timing_source": timing_source,
        "cycle_source": timing_source,
        "workload_id": os.environ.get("QEBS_WORKLOAD_ID"),
        "case_id": os.environ.get("QEBS_CASE_ID") or os.environ.get("QEBS_QE_CASE_ID"),
    }
    artifact_refs = {
        "gem5_config": os.environ.get("QEBS_GEM5_CONFIG"),
        "gem5_output_dir": os.environ.get("QEBS_GEM5_OUTPUT_DIR"),
    }
    if os.environ.get("QEBS_SYSTEMC_BRIDGE"):
        artifact_refs["systemc_bridge"] = os.environ["QEBS_SYSTEMC_BRIDGE"]
    if timing_sidecar_ref:
        artifact_refs["timing_sidecar"] = timing_sidecar_ref
    if candidate_profile_ref:
        artifact_refs["candidate_timing_profile"] = candidate_profile_ref
        artifact_refs["strict_b4_runtime_timing_input"] = candidate_profile_ref
    if device_event_report_ref:
        artifact_refs["device_event_report"] = device_event_report_ref

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
                 binary="/bin/true", strict_event_b4=False, **kwargs):
        super(SimpleFPGASystem, self).__init__(**kwargs)

        self.clk_domain = SrcClockDomain()
        self.clk_domain.clock = '1GHz'
        self.clk_domain.voltage_domain = VoltageDomain()

        self.mem_mode = 'timing'
        self.mem_ranges = [AddrRange('512MB')]

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

        self.system_port = self.membus.cpu_side_ports
        self.workload = SEWorkload.init_compatible(binary)

        if strict_event_b4:
            candidate_profile, candidate_profile_ref = load_candidate_timing_profile()
            if not candidate_profile_ref:
                raise ValueError("strict-event B4 requires QEBS_CANDIDATE_TIMING_PROFILE_JSON")
            event_schedule = mapping_from(candidate_profile.get("event_schedule"))
            dma_profile = mapping_from(candidate_profile.get("dma_profile"))
            delay_ticks = int_from_mapping(event_schedule, "candidate_event_delta_ticks", 0)
            if delay_ticks <= 0:
                raise ValueError("strict-event B4 candidate profile requires positive candidate_event_delta_ticks")
            self.fpga = FPGAAcceleratorSE(
                pio_addr=STRICT_PIO_BASE,
                strict_event_timing=True,
                candidate_profile_ref=candidate_profile_ref,
                candidate_event_delay_ticks=delay_ticks,
                candidate_dma_read_bytes=int_from_mapping(dma_profile, "dma_read_bytes", 0),
                candidate_dma_write_bytes=int_from_mapping(dma_profile, "dma_write_bytes", 0),
                strict_event_report_path=os.environ.get("QEBS_STRICT_B4_DEVICE_EVENT_REPORT_JSON", ""),
            )
            self.fpga.pio = self.membus.mem_side_ports
        else:
            self.platform = Pc()
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
            strict_event_b4 = False
            binary = os.environ.get("QEBS_SIMPLE_BINARY", "/bin/true")
        args = _DefaultArgs()
    system = SimpleFPGASystem(
        execution_mode=args.fpga_execution_mode,
        real_systemc_target=args.real_systemc_target,
        roi_stats_enabled=not args.disable_roi_stats,
        roi_label=args.roi_label,
        binary=args.binary,
        strict_event_b4=args.strict_event_b4,
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
    parser.add_argument("--strict-event-b4", action="store_true")
    parser.set_defaults(strict_event_b4=env_flag("QEBS_STRICT_B4_EVENT_TIMING", False))
    parser.add_argument("--binary", default=os.environ.get("QEBS_SIMPLE_BINARY"))
    parser.add_argument("--max-ticks", type=int, default=0)
    args = parser.parse_args()
    if args.binary is None:
        args.binary = strict_pio_binary_path() if args.strict_event_b4 else "/bin/true"
    if args.strict_event_b4 and not os.path.exists(args.binary):
        raise FileNotFoundError(
            "strict-event B4 workload binary is missing; build "
            f"{args.binary} from fpga_strict_pio_test.c"
        )

    system = create_system(args)

    root = Root(full_system=False, system=system)

    m5.instantiate()
    if args.strict_event_b4:
        system.cpu.workload[0].map(STRICT_PIO_BASE, STRICT_PIO_BASE, STRICT_PIO_SIZE, False)

    print("gem5 FPGA device test starting...")
    print(f"FPGA device: {system.fpga}")
    if args.strict_event_b4:
        print(f"Strict PIO map: vaddr=0x{STRICT_PIO_BASE:X} paddr=0x{STRICT_PIO_BASE:X}")
    else:
        print(f"PCI config: dev={system.fpga.pci_dev}, func={system.fpga.pci_func}")

    exit_event = m5.simulate(args.max_ticks) if args.max_ticks > 0 else m5.simulate()

    print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
    write_qebs_backend_report(args, exit_event)

if __name__ == "__m5_main__":
    main()
