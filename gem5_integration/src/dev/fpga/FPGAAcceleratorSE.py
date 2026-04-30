from m5.params import *
from m5.proxy import *
from m5.objects.Device import BasicPioDevice

class FPGAAcceleratorSE(BasicPioDevice):
    type = 'FPGAAcceleratorSE'
    cxx_header = "dev/fpga/fpga_accelerator_se.hh"
    cxx_class = 'gem5::FPGAAcceleratorSE'

    strict_event_timing = Param.Bool(
        False,
        "Schedule completion through a candidate-profile event instead of immediate completion",
    )
    candidate_profile_ref = Param.String(
        "",
        "Runtime candidate_timing_profile_v0.json provenance for strict B4 runs",
    )
    candidate_event_delay_ticks = Param.UInt64(
        0,
        "Candidate-specific event delay consumed by strict B4 event scheduling",
    )
    candidate_dma_read_bytes = Param.UInt64(
        0,
        "Candidate profile DMA read-byte projection recorded in the device report",
    )
    candidate_dma_write_bytes = Param.UInt64(
        0,
        "Candidate profile DMA write-byte projection recorded in the device report",
    )
    strict_event_report_path = Param.String(
        "",
        "Machine-readable SimObject event/counter report path for strict B4 runs",
    )
