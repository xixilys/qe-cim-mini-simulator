module tb_qeic_real_hpsi_local_potential_rtl;
    localparam integer N = 96;
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 40;
    reg clk;
    reg reset_n;
    reg start;
    reg sample_valid;
    reg signed [WIDTH-1:0] psi_re [0:N-1];
    reg signed [WIDTH-1:0] psi_im [0:N-1];
    reg signed [WIDTH-1:0] vloc [0:N-1];
    reg signed [WIDTH-1:0] psi_re_left;
    reg signed [WIDTH-1:0] psi_re_center;
    reg signed [WIDTH-1:0] psi_re_right;
    reg signed [WIDTH-1:0] psi_im_left;
    reg signed [WIDTH-1:0] psi_im_center;
    reg signed [WIDTH-1:0] psi_im_right;
    reg signed [WIDTH-1:0] vloc_center;
    wire signed [ACC_WIDTH-1:0] out_re;
    wire signed [ACC_WIDTH-1:0] out_im;
    wire valid;
    wire done;
    reg signed [ACC_WIDTH-1:0] expected_re [0:N-1];
    reg signed [ACC_WIDTH-1:0] expected_im [0:N-1];
    integer g;
    integer left;
    integer right;
    integer valid_count;
    integer latency_cycles;
    reg signed [ACC_WIDTH-1:0] lap_re;
    reg signed [ACC_WIDTH-1:0] lap_im;

    qeic_real_hpsi_local_potential_rtl #(.N(N), .WIDTH(WIDTH), .ACC_WIDTH(ACC_WIDTH)) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .sample_valid(sample_valid),
        .psi_re_left(psi_re_left),
        .psi_re_center(psi_re_center),
        .psi_re_right(psi_re_right),
        .psi_im_left(psi_im_left),
        .psi_im_center(psi_im_center),
        .psi_im_right(psi_im_right),
        .vloc_center(vloc_center),
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
        psi_re_left = 0;
        psi_re_center = 0;
        psi_re_right = 0;
        psi_im_left = 0;
        psi_im_center = 0;
        psi_im_right = 0;
        vloc_center = 0;
        valid_count = 0;
        latency_cycles = 0;
        for (g = 0; g < N; g = g + 1) begin
            psi_re[g] = 18'sd64 + g * 18'sd3;
            psi_im[g] = -18'sd51 - g * 18'sd2;
            vloc[g] = 18'sd128 + ((g * 17) & 31);
        end
        for (g = 0; g < N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == N - 1) ? N - 1 : g + 1;
            lap_re = psi_re[left] - (psi_re[g] <<< 1) + psi_re[right];
            lap_im = psi_im[left] - (psi_im[g] <<< 1) + psi_im[right];
            expected_re[g] = -(lap_re >>> 1) + ((vloc[g] * psi_re[g]) >>> 8);
            expected_im[g] = -(lap_im >>> 1) + ((vloc[g] * psi_im[g]) >>> 8);
        end
        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;
        for (g = 0; g < N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == N - 1) ? N - 1 : g + 1;
            psi_re_left = psi_re[left];
            psi_re_center = psi_re[g];
            psi_re_right = psi_re[right];
            psi_im_left = psi_im[left];
            psi_im_center = psi_im[g];
            psi_im_right = psi_im[right];
            vloc_center = vloc[g];
            sample_valid = 1'b1;
            @(posedge clk);
            #1;
            latency_cycles = latency_cycles + 1;
            if (valid !== 1'b1 || out_re !== expected_re[g] || out_im !== expected_im[g]) begin
                $display("DSE_REAL_RTL_FAIL sample=%0d expected=%0d,%0d got=%0d,%0d valid=%0d", g, expected_re[g], expected_im[g], out_re, out_im, valid);
                $finish(1);
            end
            valid_count = valid_count + 1;
        end
        sample_valid = 1'b0;
        #1;
        if (done !== 1'b1 || valid_count != N) begin
            $display("DSE_REAL_RTL_FAIL done=%0d valid_count=%0d", done, valid_count);
            $finish(1);
        end
        $display("DSE_REAL_RTL_PASS qeic_real_hpsi_local_potential_rtl samples=%0d", valid_count);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
