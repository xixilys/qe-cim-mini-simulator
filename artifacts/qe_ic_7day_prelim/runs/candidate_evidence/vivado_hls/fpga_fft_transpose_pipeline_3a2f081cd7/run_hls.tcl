open_project -reset qe_ic_hls_probe
set_top hls_fpga_fft_transpose_pipeline
add_files kernel.cpp
add_files -tb tb.cpp
open_solution -reset sol1
set_part {xc7z020clg400-1}
create_clock -period 10 -name default
csim_design
csynth_design
exit
