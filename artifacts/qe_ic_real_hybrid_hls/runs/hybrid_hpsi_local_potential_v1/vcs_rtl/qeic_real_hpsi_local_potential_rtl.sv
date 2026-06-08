module qeic_real_hpsi_local_potential_rtl #(
    parameter integer N = 96,
    parameter integer WIDTH = 18,
    parameter integer ACC_WIDTH = 40
) (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    input  wire sample_valid,
    input  wire signed [WIDTH-1:0] psi_re_left,
    input  wire signed [WIDTH-1:0] psi_re_center,
    input  wire signed [WIDTH-1:0] psi_re_right,
    input  wire signed [WIDTH-1:0] psi_im_left,
    input  wire signed [WIDTH-1:0] psi_im_center,
    input  wire signed [WIDTH-1:0] psi_im_right,
    input  wire signed [WIDTH-1:0] vloc_center,
    output wire signed [ACC_WIDTH-1:0] out_re,
    output wire signed [ACC_WIDTH-1:0] out_im,
    output wire valid,
    output reg  done
);
    reg active;
    integer sample_count;
    wire signed [ACC_WIDTH-1:0] lap_re =
        {{(ACC_WIDTH-WIDTH){psi_re_left[WIDTH-1]}}, psi_re_left}
        - ({{(ACC_WIDTH-WIDTH){psi_re_center[WIDTH-1]}}, psi_re_center} <<< 1)
        + {{(ACC_WIDTH-WIDTH){psi_re_right[WIDTH-1]}}, psi_re_right};
    wire signed [ACC_WIDTH-1:0] lap_im =
        {{(ACC_WIDTH-WIDTH){psi_im_left[WIDTH-1]}}, psi_im_left}
        - ({{(ACC_WIDTH-WIDTH){psi_im_center[WIDTH-1]}}, psi_im_center} <<< 1)
        + {{(ACC_WIDTH-WIDTH){psi_im_right[WIDTH-1]}}, psi_im_right};
    wire signed [(2*WIDTH)-1:0] pot_re = vloc_center * psi_re_center;
    wire signed [(2*WIDTH)-1:0] pot_im = vloc_center * psi_im_center;
    wire signed [ACC_WIDTH-1:0] pot_re_ext = {{(ACC_WIDTH-(2*WIDTH)){pot_re[(2*WIDTH)-1]}}, pot_re};
    wire signed [ACC_WIDTH-1:0] pot_im_ext = {{(ACC_WIDTH-(2*WIDTH)){pot_im[(2*WIDTH)-1]}}, pot_im};

    assign out_re = -(lap_re >>> 1) + (pot_re_ext >>> 8);
    assign out_im = -(lap_im >>> 1) + (pot_im_ext >>> 8);
    assign valid = sample_valid;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            active <= 1'b0;
            sample_count <= 0;
            done <= 1'b0;
        end else begin
            if (start) begin
                active <= 1'b1;
                sample_count <= 0;
                done <= 1'b0;
            end else if (active && sample_valid) begin
                if (sample_count == N - 1) begin
                    active <= 1'b0;
                    done <= 1'b1;
                end
                sample_count <= sample_count + 1;
            end
        end
    end
endmodule
