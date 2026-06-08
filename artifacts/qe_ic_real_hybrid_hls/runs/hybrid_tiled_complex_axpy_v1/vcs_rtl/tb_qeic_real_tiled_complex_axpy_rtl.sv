module tb_qeic_real_tiled_complex_axpy_rtl;
    localparam integer N = 64;
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 48;
    localparam signed [WIDTH-1:0] ALPHA_RE = 18'sd192;
    localparam signed [WIDTH-1:0] ALPHA_IM = -18'sd32;
    reg clk;
    reg reset_n;
    reg start;
    reg sample_valid;
    reg signed [WIDTH-1:0] x_re_mem [0:N-1];
    reg signed [WIDTH-1:0] x_im_mem [0:N-1];
    reg signed [WIDTH-1:0] y_re_mem [0:N-1];
    reg signed [WIDTH-1:0] y_im_mem [0:N-1];
    reg signed [WIDTH-1:0] x_re;
    reg signed [WIDTH-1:0] x_im;
    reg signed [WIDTH-1:0] y_re;
    reg signed [WIDTH-1:0] y_im;
    wire signed [ACC_WIDTH-1:0] out_re;
    wire signed [ACC_WIDTH-1:0] out_im;
    wire valid;
    wire done;
    reg signed [ACC_WIDTH-1:0] expected_re [0:N-1];
    reg signed [ACC_WIDTH-1:0] expected_im [0:N-1];
    integer i;
    integer valid_count;
    integer latency_cycles;

    qeic_real_tiled_complex_axpy_rtl #(.N(N), .WIDTH(WIDTH), .ACC_WIDTH(ACC_WIDTH), .ALPHA_RE(ALPHA_RE), .ALPHA_IM(ALPHA_IM)) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .sample_valid(sample_valid),
        .x_re(x_re),
        .x_im(x_im),
        .y_re(y_re),
        .y_im(y_im),
        .out_re(out_re),
        .out_im(out_im),
        .valid(valid),
        .done(done)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        reset_n = 1'b0;
        start = 1'b0;
        sample_valid = 1'b0;
        x_re = 0;
        x_im = 0;
        y_re = 0;
        y_im = 0;
        valid_count = 0;
        latency_cycles = 0;
        for (i = 0; i < N; i = i + 1) begin
            x_re_mem[i] = 18'sd16 + i * 18'sd3;
            x_im_mem[i] = -18'sd11 - i * 18'sd2;
            y_re_mem[i] = 18'sd7 + (i & 7);
            y_im_mem[i] = -18'sd5 - (i & 5);
            expected_re[i] = (y_re_mem[i] <<< 8) + (ALPHA_RE * x_re_mem[i]) - (ALPHA_IM * x_im_mem[i]);
            expected_im[i] = (y_im_mem[i] <<< 8) + (ALPHA_RE * x_im_mem[i]) + (ALPHA_IM * x_re_mem[i]);
        end
        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;
        for (i = 0; i < N; i = i + 1) begin
            @(negedge clk);
            x_re = x_re_mem[i];
            x_im = x_im_mem[i];
            y_re = y_re_mem[i];
            y_im = y_im_mem[i];
            sample_valid = 1'b1;
            @(posedge clk);
            #1;
            latency_cycles = latency_cycles + 1;
            if (valid !== 1'b1 || out_re !== expected_re[i] || out_im !== expected_im[i]) begin
                $display("DSE_REAL_RTL_FAIL sample=%0d expected=%0d,%0d got=%0d,%0d valid=%0d", i, expected_re[i], expected_im[i], out_re, out_im, valid);
                $finish(1);
            end
            valid_count = valid_count + 1;
        end
        @(negedge clk);
        sample_valid = 1'b0;
        #1;
        if (done !== 1'b1 || valid_count != N) begin
            $display("DSE_REAL_RTL_FAIL done=%0d valid_count=%0d", done, valid_count);
            $finish(1);
        end
        $display("DSE_REAL_RTL_PASS qeic_real_tiled_complex_axpy_rtl samples=%0d", valid_count);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
