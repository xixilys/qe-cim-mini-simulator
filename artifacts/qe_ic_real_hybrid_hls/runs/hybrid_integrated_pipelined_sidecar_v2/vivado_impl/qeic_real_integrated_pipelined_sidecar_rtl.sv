module qeic_real_integrated_pipelined_sidecar_rtl #(
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
    reg busy;
    reg [2:0] phase;
    integer processed_count;
    reg stage1_valid;
    reg stage2_valid;
    reg stage3_valid;
    reg stage4_valid;

    reg [1:0] mode_r;
    reg band_first_r;
    reg band_last_r;
    reg signed [WIDTH-1:0] a_re_r;
    reg signed [WIDTH-1:0] a_im_r;
    reg signed [WIDTH-1:0] b_re_r;
    reg signed [WIDTH-1:0] b_im_r;
    reg signed [WIDTH-1:0] c_re_r;
    reg signed [WIDTH-1:0] c_im_r;
    reg signed [WIDTH-1:0] weight_r;
    reg signed [WIDTH-1:0] y_re_r;
    reg signed [WIDTH-1:0] y_im_r;

    reg signed [ACC_WIDTH-1:0] lap_re_s2;
    reg signed [ACC_WIDTH-1:0] lap_im_s2;
    reg signed [(2*WIDTH)-1:0] vloc_re_s2;
    reg signed [(2*WIDTH)-1:0] vloc_im_s2;
    reg signed [(2*WIDTH)-1:0] re_sq_s2;
    reg signed [(2*WIDTH)-1:0] im_sq_s2;
    reg signed [WIDTH-1:0] weight_s2;
    reg signed [ACC_WIDTH-1:0] alpha_x_re_s2;
    reg signed [ACC_WIDTH-1:0] alpha_x_im_s2;
    reg signed [ACC_WIDTH-1:0] y_re_ext_s2;
    reg signed [ACC_WIDTH-1:0] y_im_ext_s2;

    reg signed [ACC_WIDTH-1:0] hpsi_re_s3;
    reg signed [ACC_WIDTH-1:0] hpsi_im_s3;
    reg signed [ACC_WIDTH-1:0] abs_sq_s3;
    reg signed [(ACC_WIDTH+WIDTH)-1:0] weighted_s3;
    reg signed [ACC_WIDTH-1:0] axpy_re_s3;
    reg signed [ACC_WIDTH-1:0] axpy_im_s3;
    reg signed [ACC_WIDTH-1:0] rho_acc;
    wire signed [ACC_WIDTH-1:0] sb_contribution_s3 = weighted_s3[ACC_WIDTH+WIDTH-1:WIDTH];
    wire signed [ACC_WIDTH-1:0] rho_acc_next = band_first_r ? sb_contribution_s3 : (rho_acc + sb_contribution_s3);

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            busy <= 1'b0;
            phase <= 3'd0;
            processed_count <= 0;
            stage1_valid <= 1'b0;
            stage2_valid <= 1'b0;
            stage3_valid <= 1'b0;
            stage4_valid <= 1'b0;
            rho_acc <= 0;
            out_re <= 0;
            out_im <= 0;
            rho_out <= 0;
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            stage1_valid <= 1'b0;
            stage2_valid <= 1'b0;
            stage3_valid <= 1'b0;
            stage4_valid <= 1'b0;
            valid <= 1'b0;
            if (start) begin
                active <= 1'b1;
                busy <= 1'b0;
                phase <= 3'd0;
                processed_count <= 0;
                rho_acc <= 0;
                out_re <= 0;
                out_im <= 0;
                rho_out <= 0;
                done <= 1'b0;
            end else if (active) begin
                if (!busy && sample_valid) begin
                    mode_r <= mode;
                    band_first_r <= band_first;
                    band_last_r <= band_last;
                    a_re_r <= a_re;
                    a_im_r <= a_im;
                    b_re_r <= b_re;
                    b_im_r <= b_im;
                    c_re_r <= c_re;
                    c_im_r <= c_im;
                    weight_r <= weight;
                    y_re_r <= y_re;
                    y_im_r <= y_im;
                    busy <= 1'b1;
                    phase <= 3'd1;
                    stage1_valid <= 1'b1;
                end else if (busy) begin
                    case (phase)
                        3'd1: begin
                            lap_re_s2 <= {{(ACC_WIDTH-WIDTH){a_re_r[WIDTH-1]}}, a_re_r}
                                - ({{(ACC_WIDTH-WIDTH){b_re_r[WIDTH-1]}}, b_re_r} <<< 1)
                                + {{(ACC_WIDTH-WIDTH){c_re_r[WIDTH-1]}}, c_re_r};
                            lap_im_s2 <= {{(ACC_WIDTH-WIDTH){a_im_r[WIDTH-1]}}, a_im_r}
                                - ({{(ACC_WIDTH-WIDTH){b_im_r[WIDTH-1]}}, b_im_r} <<< 1)
                                + {{(ACC_WIDTH-WIDTH){c_im_r[WIDTH-1]}}, c_im_r};
                            vloc_re_s2 <= weight_r * b_re_r;
                            vloc_im_s2 <= weight_r * b_im_r;
                            re_sq_s2 <= b_re_r * b_re_r;
                            im_sq_s2 <= b_im_r * b_im_r;
                            weight_s2 <= weight_r;
                            alpha_x_re_s2 <= (ALPHA_RE * a_re_r) - (ALPHA_IM * a_im_r);
                            alpha_x_im_s2 <= (ALPHA_RE * a_im_r) + (ALPHA_IM * a_re_r);
                            y_re_ext_s2 <= {{(ACC_WIDTH-WIDTH){y_re_r[WIDTH-1]}}, y_re_r} <<< 8;
                            y_im_ext_s2 <= {{(ACC_WIDTH-WIDTH){y_im_r[WIDTH-1]}}, y_im_r} <<< 8;
                            stage2_valid <= 1'b1;
                            phase <= 3'd2;
                        end
                        3'd2: begin
                            hpsi_re_s3 <= -(lap_re_s2 >>> 1) + (vloc_re_s2 >>> 8);
                            hpsi_im_s3 <= -(lap_im_s2 >>> 1) + (vloc_im_s2 >>> 8);
                            abs_sq_s3 <= {{(ACC_WIDTH-(2*WIDTH)){1'b0}}, re_sq_s2 + im_sq_s2};
                            weighted_s3 <= ({{(ACC_WIDTH-(2*WIDTH)){1'b0}}, re_sq_s2 + im_sq_s2}) * weight_s2;
                            axpy_re_s3 <= y_re_ext_s2 + alpha_x_re_s2;
                            axpy_im_s3 <= y_im_ext_s2 + alpha_x_im_s2;
                            stage3_valid <= 1'b1;
                            phase <= 3'd3;
                        end
                        default: begin
                            case (mode_r)
                                MODE_HPSI: begin
                                    out_re <= hpsi_re_s3;
                                    out_im <= hpsi_im_s3;
                                    rho_out <= 0;
                                    valid <= 1'b1;
                                end
                                MODE_SUM_BAND: begin
                                    rho_acc <= rho_acc_next;
                                    rho_out <= rho_acc_next;
                                    out_re <= 0;
                                    out_im <= 0;
                                    valid <= band_last_r;
                                end
                                MODE_AXPY: begin
                                    out_re <= axpy_re_s3;
                                    out_im <= axpy_im_s3;
                                    rho_out <= 0;
                                    valid <= 1'b1;
                                end
                                default: begin
                                    out_re <= 0;
                                    out_im <= 0;
                                    rho_out <= 0;
                                    valid <= 1'b0;
                                end
                            endcase
                            stage4_valid <= 1'b1;
                            if (processed_count == TOTAL_SAMPLES - 1) begin
                                active <= 1'b0;
                                done <= 1'b1;
                            end
                            processed_count <= processed_count + 1;
                            busy <= 1'b0;
                            phase <= 3'd0;
                        end
                    endcase
                end
            end
        end
    end
endmodule
