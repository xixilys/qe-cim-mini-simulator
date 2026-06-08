open_project -reset real_hybrid_hls
set_top qeic_real_sum_band_density_accumulator
add_files kernel.cpp
add_files -tb tb.cpp
open_solution -reset sol1
set_part {xc7z020clg400-1}
create_clock -period 10 -name default
csim_design
csynth_design
cosim_design -trace_level none
exit
