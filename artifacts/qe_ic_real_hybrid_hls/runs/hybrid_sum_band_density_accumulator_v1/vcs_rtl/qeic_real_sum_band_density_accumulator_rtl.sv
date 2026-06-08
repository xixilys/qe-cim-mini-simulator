module qeic_real_sum_band_density_accumulator_rtl #(
    parameter integer SAMPLES = 128,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 48
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire band_first,
    input  wire band_last,
    input  wire signed [WIDTH-1:0] psi_re,
    input  wire signed [WIDTH-1:0] psi_im,
    input  wire signed [WIDTH-1:0] weight,
    output reg  signed [ACC_WIDTH-1:0] rho_out,
    output reg  valid,
    output reg  done
);
    reg active;
    integer sample_count;
    reg signed [ACC_WIDTH-1:0] rho_acc;
    wire signed [(2*WIDTH)-1:0] re_sq = psi_re * psi_re;
    wire signed [(2*WIDTH)-1:0] im_sq = psi_im * psi_im;
    wire signed [ACC_WIDTH-1:0] abs_sq = {{(ACC_WIDTH-(2*WIDTH)){1'b0}}, re_sq + im_sq};
    wire signed [(ACC_WIDTH+WIDTH)-1:0] weighted_wide = abs_sq * weight;
    wire signed [ACC_WIDTH-1:0] contribution = weighted_wide[ACC_WIDTH+WIDTH-1:WIDTH];
    wire signed [ACC_WIDTH-1:0] rho_acc_next = band_first ? contribution : (rho_acc + contribution);

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            sample_count <= 0;
            rho_acc <= 0;
            rho_out <= 0;
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            valid <= 1'b0;
            if (start) begin
                active <= 1'b1;
                sample_count <= 0;
                rho_acc <= 0;
                rho_out <= 0;
                done <= 1'b0;
            end else if (active && sample_valid) begin
                rho_acc <= rho_acc_next;
                rho_out <= rho_acc_next;
                valid <= band_last;
                if (sample_count == SAMPLES - 1) begin
                    active <= 1'b0;
                    done <= 1'b1;
                end
                sample_count <= sample_count + 1;
            end
        end
    end
endmodule
