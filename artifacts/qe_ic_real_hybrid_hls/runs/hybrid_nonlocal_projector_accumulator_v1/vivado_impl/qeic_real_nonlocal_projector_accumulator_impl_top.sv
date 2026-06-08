module qeic_real_nonlocal_projector_accumulator_impl_top (
    input wire clk,
    input wire reset_n,
    input wire start,
    output wire done,
    output wire valid
);
    localparam integer WIDTH = 18;
    localparam integer ACC_WIDTH = 56;
    localparam integer NGRID = 16;
    localparam integer NBANDS = 4;
    localparam integer NPROJ = 4;
    localparam integer SAMPLES = 256;
    reg sample_valid;
    reg sample_first;
    reg sample_last;
    reg signed [WIDTH-1:0] beta_re;
    reg signed [WIDTH-1:0] beta_im;
    reg signed [WIDTH-1:0] psi_re;
    reg signed [WIDTH-1:0] psi_im;
    reg [15:0] sample_idx;
    wire signed [ACC_WIDTH-1:0] proj_re;
    wire signed [ACC_WIDTH-1:0] proj_im;

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

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            sample_idx <= 0;
            sample_valid <= 1'b0;
            sample_first <= 1'b0;
            sample_last <= 1'b0;
            beta_re <= 0;
            beta_im <= 0;
            psi_re <= 0;
            psi_im <= 0;
        end else begin
            if (start) begin
                sample_idx <= 0;
                sample_valid <= 1'b1;
            end else if (sample_valid) begin
                if (sample_idx == SAMPLES - 1) begin
                    sample_valid <= 1'b0;
                end
                sample_idx <= sample_idx + 1'b1;
            end
            sample_first <= sample_valid && ((sample_idx % NGRID) == 0);
            sample_last <= sample_valid && ((sample_idx % NGRID) == NGRID - 1);
            beta_re <= 18'sd9 + {2'b0, sample_idx[7:0]};
            beta_im <= -18'sd7 - {3'b0, sample_idx[6:0]};
            psi_re <= 18'sd21 + {3'b0, sample_idx[6:0]};
            psi_im <= -18'sd13 - {4'b0, sample_idx[5:0]};
        end
    end
endmodule
