module tb_qeic_real_sum_band_density_accumulator_rtl;
    localparam integer NGRID = 32;
    localparam integer NBANDS = 4;
    localparam integer SAMPLES = 128;
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 48;
    reg clk;
    reg reset_n;
    reg start;
    reg sample_valid;
    reg band_first;
    reg band_last;
    reg signed [WIDTH-1:0] psi_re [0:SAMPLES-1];
    reg signed [WIDTH-1:0] psi_im [0:SAMPLES-1];
    reg signed [WIDTH-1:0] weight [0:NBANDS-1];
    reg signed [WIDTH-1:0] psi_re_in;
    reg signed [WIDTH-1:0] psi_im_in;
    reg signed [WIDTH-1:0] weight_in;
    wire signed [ACC_WIDTH-1:0] rho_out;
    wire valid;
    wire done;
    reg signed [ACC_WIDTH-1:0] expected_rho [0:NGRID-1];
    reg signed [ACC_WIDTH-1:0] acc;
    reg signed [(2*WIDTH)-1:0] re_sq;
    reg signed [(2*WIDTH)-1:0] im_sq;
    reg signed [ACC_WIDTH-1:0] abs_sq;
    integer g;
    integer b;
    integer idx;
    integer valid_count;
    integer latency_cycles;

    qeic_real_sum_band_density_accumulator_rtl #(.SAMPLES(SAMPLES), .WIDTH(WIDTH), .ACC_WIDTH(ACC_WIDTH)) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .sample_valid(sample_valid),
        .band_first(band_first),
        .band_last(band_last),
        .psi_re(psi_re_in),
        .psi_im(psi_im_in),
        .weight(weight_in),
        .rho_out(rho_out),
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
        band_first = 1'b0;
        band_last = 1'b0;
        psi_re_in = 0;
        psi_im_in = 0;
        weight_in = 0;
        valid_count = 0;
        latency_cycles = 0;
        for (b = 0; b < NBANDS; b = b + 1) begin
            weight[b] = 18'sd64 + b * 18'sd11;
        end
        for (g = 0; g < NGRID; g = g + 1) begin
            expected_rho[g] = 0;
        end
        for (b = 0; b < NBANDS; b = b + 1) begin
            for (g = 0; g < NGRID; g = g + 1) begin
                idx = b * NGRID + g;
                psi_re[idx] = 18'sd32 + idx * 18'sd2 + (g & 3);
                psi_im[idx] = -18'sd21 - idx;
            end
        end
        for (g = 0; g < NGRID; g = g + 1) begin
            acc = 0;
            for (b = 0; b < NBANDS; b = b + 1) begin
                idx = b * NGRID + g;
                re_sq = psi_re[idx] * psi_re[idx];
                im_sq = psi_im[idx] * psi_im[idx];
                abs_sq = re_sq + im_sq;
                acc = acc + ((abs_sq * weight[b]) >>> WIDTH);
            end
            expected_rho[g] = acc;
        end
        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;
        for (g = 0; g < NGRID; g = g + 1) begin
            for (b = 0; b < NBANDS; b = b + 1) begin
                @(negedge clk);
                idx = b * NGRID + g;
                psi_re_in = psi_re[idx];
                psi_im_in = psi_im[idx];
                weight_in = weight[b];
                band_first = (b == 0);
                band_last = (b == NBANDS - 1);
                sample_valid = 1'b1;
                @(posedge clk);
                #1;
                latency_cycles = latency_cycles + 1;
                if (band_last) begin
                    if (valid !== 1'b1 || rho_out !== expected_rho[g]) begin
                        $display("DSE_REAL_RTL_FAIL grid=%0d expected=%0d got=%0d valid=%0d", g, expected_rho[g], rho_out, valid);
                        $finish(1);
                    end
                    valid_count = valid_count + 1;
                end
            end
        end
        @(negedge clk);
        sample_valid = 1'b0;
        band_first = 1'b0;
        band_last = 1'b0;
        #1;
        if (done !== 1'b1 || valid_count != NGRID) begin
            $display("DSE_REAL_RTL_FAIL done=%0d valid_count=%0d", done, valid_count);
            $finish(1);
        end
        $display("DSE_REAL_RTL_PASS qeic_real_sum_band_density_accumulator_rtl samples=%0d", SAMPLES);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
