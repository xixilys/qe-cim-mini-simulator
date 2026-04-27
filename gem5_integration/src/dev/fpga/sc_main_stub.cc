// Stub sc_main for gem5 SystemC integration
// gem5's SystemC support uses Python to drive simulation,
// but still requires sc_main symbol to be defined.

extern "C" {
int sc_main(int argc, char *argv[]) {
    // This should never be called when using Python-driven simulation
    return 0;
}
}
