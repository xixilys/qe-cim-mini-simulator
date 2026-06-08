module qeic_real_integrated_streaming_pipeline_sidecar_rtl #(
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
    integer accepted_count;
    integer completed_count;

    reg stage1_valid;
    reg [1:0] mode_s1;
    reg band_first_s1;
    reg band_last_s1;
    reg signed [WIDTH-1:0] a_re_s1;
    reg signed [WIDTH-1:0] a_im_s1;
    reg signed [WIDTH-1:0] b_re_s1;
    reg signed [WIDTH-1:0] b_im_s1;
    reg signed [WIDTH-1:0] c_re_s1;
    reg signed [WIDTH-1:0] c_im_s1;
    reg signed [WIDTH-1:0] weight_s1;
    reg signed [WIDTH-1:0] y_re_s1;
    reg signed [WIDTH-1:0] y_im_s1;

    reg stage2_valid;
    reg [1:0] mode_s2;
    reg band_first_s2;
    reg band_last_s2;
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

    reg stage3_valid;
    reg [1:0] mode_s3;
    reg band_first_s3;
    reg band_last_s3;
    reg signed [ACC_WIDTH-1:0] hpsi_re_s3;
    reg signed [ACC_WIDTH-1:0] hpsi_im_s3;
    reg signed [(ACC_WIDTH+WIDTH)-1:0] weighted_s3;
    reg signed [ACC_WIDTH-1:0] axpy_re_s3;
    reg signed [ACC_WIDTH-1:0] axpy_im_s3;
    reg signed [ACC_WIDTH-1:0] rho_acc;

    wire signed [ACC_WIDTH-1:0] sb_contribution_s3 = weighted_s3[ACC_WIDTH+WIDTH-1:WIDTH];
    wire signed [ACC_WIDTH-1:0] rho_acc_next = band_first_s3 ? sb_contribution_s3 : (rho_acc + sb_contribution_s3);

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            accepted_count <= 0;
            completed_count <= 0;
            stage1_valid <= 1'b0;
            stage2_valid <= 1'b0;
            stage3_valid <= 1'b0;
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
                accepted_count <= 0;
                completed_count <= 0;
                stage1_valid <= 1'b0;
                stage2_valid <= 1'b0;
                stage3_valid <= 1'b0;
                rho_acc <= 0;
                out_re <= 0;
                out_im <= 0;
                rho_out <= 0;
                done <= 1'b0;
            end else if (active) begin
                if (stage3_valid) begin
                    case (mode_s3)
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
                            valid <= band_last_s3;
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
                    if (completed_count == TOTAL_SAMPLES - 1) begin
                        active <= 1'b0;
                        done <= 1'b1;
                    end
                    completed_count <= completed_count + 1;
                end

                stage3_valid <= stage2_valid;
                mode_s3 <= mode_s2;
                band_first_s3 <= band_first_s2;
                band_last_s3 <= band_last_s2;
                hpsi_re_s3 <= -(lap_re_s2 >>> 1) + (vloc_re_s2 >>> 8);
                hpsi_im_s3 <= -(lap_im_s2 >>> 1) + (vloc_im_s2 >>> 8);
                weighted_s3 <= ({{(ACC_WIDTH-(2*WIDTH)){1'b0}}, re_sq_s2 + im_sq_s2}) * weight_s2;
                axpy_re_s3 <= y_re_ext_s2 + alpha_x_re_s2;
                axpy_im_s3 <= y_im_ext_s2 + alpha_x_im_s2;

                stage2_valid <= stage1_valid;
                mode_s2 <= mode_s1;
                band_first_s2 <= band_first_s1;
                band_last_s2 <= band_last_s1;
                lap_re_s2 <= {{(ACC_WIDTH-WIDTH){a_re_s1[WIDTH-1]}}, a_re_s1}
                    - ({{(ACC_WIDTH-WIDTH){b_re_s1[WIDTH-1]}}, b_re_s1} <<< 1)
                    + {{(ACC_WIDTH-WIDTH){c_re_s1[WIDTH-1]}}, c_re_s1};
                lap_im_s2 <= {{(ACC_WIDTH-WIDTH){a_im_s1[WIDTH-1]}}, a_im_s1}
                    - ({{(ACC_WIDTH-WIDTH){b_im_s1[WIDTH-1]}}, b_im_s1} <<< 1)
                    + {{(ACC_WIDTH-WIDTH){c_im_s1[WIDTH-1]}}, c_im_s1};
                vloc_re_s2 <= weight_s1 * b_re_s1;
                vloc_im_s2 <= weight_s1 * b_im_s1;
                re_sq_s2 <= b_re_s1 * b_re_s1;
                im_sq_s2 <= b_im_s1 * b_im_s1;
                weight_s2 <= weight_s1;
                alpha_x_re_s2 <= (ALPHA_RE * a_re_s1) - (ALPHA_IM * a_im_s1);
                alpha_x_im_s2 <= (ALPHA_RE * a_im_s1) + (ALPHA_IM * a_re_s1);
                y_re_ext_s2 <= {{(ACC_WIDTH-WIDTH){y_re_s1[WIDTH-1]}}, y_re_s1} <<< 8;
                y_im_ext_s2 <= {{(ACC_WIDTH-WIDTH){y_im_s1[WIDTH-1]}}, y_im_s1} <<< 8;

                if (sample_valid && accepted_count < TOTAL_SAMPLES) begin
                    stage1_valid <= 1'b1;
                    mode_s1 <= mode;
                    band_first_s1 <= band_first;
                    band_last_s1 <= band_last;
                    a_re_s1 <= a_re;
                    a_im_s1 <= a_im;
                    b_re_s1 <= b_re;
                    b_im_s1 <= b_im;
                    c_re_s1 <= c_re;
                    c_im_s1 <= c_im;
                    weight_s1 <= weight;
                    y_re_s1 <= y_re;
                    y_im_s1 <= y_im;
                    accepted_count <= accepted_count + 1;
                end else begin
                    stage1_valid <= 1'b0;
                end
            end
        end
    end
endmodule
