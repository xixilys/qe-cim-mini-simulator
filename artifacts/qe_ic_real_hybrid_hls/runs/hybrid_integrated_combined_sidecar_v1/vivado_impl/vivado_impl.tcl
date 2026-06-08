set_msg_config -id {Common 17-55} -new_severity {INFO}
read_verilog -sv qeic_real_integrated_combined_sidecar_rtl.sv
read_verilog -sv qeic_real_integrated_combined_sidecar_impl_top.sv
read_xdc vivado_impl.xdc
synth_design -top qeic_real_integrated_combined_sidecar_impl_top -part xc7z020clg400-1
opt_design
place_design
route_design
report_utilization -file vivado_utilization.rpt
report_timing_summary -file vivado_timing_summary.rpt
write_checkpoint -force post_route.dcp
