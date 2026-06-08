module qeic_real_tiled_complex_axpy_rtl #(
    parameter integer N = 64,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 48,
    parameter signed [WIDTH-1:0] ALPHA_RE = 18'sd192,
    parameter signed [WIDTH-1:0] ALPHA_IM = -18'sd32
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire signed [WIDTH-1:0] x_re,
    input  wire signed [WIDTH-1:0] x_im,
    input  wire signed [WIDTH-1:0] y_re,
    input  wire signed [WIDTH-1:0] y_im,
    output reg  signed [ACC_WIDTH-1:0] out_re,
    output reg  signed [ACC_WIDTH-1:0] out_im,
    output reg  valid,
    output reg  done
);
    reg active;
    integer sample_count;
    wire signed [WIDTH-1:0] alpha_re = ALPHA_RE;
    wire signed [WIDTH-1:0] alpha_im = ALPHA_IM;
    wire signed [(2*WIDTH)-1:0] ar_xr = alpha_re * x_re;
    wire signed [(2*WIDTH)-1:0] ai_xi = alpha_im * x_im;
    wire signed [(2*WIDTH)-1:0] ar_xi = alpha_re * x_im;
    wire signed [(2*WIDTH)-1:0] ai_xr = alpha_im * x_re;
    wire signed [ACC_WIDTH-1:0] y_re_ext = {{(ACC_WIDTH-WIDTH){y_re[WIDTH-1]}}, y_re} <<< 8;
    wire signed [ACC_WIDTH-1:0] y_im_ext = {{(ACC_WIDTH-WIDTH){y_im[WIDTH-1]}}, y_im} <<< 8;
    wire signed [ACC_WIDTH-1:0] alpha_x_re = ar_xr - ai_xi;
    wire signed [ACC_WIDTH-1:0] alpha_x_im = ar_xi + ai_xr;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            sample_count <= 0;
            out_re <= 0;
            out_im <= 0;
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            valid <= 1'b0;
            if (start) begin
                active <= 1'b1;
                sample_count <= 0;
                out_re <= 0;
                out_im <= 0;
                done <= 1'b0;
            end else if (active && sample_valid) begin
                out_re <= y_re_ext + alpha_x_re;
                out_im <= y_im_ext + alpha_x_im;
                valid <= 1'b1;
                if (sample_count == N - 1) begin
                    active <= 1'b0;
                    done <= 1'b1;
                end
                sample_count <= sample_count + 1;
            end
        end
    end
endmodule
