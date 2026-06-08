// Generated non-claimable RTL stub for qeic_l4_fpga_candidate_ground_state_band_structure_fft_transpose_fpga_only_fpga_fft_transpose_engine_9bfbea2b1f
module qe_ic_qeic_l4_fpga_candidate_ground_state_band_structure_fft_transpose_fpga_only_fpga__6cc5e75e1c (
    input wire clk,
    input wire rst_n,
    input wire valid_in,
    input wire [63:0] in_word,
    output reg valid_out,
    output reg [63:0] out_word
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_out <= 1'b0;
            out_word <= 64'd0;
        end else begin
            valid_out <= valid_in;
            out_word <= in_word ^ 64'h4f2269054f226905;
        end
    end
endmodule

// Generated non-claimable RTL stub for qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_reduction_sidecar_423b828955
module qe_ic_qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_ff4f08734c (
    input wire clk,
    input wire rst_n,
    input wire valid_in,
    input wire [63:0] in_word,
    output reg valid_out,
    output reg [63:0] out_word
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_out <= 1'b0;
            out_word <= 64'd0;
        end else begin
            valid_out <= valid_in;
            out_word <= in_word ^ 64'hf47f0f84f47f0f84;
        end
    end
endmodule

// Generated non-claimable RTL stub for qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_dma_overlap_sidecar_9a9fa929fc
module qe_ic_qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_f3cf4b1b60 (
    input wire clk,
    input wire rst_n,
    input wire valid_in,
    input wire [63:0] in_word,
    output reg valid_out,
    output reg [63:0] out_word
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_out <= 1'b0;
            out_word <= 64'd0;
        end else begin
            valid_out <= valid_in;
            out_word <= in_word ^ 64'h538def24538def24;
        end
    end
endmodule

module qe_ic_generated_stub_top (
    input wire clk,
    input wire rst_n,
    input wire top_valid_in,
    input wire [63:0] top_in_word,
    output wire [63:0] top_out_word
);
    wire [63:0] stage_0_word;
    wire stage_0_valid;
    wire [63:0] stage_1_word;
    wire stage_1_valid;
    wire [63:0] stage_2_word;
    wire stage_2_valid;
    qe_ic_qeic_l4_fpga_candidate_ground_state_band_structure_fft_transpose_fpga_only_fpga__6cc5e75e1c u_0 (.clk(clk), .rst_n(rst_n), .valid_in(top_valid_in), .in_word(top_in_word), .valid_out(stage_0_valid), .out_word(stage_0_word));
    qe_ic_qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_ff4f08734c u_1 (.clk(clk), .rst_n(rst_n), .valid_in(top_valid_in), .in_word(stage_0_word), .valid_out(stage_1_valid), .out_word(stage_1_word));
    qe_ic_qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_f3cf4b1b60 u_2 (.clk(clk), .rst_n(rst_n), .valid_in(top_valid_in), .in_word(stage_1_word), .valid_out(stage_2_valid), .out_word(stage_2_word));
    assign top_out_word = stage_2_word;
endmodule
