# QE-IC Seven-Day Preliminary Resource Map

- Config source: `artifacts/qe_ic_real_opportunity_campaign_real_run/qe_ic_real_opportunity_campaign_real_gpu_config.json`
- GPU present: `True`
- GPU model: `NVIDIA GeForce RTX 3070`
- GPU memory MiB: `8192`
- QE tools: `{"epw.x": "/usr/bin/epw.x", "ph.x": "/usr/bin/ph.x", "pw.x": "/home/xixilys/project/qe_gpu_build/q-e/build_gpu_serial_nvhpc_cuda_no_gomp/bin/pw.x"}`
- QE runtime env keys: `['CUDA_VISIBLE_DEVICES', 'LD_LIBRARY_PATH']`
- EDA tools: `{"dc_shell": "ssh://ic-eda/home/synopsys/syn/O-2018.06-SP1/bin/dc_shell", "vcs": "ssh://ic-eda/home/synopsys/vcs-mx/O-2018.09-1/bin/vcs", "vivado": "ssh://ic-eda/home/Xilinx/Vivado/2019.1/bin/vivado"}`
- SystemC/generic_sim: `/home/xixilys/project/dft_accelerate/model/generic_sim_backend/build/generic_sim`
- gem5: `/home/xixilys/project/dft_accelerate/gem5_integration/gem5/build/X86/gem5.opt`
- Existing EDA smoke logs: `['artifacts/qe_ic_7day_prelim/eda_preflight/ic_eda_smoke_20260608T172944.log']`

## Current evidence gap

The prior real-run campaign has a measured GPU baseline but candidate-side evidence is generated proxy/stub only. This runner therefore generates three IC/EDA-relevant QE full-SCF benchmark inputs, revalidates the GPU baseline, and attempts remote VCS/Vivado-HLS/DC evidence while keeping final_claim_allowed=false unless hard claim gates pass.
