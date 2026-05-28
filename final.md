# run1 release upstream closure final report — partial / fail-closed

Result: **partial / fail-closed**, advanced to the newest complete reviewed **184-unit** slot2 parser/gate/ledger packet.

## Delivered artifact state

- Run root: `runs/run1_release_upstream_closure_20260527T055402Z`
- Binding manifest: `runs/run1_release_upstream_closure_20260527T055402Z/replayed_decision_inputs/slot2_onehundredeightyfour_units_full_gate_packet_binding_manifest.json`
- Verification summary: `runs/run1_release_upstream_closure_20260527T055402Z/onehundredeightyfour_unit_verification_summary.json`
- Newer-packet probe: `runs/run1_release_upstream_closure_20260527T055402Z/slot2_newer_packet_probe_after_184_unit_verification.json`
- Release package status: `runs/run1_release_upstream_closure_20260527T055402Z/release_package_bound_closure_summary/status.json`

## Evidence counts

| Item | Value |
| --- | ---: |
| Candidate rows bound | 23 |
| Kernel rows per candidate | 8 |
| Hard-gate units | 184 |
| Parsed stages | 920 |
| Passed stages | 920 |
| Passed units | 184 |
| FPGA ranking rows | 14 |
| ASIC ranking rows | 9 |
| Missing FPGA release target rows | 80 |
| Missing ASIC release target rows | 85 |

## Verification

- 184-unit sanity: `72` checks, `0` failures.
- Replay chain: all eight `onehundredeightyfour_unit_replay_*.rc` files are `0`.
- Targeted pytest: `57 passed in 175.81s (0:02:55)`.
- Compileall: `python3 -m compileall -q dse_v2` exited `0`.
- Newer packet probe: no bindable 192-unit-or-larger reviewed packet at probe time; no candidate24 active/raw process was present in the probe, and no candidate24 packet is release evidence.

## Why this is not release-complete

- PPA metrics are still tied: FPGA has 14 top candidates and ASIC has 9 top candidates.
- Comparator has no deployment recommendation.
- Selector is blocked because cross-target comparison lacks valid FPGA and ASIC recommendations.
- Decision summary is fail-closed; `trusted_final_claim=false` and `deliverable_complete=false`.
- Release package remains `partial` with blocker `deployment_decision_summary_not_release_usable`.
- No complete reviewed 192-unit parser/gate/ledger packet is available for candidate24 binding at probe time; absent, raw, or incomplete candidate24 evidence remains non-release evidence.

## Hash anchors

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

## Next executable step

Continue when a complete reviewed 192-unit-or-larger parser packet plus matching target evidence ledger JSON/status/validation appears, or when tie-breaking physical evidence closes unique FPGA/ASIC recommendations. Raw candidate24 probes and incomplete/absent packet directories remain non-release evidence.
