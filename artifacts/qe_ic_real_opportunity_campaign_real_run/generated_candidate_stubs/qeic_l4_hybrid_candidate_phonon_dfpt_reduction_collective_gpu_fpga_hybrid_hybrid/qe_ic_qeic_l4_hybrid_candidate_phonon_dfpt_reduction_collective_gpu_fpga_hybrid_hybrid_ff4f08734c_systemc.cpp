// Generated non-claimable SystemC-style stub for qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_reduction_sidecar_423b828955
#include <systemc>

SC_MODULE(qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_systemc_stub) {
    sc_core::sc_in<bool> clk;
    sc_core::sc_in<bool> rst_n;
    sc_core::sc_in<bool> valid_in;
    sc_core::sc_in<sc_dt::sc_uint<64>> in_word;
    sc_core::sc_out<bool> valid_out;
    sc_core::sc_out<sc_dt::sc_uint<64>> out_word;

    void tick() {
        if (!rst_n.read()) {
            valid_out.write(false);
            out_word.write(0);
        } else {
            valid_out.write(valid_in.read());
            out_word.write(in_word.read());
        }
    }

    SC_CTOR(qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_systemc_stub) {
        SC_METHOD(tick);
        sensitive << clk.pos();
    }
};
