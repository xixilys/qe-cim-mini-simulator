# DAC QE FPGA DSE Manuscript

This directory contains the ACM/DAC-style LaTeX manuscript source for the QE-to-FPGA deployment DSE work.

Build:

```bash
./build.sh
```

Regenerate the fixture corpus, closed-loop summary, generated tables, and PDF:

```bash
rm -rf /tmp/qe_fpga_paper_pipeline && mkdir -p /tmp/qe_fpga_paper_pipeline
python3 ../../dse_v2/scripts/dse/build_qe_fpga_representative_workflow_corpus.py --out /tmp/qe_fpga_paper_pipeline/corpus
python3 ../../dse_v2/scripts/dse/run_qe_fpga_l3_feedback_closed_loop.py --out /tmp/qe_fpga_paper_pipeline/closed_loop --workflow-corpus /tmp/qe_fpga_paper_pipeline/corpus/workflow_corpus.json --workload-run-id paper_table_regen --candidate-budget 384 --promotion-budget 5 --implementation-package-budget 1 --l3-max-requests 3 --l3-holdout-count 2 --generic-sim ../../model/generic_sim_backend/build/generic_sim
cp /tmp/qe_fpga_paper_pipeline/closed_loop/paper_ready_experiment_summary.json generated/paper_ready_experiment_summary.json
python3 ../../dse_v2/scripts/dse/build_qe_fpga_paper_results_tables.py --summary generated/paper_ready_experiment_summary.json --out generated/results_tables.tex
latexmk -g -pdf -interaction=nonstopmode -halt-on-error main.tex
python3 ../../dse_v2/scripts/dse/build_qe_fpga_paper_artifact_index.py --summary /tmp/qe_fpga_paper_pipeline/closed_loop/paper_ready_experiment_summary.json --tables generated/results_tables.tex --pdf main.pdf --out generated/artifact_index.json --archive-summary generated/paper_ready_experiment_summary.json --table-command "python3 ../../dse_v2/scripts/dse/build_qe_fpga_paper_results_tables.py --summary generated/paper_ready_experiment_summary.json --out generated/results_tables.tex" --latex-command "latexmk -g -pdf -interaction=nonstopmode -halt-on-error main.tex"
```

The local `acmart.cls` and `ACM-Reference-Format.bst` are generated/copied from the CTAN `acmart` distribution so the paper can compile without relying on a system-wide ACM template install.

The manuscript is currently a research draft, not a final hardware-result paper.  The text records that HLS synthesis, Vivado implementation, and bitstream generation remain open gates.
