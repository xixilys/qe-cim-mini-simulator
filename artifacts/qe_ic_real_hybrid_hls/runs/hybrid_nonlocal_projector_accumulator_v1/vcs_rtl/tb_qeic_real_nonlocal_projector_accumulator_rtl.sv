module tb_qeic_real_nonlocal_projector_accumulator_rtl;
    localparam integer NGRID = 16;
    localparam integer NBANDS = 4;
    localparam integer NPROJ = 4;
    localparam integer SAMPLES = 256;
    localparam integer OUTPUTS = 16;
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 56;
    reg clk;
    reg reset_n;
    reg start;
    reg sample_valid;
    reg sample_first;
    reg sample_last;
    reg signed [WIDTH-1:0] beta_re_mem [0:(NPROJ*NGRID)-1];
    reg signed [WIDTH-1:0] beta_im_mem [0:(NPROJ*NGRID)-1];
    reg signed [WIDTH-1:0] psi_re_mem [0:(NBANDS*NGRID)-1];
    reg signed [WIDTH-1:0] psi_im_mem [0:(NBANDS*NGRID)-1];
    reg signed [WIDTH-1:0] beta_re;
    reg signed [WIDTH-1:0] beta_im;
    reg signed [WIDTH-1:0] psi_re;
    reg signed [WIDTH-1:0] psi_im;
    wire signed [ACC_WIDTH-1:0] proj_re;
    wire signed [ACC_WIDTH-1:0] proj_im;
    wire valid;
    wire done;
    reg signed [ACC_WIDTH-1:0] expected_re [0:OUTPUTS-1];
    reg signed [ACC_WIDTH-1:0] expected_im [0:OUTPUTS-1];
    reg signed [(2*WIDTH)-1:0] rr;
    reg signed [(2*WIDTH)-1:0] ii;
    reg signed [(2*WIDTH)-1:0] ri;
    reg signed [(2*WIDTH)-1:0] ir;
    integer p;
    integer b;
    integer g;
    integer pg;
    integer bg;
    integer idx;
    integer output_idx;
    integer valid_count;
    integer latency_cycles;

    qeic_real_nonlocal_projector_accumulator_rtl #(.SAMPLES(SAMPLES), .WIDTH(WIDTH), .ACC_WIDTH(ACC_WIDTH)) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .sample_valid(sample_valid),
        .sample_first(sample_first),
        .sample_last(sample_last),
        .beta_re(beta_re),
        .beta_im(beta_im),
        .psi_re(psi_re),
        .psi_im(psi_im),
        .proj_re(proj_re),
        .proj_im(proj_im),
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
        sample_first = 1'b0;
        sample_last = 1'b0;
        beta_re = 0;
        beta_im = 0;
        psi_re = 0;
        psi_im = 0;
        valid_count = 0;
        latency_cycles = 0;
        for (p = 0; p < NPROJ; p = p + 1) begin
            for (g = 0; g < NGRID; g = g + 1) begin
                pg = p * NGRID + g;
                beta_re_mem[pg] = 18'sd9 + p * 18'sd3 + g;
                beta_im_mem[pg] = -18'sd7 - p * 18'sd2 + (g & 3);
            end
        end
        for (b = 0; b < NBANDS; b = b + 1) begin
            for (g = 0; g < NGRID; g = g + 1) begin
                bg = b * NGRID + g;
                psi_re_mem[bg] = 18'sd21 + b * 18'sd5 + g * 18'sd2;
                psi_im_mem[bg] = -18'sd13 - b * 18'sd4 - g;
            end
        end
        for (p = 0; p < NPROJ; p = p + 1) begin
            for (b = 0; b < NBANDS; b = b + 1) begin
                idx = p * NBANDS + b;
                expected_re[idx] = 0;
                expected_im[idx] = 0;
                for (g = 0; g < NGRID; g = g + 1) begin
                    pg = p * NGRID + g;
                    bg = b * NGRID + g;
                    rr = beta_re_mem[pg] * psi_re_mem[bg];
                    ii = beta_im_mem[pg] * psi_im_mem[bg];
                    ri = beta_re_mem[pg] * psi_im_mem[bg];
                    ir = beta_im_mem[pg] * psi_re_mem[bg];
                    expected_re[idx] = expected_re[idx] + rr + ii;
                    expected_im[idx] = expected_im[idx] + ri - ir;
                end
            end
        end
        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;
        output_idx = 0;
        for (p = 0; p < NPROJ; p = p + 1) begin
            for (b = 0; b < NBANDS; b = b + 1) begin
                for (g = 0; g < NGRID; g = g + 1) begin
                    @(negedge clk);
                    pg = p * NGRID + g;
                    bg = b * NGRID + g;
                    beta_re = beta_re_mem[pg];
                    beta_im = beta_im_mem[pg];
                    psi_re = psi_re_mem[bg];
                    psi_im = psi_im_mem[bg];
                    sample_first = (g == 0);
                    sample_last = (g == NGRID - 1);
                    sample_valid = 1'b1;
                    @(posedge clk);
                    #1;
                    latency_cycles = latency_cycles + 1;
                    if (sample_last) begin
                        if (valid !== 1'b1 || proj_re !== expected_re[output_idx] || proj_im !== expected_im[output_idx]) begin
                            $display("DSE_REAL_RTL_FAIL p=%0d b=%0d expected=%0d,%0d got=%0d,%0d valid=%0d", p, b, expected_re[output_idx], expected_im[output_idx], proj_re, proj_im, valid);
                            $finish(1);
                        end
                        output_idx = output_idx + 1;
                        valid_count = valid_count + 1;
                    end
                end
            end
        end
        @(negedge clk);
        sample_valid = 1'b0;
        sample_first = 1'b0;
        sample_last = 1'b0;
        #1;
        if (done !== 1'b1 || valid_count != OUTPUTS) begin
            $display("DSE_REAL_RTL_FAIL done=%0d valid_count=%0d", done, valid_count);
            $finish(1);
        end
        $display("DSE_REAL_RTL_PASS qeic_real_nonlocal_projector_accumulator_rtl samples=%0d", SAMPLES);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
