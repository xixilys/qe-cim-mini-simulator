create_clock -period 20.000 -name clk [get_ports clk]
set_false_path -from [get_ports reset_n]
