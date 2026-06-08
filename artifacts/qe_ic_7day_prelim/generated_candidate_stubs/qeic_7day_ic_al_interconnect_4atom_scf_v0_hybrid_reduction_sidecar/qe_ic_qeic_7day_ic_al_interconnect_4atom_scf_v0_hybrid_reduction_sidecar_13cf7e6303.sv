// Generated non-claimable RTL stub for qeic_7day_ic_al_interconnect_4atom_scf_v0_hybrid_reduction_sidecar
module qe_ic_qeic_7day_ic_al_interconnect_4atom_scf_v0_hybrid_reduction_sidecar_13cf7e6303 (
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
