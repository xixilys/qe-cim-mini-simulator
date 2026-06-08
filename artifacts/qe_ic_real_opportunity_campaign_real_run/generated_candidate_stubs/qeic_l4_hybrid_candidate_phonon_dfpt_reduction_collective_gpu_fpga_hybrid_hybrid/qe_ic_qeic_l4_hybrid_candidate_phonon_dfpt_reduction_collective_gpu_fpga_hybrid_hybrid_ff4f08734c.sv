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
