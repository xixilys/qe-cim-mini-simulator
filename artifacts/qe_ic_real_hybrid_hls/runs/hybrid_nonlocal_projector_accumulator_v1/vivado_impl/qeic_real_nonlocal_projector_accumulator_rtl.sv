module qeic_real_nonlocal_projector_accumulator_rtl #(
    parameter integer SAMPLES = 256,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 56
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire sample_first,
    input  wire sample_last,
    input  wire signed [WIDTH-1:0] beta_re,
    input  wire signed [WIDTH-1:0] beta_im,
    input  wire signed [WIDTH-1:0] psi_re,
    input  wire signed [WIDTH-1:0] psi_im,
    output reg  signed [ACC_WIDTH-1:0] proj_re,
    output reg  signed [ACC_WIDTH-1:0] proj_im,
    output reg  valid,
    output reg  done
);
    reg active;
    integer sample_count;
    reg signed [ACC_WIDTH-1:0] acc_re;
    reg signed [ACC_WIDTH-1:0] acc_im;
    wire signed [(2*WIDTH)-1:0] beta_psi_rr = beta_re * psi_re;
    wire signed [(2*WIDTH)-1:0] beta_psi_ii = beta_im * psi_im;
    wire signed [(2*WIDTH)-1:0] beta_psi_ri = beta_re * psi_im;
    wire signed [(2*WIDTH)-1:0] beta_psi_ir = beta_im * psi_re;
    wire signed [ACC_WIDTH-1:0] prod_re =
        {{(ACC_WIDTH-(2*WIDTH)){beta_psi_rr[(2*WIDTH)-1]}}, beta_psi_rr}
        + {{(ACC_WIDTH-(2*WIDTH)){beta_psi_ii[(2*WIDTH)-1]}}, beta_psi_ii};
    wire signed [ACC_WIDTH-1:0] prod_im =
        {{(ACC_WIDTH-(2*WIDTH)){beta_psi_ri[(2*WIDTH)-1]}}, beta_psi_ri}
        - {{(ACC_WIDTH-(2*WIDTH)){beta_psi_ir[(2*WIDTH)-1]}}, beta_psi_ir};
    wire signed [ACC_WIDTH-1:0] base_re = sample_first ? {ACC_WIDTH{1'b0}} : acc_re;
    wire signed [ACC_WIDTH-1:0] base_im = sample_first ? {ACC_WIDTH{1'b0}} : acc_im;
    wire signed [ACC_WIDTH-1:0] next_re = base_re + prod_re;
    wire signed [ACC_WIDTH-1:0] next_im = base_im + prod_im;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            sample_count <= 0;
            acc_re <= 0;
            acc_im <= 0;
            proj_re <= 0;
            proj_im <= 0;
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            valid <= 1'b0;
            if (start) begin
                active <= 1'b1;
                sample_count <= 0;
                acc_re <= 0;
                acc_im <= 0;
                proj_re <= 0;
                proj_im <= 0;
                done <= 1'b0;
            end else if (active && sample_valid) begin
                if (sample_last) begin
                    proj_re <= next_re;
                    proj_im <= next_im;
                    valid <= 1'b1;
                    acc_re <= 0;
                    acc_im <= 0;
                end else begin
                    acc_re <= next_re;
                    acc_im <= next_im;
                end
                if (sample_count == SAMPLES - 1) begin
                    active <= 1'b0;
                    done <= 1'b1;
                end
                sample_count <= sample_count + 1;
            end
        end
    end
endmodule
