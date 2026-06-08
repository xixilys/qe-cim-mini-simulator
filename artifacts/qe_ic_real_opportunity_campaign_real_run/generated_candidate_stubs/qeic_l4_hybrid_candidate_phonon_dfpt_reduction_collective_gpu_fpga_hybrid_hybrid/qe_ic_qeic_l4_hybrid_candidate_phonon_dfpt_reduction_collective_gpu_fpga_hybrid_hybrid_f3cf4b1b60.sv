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
