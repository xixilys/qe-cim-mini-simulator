# run1 release upstream closure status — 184-unit checkpoint

Status: **partial / fail-closed**. Do **not** claim `deliverable_complete=true`.

## Current binding

- Run root: `runs/run1_release_upstream_closure_20260527T055402Z`
- Source reviewed packet: `/home/xixilys/project/dft_accelerate/.omx/manual-five-slot/manual-five-slot-wave-20260527A/slot2-run2-target-source/run2_target_consumer_ppa_gate_20260527T051346Z/bound_bundle_onehundredeightyfour_units_full_gate_parser_packet_20260527T144610Z`
- Source target ledger: `/home/xixilys/project/dft_accelerate/.omx/manual-five-slot/manual-five-slot-wave-20260527A/slot2-run2-target-source/run2_target_consumer_ppa_gate_20260527T051346Z/target_gate_ledger_with_onehundredeightyfour_units_full_gate_probe`
- Latest complete reviewed packet unit count: `184`
- This turn advanced the published checkpoint from stale 152 status through verified 160, 168, and 176 bindings to the latest complete reviewed 184-unit parser/gate/ledger packet.
- Status writer repair: the prior 160 writer failed because it hard-coded a non-existent artifact label (`post-160 168 probe`); this checkpoint writes status/final from the 184-unit summary using the actual dynamic post-probe label.
- Newer-packet probe: `no_bindable_reviewed_onehundredninetytwo_or_larger_packet_found`; bindable reviewed 192-unit-or-larger packet refs: `0`.
- candidate24/192 state: active process line count `0`; latest raw probe file count `0`. This is **not** release evidence.

## What advanced in this checkpoint

- Bound **23 candidates × 8 kernels = 184 hard-gate units**.
- Bound **920 parsed stages**; `valid_parsed_result_count=920`.
- Gate adjudication has `stage_gate_passed_count=920`, `unit_gate_passed_count=184`, `blocked_unit_count=0`.
- Target split is **14 FPGA rows / 9 ASIC rows**.
- Replayed chain completed with rc 0 for release gate, PPA ranking, provenance audit, winner resolution, release-gate input matrix, comparator/selector, decision summary, and release package.

Bound candidates:

  - `cdse_002b847bbfdaef301054` (fpga)
  - `cdse_072a7bf296354553dc3f` (fpga)
  - `cdse_0757821a8279c8ad63f3` (fpga)
  - `cdse_0ad58d6a2195cc2a4b33` (asic)
  - `cdse_0e3b9b3b58c3290a7766` (fpga)
  - `cdse_108f0801aa81d206f12f` (fpga)
  - `cdse_112e732e0cd5352296c5` (fpga)
  - `cdse_11908f7d14c0e41c18e8` (asic)
  - `cdse_11f602a8042a8b453919` (asic)
  - `cdse_134444b0406e0e64c893` (asic)
  - `cdse_143fc75b3f5b91b69e13` (fpga)
  - `cdse_15454e1d757a9452299c` (fpga)
  - `cdse_17f78b34471e9cd0f5a4` (asic)
  - `cdse_1c0f6beb0cd7adc46805` (asic)
  - `cdse_200a0afa04d15c16392c` (fpga)
  - `cdse_2488cb2f62bf48e67b6f` (asic)
  - `cdse_24d2cfacbe7ebaf2990e` (fpga)
  - `cdse_24fc3a00482834f8d554` (fpga)
  - `cdse_25195f053934ab1f99d1` (fpga)
  - `cdse_25cd9741580fa38ee8ae` (asic)
  - `cdse_261554f7d93bb90981e1` (fpga)
  - `cdse_26f3acc4999686e2b816` (fpga)
  - `cdse_28483909daac6c356dc3` (asic)

## Current decision state

- Hardware release gate: `hardware_release_gate_passed_pending_deliverable_claim`, `hardware_completion_eligible=True`, `deliverable_complete=false`.
- PPA ranking: `trusted_hardware_ppa_ranking_tied` with `23` eligible candidates.
- FPGA winner resolution: blocked by `14` tied top candidates.
- ASIC winner resolution: blocked by `9` tied top candidates.
- Comparator: `blocked_no_deployment_recommendations`.
- Selector: `blocked_cross_target_requires_fpga_and_asic_recommendations`.
- Decision summary: `deployment_decision_summary_fail_closed`; `trusted_final_claim=false`.
- Release package: `partial`; blocker ids `['deployment_decision_summary_not_release_usable']`.
- Missing release-universe target rows: **80 FPGA** and **85 ASIC**.

## Verification evidence

Fresh verification in `/home/xixilys/project/dft_accelerate.omx-worktrees/launch-run1`:

- `python3 /tmp/run1_bind_onehundredeightyfour.py` → rc=0
- `/tmp/run1_onehundredeightyfour_replay.sh` → all rc zero=`true`
- `python3 /tmp/run1_onehundredeightyfour_sanity.py` → rc=0 (`72` checks / `0` failures)
- `python3 /tmp/run1_probe_after_184.py` → rc=0, status `no_bindable_reviewed_onehundredninetytwo_or_larger_packet_found`
- `python3 -m pytest -q dse_v2/tests/test_dft_hardware_ppa_ranking.py dse_v2/tests/test_dft_deployment_objective.py dse_v2/tests/test_dft_deployment_comparator.py dse_v2/tests/test_dft_deployment_selector.py dse_v2/tests/test_dft_deployment_decision_summary.py dse_v2/tests/test_dft_hardware_closure_release_gate_input_matrix.py dse_v2/tests/test_complete_dse_release_matrix.py dse_v2/tests/test_complete_dse_done_when_4_6_audit.py` → 57 passed in 175.81s (0:02:55)
- `python3 -m compileall -q dse_v2` → compileall_rc=0

Replay rc files:

- `onehundredeightyfour_unit_replay_comparator_selector.rc` = `0`
- `onehundredeightyfour_unit_replay_decision_summary.rc` = `0`
- `onehundredeightyfour_unit_replay_input_matrix.rc` = `0`
- `onehundredeightyfour_unit_replay_package.rc` = `0`
- `onehundredeightyfour_unit_replay_ppa_ranking.rc` = `0`
- `onehundredeightyfour_unit_replay_provenance_audit.rc` = `0`
- `onehundredeightyfour_unit_replay_release_gate.rc` = `0`
- `onehundredeightyfour_unit_replay_winner_resolution.rc` = `0`

## Fresh 192-unit heartbeat

- Complete 192-or-larger packet count: `0`.
- Incomplete 192-or-larger packet count: `0`.
- candidate24 active process line count after probe: `0`.
- Claim boundary: candidate24 raw execution / active process state is **not bindable** until parser/gate/ledger are all present; raw state cannot be used for recommendation or binding.

## Key hashes

- binding manifest: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/slot2_onehundredeightyfour_units_full_gate_packet_binding_manifest.json`; SHA256 `685cc284b34d1a4a5ee4a629f0f40409b53a07673007d9fcb58b6dc869912b99`
- 184-unit bind stdout: `runs/run1_release_upstream_closure_20260527T055402Z/onehundredeightyfour_unit_bind_stdout.json`; SHA256 `cd7d72f02405ca13e368b9d6933c9cfd39367478c05b709fc143a325c6a8cbaf`
- 184-unit sanity: `runs/run1_release_upstream_closure_20260527T055402Z/onehundredeightyfour_unit_sanity_stdout.json`; SHA256 `6695c8da45199a6871059b5f0b59fd36e20e902d8aec27c463bb6228cdde413a`
- parsed evidence manifest: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/dft_hardware_closure_parsed_evidence_manifest.json`; SHA256 `6bced15a50699ab8042cb65f0dc12762261579958a89f394bd85bcb060cf3785`
- gate adjudication: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/dft_hardware_closure_gate_adjudication.json`; SHA256 `78a362cc68588b05a4f15d81bcd5a2bcdd95a1b000f74636372850ccfbda7a57`
- release gate: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/dft_hardware_closure_release_gate.json`; SHA256 `a2022174b8df02f3a575d7cd97cd6d11851b7e65e810d1e4e32e20db6bab8019`
- PPA ranking: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/dft_hardware_ppa_ranking.json`; SHA256 `cb04e8f72b2b74f4e38244e0f9113282f4863557540c12148b1a41eb796118e5`
- provenance audit: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/dft_candidate_specific_ppa_provenance_audit.json`; SHA256 `b677aa79e27d39048d145fa203ea8882a2153360a3deb2fb1d8b67f6f9ae2869`
- winner resolution: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/dft_architecture_winner_resolution.json`; SHA256 `c18ffad4d1809bc722c470f1668d1ec70cba6dc9f610d6cfbd3eb8720f66d221`
- release-gate input matrix: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/dft_hardware_closure_release_gate_input_matrix.json`; SHA256 `16bc2c84d669bceeb98745ac7c1733ae47513edd2864490dbd1881ac6697aaba`
- deployment comparator: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/dft_deployment_comparator.json`; SHA256 `3afcd488d8c7ec1d43d33e21587f1d2979d0a769ac6827d695d3a87adbe8edff`
- deployment selector: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/dft_deployment_selector.json`; SHA256 `a06c8842a29c1553df29aadcd8a17e2501a07b6769d7b600136afec6b9779ef3`
- decision summary: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/dft_deployment_decision_summary.json`; SHA256 `120c5e5dbe4177067919a79157ad1a5cbab5e6e40852285bf27c2a16593d0fa2`
- release package: `runs/run1_release_upstream_closure_20260527T055402Z/release_package_bound_closure_summary/complete_dse_release_artifact_package.json`; SHA256 `61272dd04c5f564096066295b44562bd5100653d8607dcc973b5420f1d3ccf86`
- release package status: `runs/run1_release_upstream_closure_20260527T055402Z/release_package_bound_closure_summary/status.json`; SHA256 `9ffa4481c13966130d13766ac9af9d4c7c97910f7fb63cf3816d94ac1d21a3bd`
- release hash manifest: `runs/run1_release_upstream_closure_20260527T055402Z/release_package_bound_closure_summary/complete_dse_release_artifact_hash_manifest.json`; SHA256 `50b9e83784d2ee943e9156c4fa4fc15d768e3a12ce9fda8dbe9c8eb489a1aa1d`
- post-184 192 probe: `runs/run1_release_upstream_closure_20260527T055402Z/slot2_newer_packet_probe_after_184_unit_verification.json`; SHA256 `02af91122d26d17f4ccd15e38726b65e1f0c6645677a91dc9c69c43ccdaf672e`
- 184 pytest stdout: `runs/run1_release_upstream_closure_20260527T055402Z/onehundredeightyfour_unit_pytest_stdout.log`; SHA256 `bd171944f3f761eed7055d20cc2a89dbbbc95fb106272f1802cd156d9843d289`
- 184 compileall rc: `runs/run1_release_upstream_closure_20260527T055402Z/onehundredeightyfour_unit_compileall.rc`; SHA256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`
- 184 verification summary: `runs/run1_release_upstream_closure_20260527T055402Z/onehundredeightyfour_unit_verification_summary.json`; SHA256 `809db03f28c4512506ec728a991fee9aa5a7851f4922f6b1125a0425da6ad364`
