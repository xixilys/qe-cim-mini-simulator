module qeic_real_integrated_combined_sidecar_rtl #(
    parameter integer TOTAL_SAMPLES = 288,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 48,
    parameter signed [WIDTH-1:0] ALPHA_RE = 18'sd192,
    parameter signed [WIDTH-1:0] ALPHA_IM = -18'sd32
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire [1:0] mode,
    input  wire band_first,
    input  wire band_last,
    input  wire signed [WIDTH-1:0] a_re,
    input  wire signed [WIDTH-1:0] a_im,
    input  wire signed [WIDTH-1:0] b_re,
    input  wire signed [WIDTH-1:0] b_im,
    input  wire signed [WIDTH-1:0] c_re,
    input  wire signed [WIDTH-1:0] c_im,
    input  wire signed [WIDTH-1:0] weight,
    input  wire signed [WIDTH-1:0] y_re,
    input  wire signed [WIDTH-1:0] y_im,
    output reg  signed [ACC_WIDTH-1:0] out_re,
    output reg  signed [ACC_WIDTH-1:0] out_im,
    output reg  signed [ACC_WIDTH-1:0] rho_out,
    output reg  valid,
    output reg  done
);
    localparam [1:0] MODE_HPSI = 2'd0;
    localparam [1:0] MODE_SUM_BAND = 2'd1;
    localparam [1:0] MODE_AXPY = 2'd2;

    reg active;
    integer sample_count;
    reg signed [ACC_WIDTH-1:0] rho_acc;

    wire signed [ACC_WIDTH-1:0] lap_re = {{(ACC_WIDTH-WIDTH){a_re[WIDTH-1]}}, a_re}
        - ({{(ACC_WIDTH-WIDTH){b_re[WIDTH-1]}}, b_re} <<< 1)
        + {{(ACC_WIDTH-WIDTH){c_re[WIDTH-1]}}, c_re};
    wire signed [ACC_WIDTH-1:0] lap_im = {{(ACC_WIDTH-WIDTH){a_im[WIDTH-1]}}, a_im}
        - ({{(ACC_WIDTH-WIDTH){b_im[WIDTH-1]}}, b_im} <<< 1)
        + {{(ACC_WIDTH-WIDTH){c_im[WIDTH-1]}}, c_im};
    wire signed [(2*WIDTH)-1:0] vloc_re = weight * b_re;
    wire signed [(2*WIDTH)-1:0] vloc_im = weight * b_im;
    wire signed [ACC_WIDTH-1:0] hpsi_re = -(lap_re >>> 1) + (vloc_re >>> 8);
    wire signed [ACC_WIDTH-1:0] hpsi_im = -(lap_im >>> 1) + (vloc_im >>> 8);

    wire signed [(2*WIDTH)-1:0] sb_re_sq = b_re * b_re;
    wire signed [(2*WIDTH)-1:0] sb_im_sq = b_im * b_im;
    wire signed [ACC_WIDTH-1:0] sb_abs_sq = {{(ACC_WIDTH-(2*WIDTH)){1'b0}}, sb_re_sq + sb_im_sq};
    wire signed [(ACC_WIDTH+WIDTH)-1:0] sb_weighted = sb_abs_sq * weight;
    wire signed [ACC_WIDTH-1:0] sb_contribution = sb_weighted[ACC_WIDTH+WIDTH-1:WIDTH];
    wire signed [ACC_WIDTH-1:0] rho_acc_next = band_first ? sb_contribution : (rho_acc + sb_contribution);

    wire signed [(2*WIDTH)-1:0] ar_xr = ALPHA_RE * a_re;
    wire signed [(2*WIDTH)-1:0] ai_xi = ALPHA_IM * a_im;
    wire signed [(2*WIDTH)-1:0] ar_xi = ALPHA_RE * a_im;
    wire signed [(2*WIDTH)-1:0] ai_xr = ALPHA_IM * a_re;
    wire signed [ACC_WIDTH-1:0] y_re_ext = {{(ACC_WIDTH-WIDTH){y_re[WIDTH-1]}}, y_re} <<< 8;
    wire signed [ACC_WIDTH-1:0] y_im_ext = {{(ACC_WIDTH-WIDTH){y_im[WIDTH-1]}}, y_im} <<< 8;
    wire signed [ACC_WIDTH-1:0] alpha_x_re = ar_xr - ai_xi;
    wire signed [ACC_WIDTH-1:0] alpha_x_im = ar_xi + ai_xr;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            sample_count <= 0;
            rho_acc <= 0;
            out_re <= 0;
            out_im <= 0;
            rho_out <= 0;
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            valid <= 1'b0;
            if (start) begin
                active <= 1'b1;
                sample_count <= 0;
                rho_acc <= 0;
                out_re <= 0;
                out_im <= 0;
                rho_out <= 0;
                done <= 1'b0;
            end else if (active && sample_valid) begin
                case (mode)
                    MODE_HPSI: begin
                        out_re <= hpsi_re;
                        out_im <= hpsi_im;
                        valid <= 1'b1;
                    end
                    MODE_SUM_BAND: begin
                        rho_acc <= rho_acc_next;
                        rho_out <= rho_acc_next;
                        valid <= band_last;
                    end
                    MODE_AXPY: begin
                        out_re <= y_re_ext + alpha_x_re;
                        out_im <= y_im_ext + alpha_x_im;
                        valid <= 1'b1;
                    end
                    default: begin
                        out_re <= 0;
                        out_im <= 0;
                        rho_out <= 0;
                        valid <= 1'b0;
                    end
                endcase
                if (sample_count == TOTAL_SAMPLES - 1) begin
                    active <= 1'b0;
                    done <= 1'b1;
                end
                sample_count <= sample_count + 1;
            end
        end
    end
endmodule
