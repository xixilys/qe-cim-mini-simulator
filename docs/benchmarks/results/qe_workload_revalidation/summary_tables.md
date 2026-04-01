# QE Workload 复核数据摘要

## 1. Case Matrix

| case | atoms | functional | pseudo types | input diag | exit | dominant solver | generalized ratio | top (n,m) |
| --- | ---: | --- | --- | --- | ---: | --- | ---: | --- |
| h2_tiny | 2 | pbe | USPP | default | 0 | davidson | 77.4% | (4,2)x15, (2,2)x8, (3,2)x8 |
| si8_pbe_uspp | 8 | pbe | USPP | default | 0 | davidson | 86.5% | (32,16)x17, (16,16)x7, (19,16)x5 |
| si8_pbe_nc | 8 | pbe | NC | default | 0 | davidson | 89.4% | (32,16)x19, (16,16)x8, (28,16)x5 |
| si8_pbe0_uspp | 8 | pbe0 | USPP | cg | 0 | cg | 25.0% | (16,16)x3, (32,16)x1 |
| graphene_pbe_paw | 2 | pbe | PAW | default | 0 | davidson | 76.8% | (8,4)x125, (4,4)x60, (6,4)x39 |
| graphene_pbe_uspp | 2 | pbe | USPP | default | 0 | davidson | 76.7% | (8,4)x122, (4,4)x60, (6,4)x35 |
| benzene | 12 | pbe | NC | default | 82 | davidson | 92.3% | (48,24)x7, (24,24)x3, (38,24)x2 |
| bn32_pbe_uspp | 32 | pbe | USPP | default | 0 | davidson | 76.2% | (128,64)x10, (64,64)x5, (80,64)x2 |
| bn32_pbe0_uspp | 32 | pbe0 | USPP | cg | 0 | cg | 33.3% | (64,64)x2, (128,64)x1 |

## 2. Top-Level Timing Shares

| case | c_bands | sum_band | v_of_rho | mix_rho | other |
| --- | ---: | ---: | ---: | ---: | ---: |
| h2_tiny | 50.0% | 0.0% | 50.0% | 0.0% | 0.0% |
| si8_pbe_uspp | 50.0% | 23.4% | 6.4% | 1.1% | 19.1% |
| si8_pbe_nc | 76.7% | 8.1% | 14.0% | 1.2% | 0.0% |
| si8_pbe0_uspp | 63.4% | 16.9% | 5.6% | 0.0% | 14.1% |
| graphene_pbe_paw | 45.0% | 10.0% | 10.0% | 0.0% | 35.0% |
| graphene_pbe_uspp | 64.3% | 14.3% | 14.3% | 0.0% | 7.1% |
| benzene | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| bn32_pbe_uspp | 77.7% | 12.6% | 5.8% | 0.0% | 3.9% |
| bn32_pbe0_uspp | 95.2% | 2.8% | 1.2% | 0.0% | 0.8% |

## 3. Solver / *egterg Breakdown

| case | c_bands->*egterg | c_bands->cg | *egterg->h_psi | *egterg->diag | h_psi calls | s_psi calls | max nbase |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| h2_tiny | 100.0% | 0.0% | 100.0% | 0.0% | 31 | 31 | 4 |
| si8_pbe_uspp | 97.6% | 0.0% | 80.0% | 2.9% | 52 | 52 | 32 |
| si8_pbe_nc | 98.5% | 0.0% | 98.1% | 1.9% | 67 | 0 | 32 |
| si8_pbe0_uspp | 0.0% | 87.5% | 0.0% | 0.0% | 197 | 391 | 0 |
| graphene_pbe_paw | 96.3% | 0.0% | 84.2% | 5.3% | 259 | 259 | 8 |
| graphene_pbe_uspp | 96.3% | 0.0% | 83.3% | 5.6% | 257 | 257 | 8 |
| benzene | 0.0% | 0.0% | 0.0% | 0.0% | 26 | 0 | 48 |
| bn32_pbe_uspp | 98.7% | 0.0% | 81.3% | 9.3% | 21 | 21 | 128 |
| bn32_pbe0_uspp | 0.0% | 93.5% | 0.0% | 0.0% | 579 | 1156 | 0 |

## 4. Traceability

### h2_tiny
input: [input](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/h2_tiny_gamma.in)  command: [command](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/h2_tiny/command.sh)  stdout: [stdout](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/h2_tiny/stdout.out)  subspace: [subspace](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/h2_tiny/subspace_trace.csv)  hpsi: [hpsi](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/h2_tiny/hpsi_trace.csv)  bandsolver: [bandsolver](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/h2_tiny/bandsolver_trace.csv)

### si8_pbe_uspp
input: [input](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/si8_pbe_uspp.in)  command: [command](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe_uspp/command.sh)  stdout: [stdout](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe_uspp/stdout.out)  subspace: [subspace](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe_uspp/subspace_trace.csv)  hpsi: [hpsi](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe_uspp/hpsi_trace.csv)  bandsolver: [bandsolver](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe_uspp/bandsolver_trace.csv)

### si8_pbe_nc
input: [input](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/si8_pbe_nc.in)  command: [command](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe_nc/command.sh)  stdout: [stdout](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe_nc/stdout.out)  subspace: [subspace](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe_nc/subspace_trace.csv)  hpsi: [hpsi](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe_nc/hpsi_trace.csv)  bandsolver: [bandsolver](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe_nc/bandsolver_trace.csv)

### si8_pbe0_uspp
input: [input](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/si8_pbe0_uspp_cg.in)  command: [command](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe0_uspp/command.sh)  stdout: [stdout](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe0_uspp/stdout.out)  subspace: [subspace](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe0_uspp/subspace_trace.csv)  hpsi: [hpsi](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe0_uspp/hpsi_trace.csv)  bandsolver: [bandsolver](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/si8_pbe0_uspp/bandsolver_trace.csv)

### graphene_pbe_paw
input: [input](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/graphene_pbe_paw_scf.in)  command: [command](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_paw/command.sh)  stdout: [stdout](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_paw/stdout.out)  subspace: [subspace](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_paw/subspace_trace.csv)  hpsi: [hpsi](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_paw/hpsi_trace.csv)  bandsolver: [bandsolver](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_paw/bandsolver_trace.csv)

### graphene_pbe_uspp
input: [input](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/graphene_pbe_uspp_scf.in)  command: [command](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_uspp/command.sh)  stdout: [stdout](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_uspp/stdout.out)  subspace: [subspace](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_uspp/subspace_trace.csv)  hpsi: [hpsi](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_uspp/hpsi_trace.csv)  bandsolver: [bandsolver](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_uspp/bandsolver_trace.csv)

### benzene
input: [input](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/benzene_workload_small.in)  command: [command](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/benzene/command.sh)  stdout: [stdout](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/benzene/stdout.out)  subspace: [subspace](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/benzene/subspace_trace.csv)  hpsi: [hpsi](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/benzene/hpsi_trace.csv)  bandsolver: [bandsolver](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/benzene/bandsolver_trace.csv)

### bn32_pbe_uspp
input: [input](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/bn32_pbe_uspp.in)  command: [command](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/bn32_pbe_uspp/command.sh)  stdout: [stdout](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/bn32_pbe_uspp/stdout.out)  subspace: [subspace](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/bn32_pbe_uspp/subspace_trace.csv)  hpsi: [hpsi](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/bn32_pbe_uspp/hpsi_trace.csv)  bandsolver: [bandsolver](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/bn32_pbe_uspp/bandsolver_trace.csv)

### bn32_pbe0_uspp
input: [input](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/bn32_pbe0_uspp_cg.in)  command: [command](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/bn32_pbe0_uspp/command.sh)  stdout: [stdout](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/bn32_pbe0_uspp/stdout.out)  subspace: [subspace](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/bn32_pbe0_uspp/subspace_trace.csv)  hpsi: [hpsi](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/bn32_pbe0_uspp/hpsi_trace.csv)  bandsolver: [bandsolver](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/bn32_pbe0_uspp/bandsolver_trace.csv)

## 5. Parser Validation

| reference | electrons | c_bands | *egterg | h_psi | solver rows |
| --- | --- | --- | --- | --- | ---: |
| graphene_relax_old | yes | yes | yes | yes | 6 |
| fe_scf_old | yes | yes | yes | yes | 17 |
| h2_rerun | yes | yes | yes | yes | 8 |
