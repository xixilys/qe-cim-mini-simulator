module qeic_real_integrated_pipelined_sidecar_impl_top (
    input  wire clk,
    input  wire reset_n,
    input  wire start,
    output wire done,
    output wire [47:0] checksum
);
    localparam integer HPSI_N = 96;
    localparam integer SUM_GRID = 32;
    localparam integer SUM_BANDS = 4;
    localparam integer SUM_SAMPLES = 128;
    localparam integer AXPY_N = 64;
    localparam integer TOTAL_SAMPLES = 288;
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 48;
    localparam [1:0] MODE_HPSI = 2'd0;
    localparam [1:0] MODE_SUM_BAND = 2'd1;
    localparam [1:0] MODE_AXPY = 2'd2;

    reg sidecar_start;
    reg active;
    reg sample_valid;
    reg [1:0] mode;
    reg band_first;
    reg band_last;
    reg signed [WIDTH-1:0] a_re;
    reg signed [WIDTH-1:0] a_im;
    reg signed [WIDTH-1:0] b_re;
    reg signed [WIDTH-1:0] b_im;
    reg signed [WIDTH-1:0] c_re;
    reg signed [WIDTH-1:0] c_im;
    reg signed [WIDTH-1:0] weight;
    reg signed [WIDTH-1:0] y_re;
    reg signed [WIDTH-1:0] y_im;
    reg [15:0] sample_index;
    reg [47:0] checksum_reg;
    reg done_reg;

    wire signed [ACC_WIDTH-1:0] out_re;
    wire signed [ACC_WIDTH-1:0] out_im;
    wire signed [ACC_WIDTH-1:0] rho_out;
    wire valid;
    wire sidecar_done;
    wire [15:0] sum_phase = sample_index - 16'd96;
    wire [1:0] sum_band_mod = sum_phase[1:0];

    assign checksum = checksum_reg;
    assign done = done_reg | sidecar_done;

    qeic_real_integrated_pipelined_sidecar_rtl #(
        .TOTAL_SAMPLES(TOTAL_SAMPLES),
        .WIDTH(WIDTH),
        .ACC_WIDTH(ACC_WIDTH)
    ) sidecar (
        .clk(clk),
        .reset_n(reset_n),
        .start(sidecar_start),
        .sample_valid(sample_valid),
        .mode(mode),
        .band_first(band_first),
        .band_last(band_last),
        .a_re(a_re),
        .a_im(a_im),
        .b_re(b_re),
        .b_im(b_im),
        .c_re(c_re),
        .c_im(c_im),
        .weight(weight),
        .y_re(y_re),
        .y_im(y_im),
        .out_re(out_re),
        .out_im(out_im),
        .rho_out(rho_out),
        .valid(valid),
        .done(sidecar_done)
    );

    always @* begin
        if (sample_index < HPSI_N) begin
            mode = MODE_HPSI;
        end else if (sample_index < HPSI_N + SUM_SAMPLES) begin
            mode = MODE_SUM_BAND;
        end else begin
            mode = MODE_AXPY;
        end
        sample_valid = active;
        band_first = active && mode == MODE_SUM_BAND && sum_band_mod == 2'd0;
        band_last = active && mode == MODE_SUM_BAND && sum_band_mod == 2'd3;
        a_re = 18'sd64 + $signed({2'b00, sample_index});
        a_im = -18'sd51 - $signed({2'b00, sample_index});
        b_re = 18'sd32 + $signed({2'b00, sample_index[14:0], 1'b0});
        b_im = -18'sd21 - $signed({2'b00, sample_index});
        c_re = 18'sd67 + $signed({2'b00, sample_index});
        c_im = -18'sd47 - $signed({2'b00, sample_index});
        weight = 18'sd64 + $signed({12'b0, sample_index[5:0]});
        y_re = 18'sd7 + $signed({15'b0, sample_index[2:0]});
        y_im = -18'sd5 - $signed({15'b0, sample_index[2:0]});
    end

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            sidecar_start <= 1'b0;
            active <= 1'b0;
            sample_index <= 16'd0;
            checksum_reg <= 48'd0;
            done_reg <= 1'b0;
        end else begin
            sidecar_start <= 1'b0;
            if (start && !active) begin
                sidecar_start <= 1'b1;
                active <= 1'b1;
                sample_index <= 16'd0;
                checksum_reg <= 48'd0;
                done_reg <= 1'b0;
            end else if (active) begin
                if (valid) begin
                    checksum_reg <= checksum_reg + out_re[47:0] + out_im[47:0] + rho_out[47:0];
                end
                if (sample_index == 16'd287) begin
                    active <= 1'b0;
                    done_reg <= 1'b1;
                end else begin
                    sample_index <= sample_index + 16'd1;
                end
            end
        end
    end
endmodule
