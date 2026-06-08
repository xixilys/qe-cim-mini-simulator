module tb_qeic_real_integrated_streaming_pipeline_sidecar_rtl;
    localparam integer HPSI_N = 96;
    localparam integer SUM_GRID = 32;
    localparam integer SUM_BANDS = 4;
    localparam integer SUM_SAMPLES = 128;
    localparam integer AXPY_N = 64;
    localparam integer TOTAL_SAMPLES = 288;
    localparam integer OUTPUT_SAMPLES = 192;
    localparam integer PIPELINE_LATENCY = 4;
    localparam integer EXPECTED_LATENCY = 291;
    localparam integer HPSI_COMPONENT_CYCLES = 99;
    localparam integer SUM_BAND_COMPONENT_CYCLES = 131;
    localparam integer AXPY_COMPONENT_CYCLES = 67;
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 48;
    localparam [1:0] MODE_HPSI = 2'd0;
    localparam [1:0] MODE_SUM_BAND = 2'd1;
    localparam [1:0] MODE_AXPY = 2'd2;
    localparam signed [WIDTH-1:0] ALPHA_RE = 18'sd192;
    localparam signed [WIDTH-1:0] ALPHA_IM = -18'sd32;
    reg clk;
    reg reset_n;
    reg start;
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
    wire signed [ACC_WIDTH-1:0] out_re;
    wire signed [ACC_WIDTH-1:0] out_im;
    wire signed [ACC_WIDTH-1:0] rho_out;
    wire valid;
    wire done;

    reg signed [WIDTH-1:0] hpsi_re [0:HPSI_N-1];
    reg signed [WIDTH-1:0] hpsi_im [0:HPSI_N-1];
    reg signed [WIDTH-1:0] hpsi_vloc [0:HPSI_N-1];
    reg signed [ACC_WIDTH-1:0] hpsi_expected_re [0:HPSI_N-1];
    reg signed [ACC_WIDTH-1:0] hpsi_expected_im [0:HPSI_N-1];
    reg signed [WIDTH-1:0] sum_re [0:SUM_SAMPLES-1];
    reg signed [WIDTH-1:0] sum_im [0:SUM_SAMPLES-1];
    reg signed [WIDTH-1:0] sum_weight [0:SUM_BANDS-1];
    reg signed [ACC_WIDTH-1:0] sum_expected [0:SUM_GRID-1];
    reg signed [WIDTH-1:0] axpy_x_re [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_x_im [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_y_re [0:AXPY_N-1];
    reg signed [WIDTH-1:0] axpy_y_im [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] axpy_expected_re [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] axpy_expected_im [0:AXPY_N-1];
    reg signed [ACC_WIDTH-1:0] expected_re [0:OUTPUT_SAMPLES-1];
    reg signed [ACC_WIDTH-1:0] expected_im [0:OUTPUT_SAMPLES-1];
    reg signed [ACC_WIDTH-1:0] expected_rho [0:OUTPUT_SAMPLES-1];
    reg expected_is_sum [0:OUTPUT_SAMPLES-1];
    reg signed [ACC_WIDTH-1:0] lap_re;
    reg signed [ACC_WIDTH-1:0] lap_im;
    reg signed [ACC_WIDTH-1:0] acc;
    reg signed [(2*WIDTH)-1:0] re_sq;
    reg signed [(2*WIDTH)-1:0] im_sq;
    reg signed [ACC_WIDTH-1:0] abs_sq;
    integer i;
    integer g;
    integer b;
    integer left;
    integer right;
    integer idx;
    integer output_idx;
    integer expected_idx;
    integer latency_cycles;

    qeic_real_integrated_streaming_pipeline_sidecar_rtl #(
        .TOTAL_SAMPLES(TOTAL_SAMPLES),
        .WIDTH(WIDTH),
        .ACC_WIDTH(ACC_WIDTH),
        .ALPHA_RE(ALPHA_RE),
        .ALPHA_IM(ALPHA_IM)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
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
        .done(done)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    task automatic check_output;
        begin
            if (valid === 1'b1) begin
                if (output_idx >= OUTPUT_SAMPLES) begin
                    $display("DSE_REAL_RTL_FAIL streaming extra_valid output_idx=%0d", output_idx);
                    $finish(1);
                end
                if (expected_is_sum[output_idx]) begin
                    if (rho_out !== expected_rho[output_idx]) begin
                        $display("DSE_REAL_RTL_FAIL streaming sum output=%0d expected=%0d got=%0d", output_idx, expected_rho[output_idx], rho_out);
                        $finish(1);
                    end
                end else if (out_re !== expected_re[output_idx] || out_im !== expected_im[output_idx]) begin
                    $display("DSE_REAL_RTL_FAIL streaming vector output=%0d expected=%0d,%0d got=%0d,%0d", output_idx, expected_re[output_idx], expected_im[output_idx], out_re, out_im);
                    $finish(1);
                end
                output_idx = output_idx + 1;
            end
        end
    endtask

    task automatic tick_and_check;
        begin
            @(posedge clk);
            #1;
            latency_cycles = latency_cycles + 1;
            check_output();
        end
    endtask

    initial begin
        reset_n = 1'b0;
        start = 1'b0;
        sample_valid = 1'b0;
        mode = MODE_HPSI;
        band_first = 1'b0;
        band_last = 1'b0;
        a_re = 0;
        a_im = 0;
        b_re = 0;
        b_im = 0;
        c_re = 0;
        c_im = 0;
        weight = 0;
        y_re = 0;
        y_im = 0;
        output_idx = 0;
        expected_idx = 0;
        latency_cycles = 0;

        for (g = 0; g < HPSI_N; g = g + 1) begin
            hpsi_re[g] = 18'sd64 + g * 18'sd3;
            hpsi_im[g] = -18'sd51 - g * 18'sd2;
            hpsi_vloc[g] = 18'sd128 + ((g * 17) & 31);
        end
        for (g = 0; g < HPSI_N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == HPSI_N - 1) ? HPSI_N - 1 : g + 1;
            lap_re = hpsi_re[left] - (hpsi_re[g] <<< 1) + hpsi_re[right];
            lap_im = hpsi_im[left] - (hpsi_im[g] <<< 1) + hpsi_im[right];
            hpsi_expected_re[g] = -(lap_re >>> 1) + ((hpsi_vloc[g] * hpsi_re[g]) >>> 8);
            hpsi_expected_im[g] = -(lap_im >>> 1) + ((hpsi_vloc[g] * hpsi_im[g]) >>> 8);
            expected_re[expected_idx] = hpsi_expected_re[g];
            expected_im[expected_idx] = hpsi_expected_im[g];
            expected_rho[expected_idx] = 0;
            expected_is_sum[expected_idx] = 1'b0;
            expected_idx = expected_idx + 1;
        end
        for (b = 0; b < SUM_BANDS; b = b + 1) begin
            sum_weight[b] = 18'sd64 + b * 18'sd11;
        end
        for (g = 0; g < SUM_GRID; g = g + 1) begin
            sum_expected[g] = 0;
        end
        for (b = 0; b < SUM_BANDS; b = b + 1) begin
            for (g = 0; g < SUM_GRID; g = g + 1) begin
                idx = b * SUM_GRID + g;
                sum_re[idx] = 18'sd32 + idx * 18'sd2 + (g & 3);
                sum_im[idx] = -18'sd21 - idx;
            end
        end
        for (g = 0; g < SUM_GRID; g = g + 1) begin
            acc = 0;
            for (b = 0; b < SUM_BANDS; b = b + 1) begin
                idx = b * SUM_GRID + g;
                re_sq = sum_re[idx] * sum_re[idx];
                im_sq = sum_im[idx] * sum_im[idx];
                abs_sq = re_sq + im_sq;
                acc = acc + ((abs_sq * sum_weight[b]) >>> WIDTH);
            end
            sum_expected[g] = acc;
            expected_re[expected_idx] = 0;
            expected_im[expected_idx] = 0;
            expected_rho[expected_idx] = acc;
            expected_is_sum[expected_idx] = 1'b1;
            expected_idx = expected_idx + 1;
        end
        for (i = 0; i < AXPY_N; i = i + 1) begin
            axpy_x_re[i] = 18'sd16 + i * 18'sd3;
            axpy_x_im[i] = -18'sd11 - i * 18'sd2;
            axpy_y_re[i] = 18'sd7 + (i & 7);
            axpy_y_im[i] = -18'sd5 - (i & 5);
            axpy_expected_re[i] = (axpy_y_re[i] <<< 8) + (ALPHA_RE * axpy_x_re[i]) - (ALPHA_IM * axpy_x_im[i]);
            axpy_expected_im[i] = (axpy_y_im[i] <<< 8) + (ALPHA_RE * axpy_x_im[i]) + (ALPHA_IM * axpy_x_re[i]);
            expected_re[expected_idx] = axpy_expected_re[i];
            expected_im[expected_idx] = axpy_expected_im[i];
            expected_rho[expected_idx] = 0;
            expected_is_sum[expected_idx] = 1'b0;
            expected_idx = expected_idx + 1;
        end
        if (expected_idx != OUTPUT_SAMPLES) begin
            $display("DSE_REAL_RTL_FAIL streaming expected_idx=%0d output_samples=%0d", expected_idx, OUTPUT_SAMPLES);
            $finish(1);
        end

        repeat (3) @(posedge clk);
        reset_n = 1'b1;
        @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;

        for (g = 0; g < HPSI_N; g = g + 1) begin
            left = (g == 0) ? 0 : g - 1;
            right = (g == HPSI_N - 1) ? HPSI_N - 1 : g + 1;
            @(negedge clk);
            mode = MODE_HPSI;
            a_re = hpsi_re[left];
            a_im = hpsi_im[left];
            b_re = hpsi_re[g];
            b_im = hpsi_im[g];
            c_re = hpsi_re[right];
            c_im = hpsi_im[right];
            weight = hpsi_vloc[g];
            band_first = 1'b0;
            band_last = 1'b0;
            y_re = 0;
            y_im = 0;
            sample_valid = 1'b1;
            tick_and_check();
        end

        for (g = 0; g < SUM_GRID; g = g + 1) begin
            for (b = 0; b < SUM_BANDS; b = b + 1) begin
                @(negedge clk);
                idx = b * SUM_GRID + g;
                mode = MODE_SUM_BAND;
                a_re = 0;
                a_im = 0;
                b_re = sum_re[idx];
                b_im = sum_im[idx];
                c_re = 0;
                c_im = 0;
                weight = sum_weight[b];
                y_re = 0;
                y_im = 0;
                band_first = (b == 0);
                band_last = (b == SUM_BANDS - 1);
                sample_valid = 1'b1;
                tick_and_check();
            end
        end

        for (i = 0; i < AXPY_N; i = i + 1) begin
            @(negedge clk);
            mode = MODE_AXPY;
            a_re = axpy_x_re[i];
            a_im = axpy_x_im[i];
            b_re = 0;
            b_im = 0;
            c_re = 0;
            c_im = 0;
            weight = 0;
            y_re = axpy_y_re[i];
            y_im = axpy_y_im[i];
            band_first = 1'b0;
            band_last = 1'b0;
            sample_valid = 1'b1;
            tick_and_check();
        end

        @(negedge clk);
        sample_valid = 1'b0;
        band_first = 1'b0;
        band_last = 1'b0;
        while (done !== 1'b1) begin
            tick_and_check();
        end
        if (output_idx != OUTPUT_SAMPLES || latency_cycles != EXPECTED_LATENCY) begin
            $display("DSE_REAL_RTL_FAIL streaming done=%0d outputs=%0d expected_outputs=%0d latency=%0d expected_latency=%0d", done, output_idx, OUTPUT_SAMPLES, latency_cycles, EXPECTED_LATENCY);
            $finish(1);
        end
        $display("DSE_REAL_RTL_COMPONENT hpsi samples=%0d cycles=%0d", HPSI_N, HPSI_COMPONENT_CYCLES);
        $display("DSE_REAL_RTL_COMPONENT sum_band samples=%0d cycles=%0d", SUM_SAMPLES, SUM_BAND_COMPONENT_CYCLES);
        $display("DSE_REAL_RTL_COMPONENT axpy samples=%0d cycles=%0d", AXPY_N, AXPY_COMPONENT_CYCLES);
        $display("DSE_REAL_RTL_PASS qeic_real_integrated_streaming_pipeline_sidecar_rtl samples=%0d", TOTAL_SAMPLES);
        $display("DSE_REAL_RTL_LATENCY_CYCLES %0d", latency_cycles);
        $finish(0);
    end
endmodule
