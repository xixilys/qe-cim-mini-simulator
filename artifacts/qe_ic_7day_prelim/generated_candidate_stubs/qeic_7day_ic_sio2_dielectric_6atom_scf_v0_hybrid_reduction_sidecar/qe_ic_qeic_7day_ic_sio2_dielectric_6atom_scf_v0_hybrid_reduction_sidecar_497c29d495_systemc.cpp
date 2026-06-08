// Generated non-claimable SystemC-style stub for qeic_7day_ic_sio2_dielectric_6atom_scf_v0_hybrid_reduction_sidecar
#include <systemc>

SC_MODULE(qeic_7day_ic_sio2_dielectric_6atom_scf_v0_hybrid_reduction_sidecar_systemc_stub) {
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

    SC_CTOR(qeic_7day_ic_sio2_dielectric_6atom_scf_v0_hybrid_reduction_sidecar_systemc_stub) {
        SC_METHOD(tick);
        sensitive << clk.pos();
    }
};
