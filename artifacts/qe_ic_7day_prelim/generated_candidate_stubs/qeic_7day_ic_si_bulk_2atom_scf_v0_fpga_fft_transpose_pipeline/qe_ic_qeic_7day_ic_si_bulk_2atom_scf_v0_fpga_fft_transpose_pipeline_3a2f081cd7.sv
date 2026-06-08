// Generated non-claimable RTL stub for qeic_7day_ic_si_bulk_2atom_scf_v0_fpga_fft_transpose_pipeline
module qe_ic_qeic_7day_ic_si_bulk_2atom_scf_v0_fpga_fft_transpose_pipeline_3a2f081cd7 (
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
