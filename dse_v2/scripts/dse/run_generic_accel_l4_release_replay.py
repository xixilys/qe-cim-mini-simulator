#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(os.environ.get('REPO_ROOT', Path(__file__).resolve().parents[3])).resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.backends.gem5_systemc_adapter import build_generic_accel_command_descriptor, build_raw_l4_interface_observations
from dse_v2.codesign.l4_closure import canonicalize_l4_interface_metrics
from dse_v2.evidence.full_flow import build_gem5_l4_proof

RUNROOT = Path(os.environ.get('RUNROOT', Path.cwd() / 'runs/generic_accel_l4_release_replay'))
GEM5 = Path(os.environ.get('GEM5_BIN', '/mnt/f/phd/year_2/project/dft_accelerate/gem5_integration/gem5/build/X86/gem5.opt'))
CONFIG = REPO_ROOT / 'gem5_integration/configs/generic_accel_l4_test.py'
DRIVER = REPO_ROOT / 'gem5_integration/test_programs/generic_accel/generic_accel_l4_driver'
GENERIC_SIM = REPO_ROOT / 'model/generic_sim_backend/build/generic_sim'
LOG = RUNROOT / 'logs/expanded_gem5_l4_matrix.log'


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run_cmd(cmd, cwd=REPO_ROOT, timeout=240):
    start = time.time()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as log:
        log.write(f"\n===== {now()} =====\ncmd={' '.join(map(str, cmd))}\ncwd={cwd}\n")
    try:
        cp = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout)
        stdout, stderr, rc = cp.stdout or '', cp.stderr or '', cp.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b'').decode('utf-8', 'replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        stderr = (exc.stderr or b'').decode('utf-8', 'replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        stderr += f"\nTIMEOUT after {timeout}s"
        rc = 124
    with LOG.open('a', encoding='utf-8') as log:
        log.write((stdout + stderr)[-12000:] + f"\nexit_code={rc}\nelapsed_s={time.time()-start:.3f}\n")
    return rc, stdout, stderr, round(time.time() - start, 3)


def ensure_prereqs():
    if not DRIVER.exists():
        rc, _, _, _ = run_cmd(['gcc','-std=c99','-O2','-Wall','-Wextra','-static','-I',str(REPO_ROOT),str(DRIVER.with_suffix('.c')),'-o',str(DRIVER)], timeout=120)
        if rc != 0:
            raise SystemExit(f'failed to build driver rc={rc}')
    if not GENERIC_SIM.exists():
        rc, _, _, _ = run_cmd(['cmake','-S',str(REPO_ROOT/'model/generic_sim_backend'),'-B',str(REPO_ROOT/'model/generic_sim_backend/build')], timeout=300)
        if rc == 0:
            rc, _, _, _ = run_cmd(['cmake','--build',str(REPO_ROOT/'model/generic_sim_backend/build'),'-j2'], timeout=900)
        if rc != 0:
            raise SystemExit(f'failed to build generic_sim rc={rc}')


def request_payload(case_id: str, candidate_id: str, nodes: dict, edges: list, mapping: dict, accels: list, extra: dict | None = None) -> dict:
    payload = {
        'schema_version': 'dse.simulation_request.v1',
        'run_id': f'{candidate_id}__{case_id}',
        'mode': 'gem5_cosim',
        'workload_case_id': case_id,
        'candidate_identity': {
            'candidate_id': candidate_id,
            'algorithm_id': 'slot4_expanded_l4_probe',
            'architecture_id': 'generic_accel_l4_expanded',
            'mapping_id': f'map_{candidate_id}_{case_id}',
            'compile_schedule_id': f'compile_{candidate_id}_{case_id}',
            'runtime_schedule_id': f'runtime_{candidate_id}_{case_id}',
        },
        'compile_schedule': {'schedule_id': f'compile_{candidate_id}_{case_id}', 'source': 'slot4_expanded_probe'},
        'runtime_schedule': {'schedule_id': f'runtime_{candidate_id}_{case_id}', 'policy': 'static_topological'},
        'sidecar_dispatch': {'mode': 'in_gem5_uarch', 'model': 'none'},
        'extension_payload': {'adapter_metadata': {'source_kind': 'slot4_expanded_probe', 'claim_scope': 'vertical_slice_only'}},
        'workload': {'nodes': nodes, 'edges': edges},
        'mapping': mapping,
        'architecture': {
            'host': {'clock_mhz': 3000, 'memory_bw_gbps': 100, 'cores': 1},
            'interconnect': {'bandwidth_gbps': 64, 'latency_ns': 800},
            'accelerators': accels,
        },
    }
    if extra:
        payload.update(extra)
    return payload

COMMON_ACCEL_FPGA = {'accel_id':'generic_accel_0','accel_type':'fpga','clock_mhz':250,'local_memory_kb':2048,'power':{'static_w':5,'max_w':25},'capabilities':{'fft':{'peak_gops':64,'efficiency':0.65},'projector':{'peak_gops':48,'efficiency':0.60},'reduction':{'peak_gops':20,'efficiency':0.55},'dma':{'peak_gops':1,'efficiency':1.0}}}
COMMON_ACCEL_ASIC = {'accel_id':'generic_accel_asic0','accel_type':'cim','clock_mhz':700,'local_memory_kb':4096,'power':{'static_w':2,'max_w':12},'capabilities':{'projector':{'peak_gops':128,'efficiency':0.70},'reduction':{'peak_gops':48,'efficiency':0.65},'fft':{'peak_gops':96,'efficiency':0.50}}}
BIG_TEXT = 'slot4_payload_' * 4096
CASES = [
    {
        'row_id': 'valid_fft_single_completion', 'expected': 'passed', 'repeat': 1,
        'candidate_id': 'slot4_fpga_fft_candidate', 'workload_case_id': 'qe_scf_fft_smoke',
        'request': request_payload(
            'qe_scf_fft_smoke', 'slot4_fpga_fft_candidate',
            {'load_wavefunction': {'op_type':'dma','estimated_flops':0,'estimated_memory_bytes':4096}, 'fft_kernel': {'op_type':'fft','estimated_flops':2_000_000,'estimated_memory_bytes':16384}},
            [{'source':'load_wavefunction','target':'fft_kernel','tensor_name':'psi','size_bytes':4096}],
            {'load_wavefunction':'host','fft_kernel':'generic_accel_0'}, [COMMON_ACCEL_FPGA]),
    },
    {
        'row_id': 'valid_projector_asic_payload', 'expected': 'passed', 'repeat': 1,
        'candidate_id': 'slot4_asic_projector_candidate', 'workload_case_id': 'qe_relax_projector_smoke',
        'request': request_payload(
            'qe_relax_projector_smoke', 'slot4_asic_projector_candidate',
            {'beta_load': {'op_type':'dma','estimated_flops':0,'estimated_memory_bytes':8192}, 'projector': {'op_type':'projector','estimated_flops':5_000_000,'estimated_memory_bytes':32768}, 'reduction': {'op_type':'reduction','estimated_flops':500_000,'estimated_memory_bytes':8192}},
            [{'source':'beta_load','target':'projector','tensor_name':'beta','size_bytes':8192}, {'source':'projector','target':'reduction','tensor_name':'proj','size_bytes':4096}],
            {'beta_load':'host','projector':'generic_accel_asic0','reduction':'generic_accel_asic0'}, [COMMON_ACCEL_ASIC],
            {'extension_payload': {'adapter_metadata': {'source_kind':'slot4_expanded_probe','claim_scope':'vertical_slice_only'}, 'large_payload': BIG_TEXT}}),
    },
    {
        'row_id': 'valid_multi_completion_repeat', 'expected': 'passed', 'repeat': 2,
        'candidate_id': 'slot4_fpga_runtime_repeat_candidate', 'workload_case_id': 'qe_bands_dma_repeat_smoke',
        'request': request_payload(
            'qe_bands_dma_repeat_smoke', 'slot4_fpga_runtime_repeat_candidate',
            {'stage_a': {'op_type':'fft','estimated_flops':1_000_000,'estimated_memory_bytes':12000}, 'stage_b': {'op_type':'projector','estimated_flops':2_500_000,'estimated_memory_bytes':20000}, 'stage_c': {'op_type':'reduction','estimated_flops':250_000,'estimated_memory_bytes':4000}},
            [{'source':'stage_a','target':'stage_b','tensor_name':'a2b','size_bytes':12000}, {'source':'stage_b','target':'stage_c','tensor_name':'b2c','size_bytes':4000}],
            {'stage_a':'generic_accel_0','stage_b':'generic_accel_0','stage_c':'host'}, [COMMON_ACCEL_FPGA]),
    },
    {
        'row_id': 'expected_bad_descriptor_validation', 'expected': 'descriptor_error', 'repeat': 1,
        'candidate_id': 'slot4_bad_descriptor_candidate', 'workload_case_id': 'descriptor_validation_bad_magic',
        'request': {'schema_version':'dse.simulation_request.v1','run_id':'bad_descriptor_unused','mode':'gem5_cosim','workload':{'nodes':{'unused':{'op_type':'fft','estimated_flops':1,'estimated_memory_bytes':1}},'edges':[]},'mapping':{'unused':'host'},'architecture':{'host':{'clock_mhz':3000},'accelerators':[]}},
    },
]

BAD_DRIVER_C = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define MMIO_BASE 0xF0000000UL
#define WORK_BASE 0x08000000UL
#define REG_CMD_DOORBELL 0x1000
#define REG_CMD_DESC_ADDR_LO 0x1004
#define REG_CMD_DESC_ADDR_HI 0x1008
#define REG_CMD_DESC_SIZE 0x100C
#define REG_COMP_STATUS 0x3000
#define REG_COMP_DESC_ADDR_LO 0x3004
#define REG_COMP_DESC_ADDR_HI 0x3008
#define REG_COMP_ERROR_CODE 0x300C
#define COMPLETION_OFFSET 0x110000
#define RESULT_OFFSET 0x120000
#define POLL_LIMIT 100000000
typedef struct __attribute__((packed)) { uint32_t magic, version, type, flags; uint64_t request_addr, result_addr, workspace_addr, workspace_size; uint64_t ext_addr, ext_bytes, cand_addr, cand_bytes, comp_addr, comp_bytes, runtime_addr, runtime_bytes, sidecar_addr, sidecar_bytes; } desc_t;
typedef struct __attribute__((packed)) { uint32_t magic, status; uint64_t result_addr, cycles; uint32_t error_code; } comp_t;
static void w32(uintptr_t off, uint32_t val){ volatile uint32_t *r=(volatile uint32_t*)(MMIO_BASE+off); *r=val; __sync_synchronize(); }
static uint32_t r32(uintptr_t off){ volatile uint32_t *r=(volatile uint32_t*)(MMIO_BASE+off); uint32_t v=*r; __sync_synchronize(); return v; }
int main(int argc, char **argv){ (void)argc; (void)argv; desc_t *d=(desc_t*)WORK_BASE; comp_t *c=(comp_t*)(WORK_BASE+COMPLETION_OFFSET); char *result=(char*)(WORK_BASE+RESULT_OFFSET); memset(d,0,sizeof(*d)); memset(c,0,sizeof(*c)); result[0]='\0'; d->magic=0xDEADBEEF; d->version=1; d->type=1; d->flags=0xff; d->request_addr=WORK_BASE+0x1000; d->result_addr=(uint64_t)(uintptr_t)result; d->workspace_addr=WORK_BASE; d->workspace_size=4096; w32(REG_CMD_DESC_ADDR_LO,(uint32_t)((uintptr_t)d&0xffffffffU)); w32(REG_CMD_DESC_ADDR_HI,(uint32_t)(((uint64_t)(uintptr_t)d)>>32)); w32(REG_CMD_DESC_SIZE,(uint32_t)sizeof(*d)); w32(REG_COMP_DESC_ADDR_LO,(uint32_t)((uintptr_t)c&0xffffffffU)); w32(REG_COMP_DESC_ADDR_HI,(uint32_t)(((uint64_t)(uintptr_t)c)>>32)); w32(REG_CMD_DOORBELL,1); uint32_t status=0; for(int i=0;i<POLL_LIMIT;i++){ status=r32(REG_COMP_STATUS); if(status==1||status==2) break; } uint32_t err=r32(REG_COMP_ERROR_CODE); printf("bad_descriptor_expected_status=%u error_code=%u\n",status,err); printf("completion_magic=0x%08x completion_status=%u cycles=%llu result_addr=0x%llx\n",c->magic,c->status,(unsigned long long)c->cycles,(unsigned long long)c->result_addr); printf("result_prefix=%.160s\n",result); return (status==2 && err==0x1001) ? 0 : 7; }
'''


def marker_line(text: str, key: str) -> str:
    return next((line for line in text.splitlines() if key in line), '')


def parse_result_path(gem5_log: str) -> Path | None:
    m = re.search(r'uarch_request_decode verified=true.*result_path=(\S+)', gem5_log)
    if m:
        p = Path(m.group(1))
        if p.exists():
            return p
    return None


def run_case(case: dict) -> dict:
    case_dir = RUNROOT / 'proof_runs' / case['row_id']
    case_dir.mkdir(parents=True, exist_ok=True)
    request_path = case_dir / 'simulation_request.json'
    write_json(request_path, case['request'])
    write_json(case_dir / 'generic_accel_command_descriptor.json', build_generic_accel_command_descriptor(case['request']))
    binary = DRIVER
    if case['expected'] == 'descriptor_error':
        bad_src = RUNROOT / 'replay/generic_accel_bad_descriptor_driver.c'
        bad_bin = RUNROOT / 'replay/generic_accel_bad_descriptor_driver'
        bad_src.write_text(BAD_DRIVER_C, encoding='utf-8')
        rc, _, _, _ = run_cmd(['gcc','-std=c99','-O2','-Wall','-Wextra','-static',str(bad_src),'-o',str(bad_bin)], timeout=120)
        if rc != 0:
            return {'row_id':case['row_id'], 'status':'blocked', 'blockers':['bad_descriptor_driver_build_failed']}
        binary = bad_bin
    m5out = case_dir / 'm5out'
    cmd = [GEM5, f'--outdir={m5out}', '--debug-flags=GenericAccel', '--debug-file=gem5.log', CONFIG, '--binary', binary, '--request', request_path, '--simulator', GENERIC_SIM, '--max-ticks', '10000000000', '--cpu-type', 'atomic', '--driver-repeat', str(case.get('repeat',1))]
    rc, stdout, stderr, elapsed = run_cmd(cmd, timeout=240)
    (case_dir / 'gem5.stdout.log').write_text(stdout, encoding='utf-8')
    (case_dir / 'gem5.stderr.log').write_text(stderr, encoding='utf-8')
    gem5_log_path = m5out / 'gem5.log'
    gem5_log = gem5_log_path.read_text(encoding='utf-8', errors='replace') if gem5_log_path.exists() else ''
    (case_dir / 'gem5.log').write_text(gem5_log, encoding='utf-8')
    raw_result_path = parse_result_path(gem5_log)
    result = None
    result_copy = None
    if raw_result_path and raw_result_path.exists():
        result = json.loads(raw_result_path.read_text(encoding='utf-8'))
        result_copy = case_dir / 'simulation_result.raw.json'
        write_json(result_copy, result)
    artifacts = {
        'transport_harness': 'gem5_generic_accel_microarchitecture_v1', 'fallback_from_gem5': False,
        'simulation_request': str(request_path), 'simulation_result': str(result_copy) if result_copy else str(raw_result_path) if raw_result_path else None,
        'gem5_log': str(gem5_log_path), 'gem5_stdout': str(case_dir/'gem5.stdout.log'), 'gem5_stderr': str(case_dir/'gem5.stderr.log'),
        'generic_accel_command_descriptor': str(case_dir/'generic_accel_command_descriptor.json'),
        'gem5_stats': str(m5out/'stats.txt') if (m5out/'stats.txt').exists() else None,
        'gem5_config_ini': str(m5out/'config.ini') if (m5out/'config.ini').exists() else None,
        'gem5_config_json': str(m5out/'config.json') if (m5out/'config.json').exists() else None,
        'require_gem5_stats_config': True,
    }
    if result is not None:
        raw_obs = build_raw_l4_interface_observations(gem5_log=gem5_log, gem5_stdout=stdout, result=result, source_artifacts=artifacts)
        write_json(case_dir/'raw_l4_interface_observations.json', raw_obs)
        artifacts['raw_l4_interface_observations'] = str(case_dir/'raw_l4_interface_observations.json')
        proof = build_gem5_l4_proof(gem5_log, stdout, result, artifacts)
        write_json(case_dir/'gem5_l4_proof.json', proof)
        metrics = canonicalize_l4_interface_metrics(raw_obs, gem5_l4_proof=proof, raw_observations_artifact=str(case_dir/'raw_l4_interface_observations.json'))
        write_json(case_dir/'l4_interface_metrics.json', metrics)
    else:
        proof = {'passed': False, 'proof_status':'expected_descriptor_error' if case['expected']=='descriptor_error' else 'failed', 'checks': {}, 'missing_evidence':['no_passed_result_json'], 'transport_harness':'gem5_generic_accel_microarchitecture_v1', 'fallback_from_gem5':False, 'source_artifacts':artifacts}
        metrics = {'status':'blocked'}
        write_json(case_dir/'gem5_l4_proof.json', proof)
    descriptor_error_observed = 'descriptor_read verified=false reason=bad_magic_or_version' in gem5_log and 'bad_descriptor_expected_status=2 error_code=4097' in stdout
    row = {
        'row_id': case['row_id'], 'candidate_id': case['candidate_id'], 'workload_case_id': case['workload_case_id'], 'expected': case['expected'], 'driver_repeat': case.get('repeat',1),
        'gem5_returncode': rc, 'elapsed_s': elapsed, 'run_dir': str(case_dir),
        'proof_passed': proof.get('passed') is True, 'proof_status': proof.get('proof_status'), 'metrics_status': metrics.get('status'),
        'descriptor_error_observed': descriptor_error_observed,
        'log_markers': {
            'descriptor_read_true_count': gem5_log.count('descriptor_read verified=true'),
            'descriptor_read_false_count': gem5_log.count('descriptor_read verified=false'),
            'request_decode_true_count': gem5_log.count('uarch_request_decode verified=true'),
            'microarchitecture_execute_true_count': gem5_log.count('microarchitecture_execute verified=true'),
            'completion_writeback_true_count': gem5_log.count('completion_writeback verified=true'),
            'completion_writeback_false_count': gem5_log.count('completion_writeback verified=false'),
            'driver_status_passed_count': stdout.count('generic_accel_l4_status=1 error_code=0'),
            'driver_completion_descriptor_passed_count': stdout.count('completion_magic=0x4753494d completion_status=0'),
            'uarch_op_complete_count': gem5_log.count('uarch_op_complete verified=true'),
        },
        'artifacts': artifacts,
        'missing_evidence': proof.get('missing_evidence', []),
        'claim_label': 'trusted_l4_vertical_row' if proof.get('passed') is True else ('expected_negative_descriptor_validation' if descriptor_error_observed else 'blocked'),
        'claim_boundary': 'Real gem5 GenericAccel L4 row; still vertical evidence, not QE full-SCF or PPA.' if proof.get('passed') is True else 'Negative/blocked L4 validation row; not performance evidence.',
    }
    write_json(case_dir/'row_summary.json', row)
    return row


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Run the repo-owned GenericAccel gem5 L4 expanded replay matrix.')
    parser.add_argument('--runroot', type=Path, required=True, help='Output runroot for proof_runs and generic_accel_l4_expanded_proof_matrix.json')
    parser.add_argument('--repo-root', type=Path, default=REPO_ROOT, help='Repository root containing gem5 config/driver and generic_sim')
    parser.add_argument('--gem5-bin', type=Path, default=GEM5, help='gem5.opt binary to execute')
    parser.add_argument('--generic-sim', type=Path, default=None, help='Override generic_sim path')
    parser.add_argument('--driver', type=Path, default=None, help='Override GenericAccel guest driver path')
    parser.add_argument('--external-binary-ok', action='store_true', help='Allow --gem5-bin to point outside --repo-root; provenance is recorded fail-closed')
    return parser.parse_args(argv)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def main(argv=None) -> int:
    global REPO_ROOT, RUNROOT, GEM5, CONFIG, DRIVER, GENERIC_SIM, LOG
    args = parse_args(argv)
    REPO_ROOT = args.repo_root.resolve()
    RUNROOT = args.runroot.resolve()
    GEM5 = args.gem5_bin.resolve()
    CONFIG = REPO_ROOT / 'gem5_integration/configs/generic_accel_l4_test.py'
    DRIVER = args.driver.resolve() if args.driver else REPO_ROOT / 'gem5_integration/test_programs/generic_accel/generic_accel_l4_driver'
    GENERIC_SIM = args.generic_sim.resolve() if args.generic_sim else REPO_ROOT / 'model/generic_sim_backend/build/generic_sim'
    LOG = RUNROOT / 'logs/expanded_gem5_l4_matrix.log'
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    if not (REPO_ROOT / 'dse_v2').exists():
        raise SystemExit(f'--repo-root does not look like this repo: {REPO_ROOT}')
    if not args.external_binary_ok and not _is_relative_to(GEM5, REPO_ROOT):
        raise SystemExit(f'gem5 binary is outside repo; pass --external-binary-ok to record external-binary provenance: {GEM5}')
    ensure_prereqs()
    rows = [run_case(case) for case in CASES]
    matrix = {
        'schema_version': 'dse.slot4.generic_accel_l4_expanded_proof_matrix.v1',
        'created_at': now(),
        'gem5_binary': str(GEM5),
        'gem5_binary_sha256': sha(GEM5) if GEM5.exists() else None,
        'row_count': len(rows),
        'passed_runtime_rows': sum(1 for r in rows if r.get('proof_passed') is True),
        'expected_negative_rows': sum(1 for r in rows if r.get('descriptor_error_observed') is True),
        'rows': rows,
        'claim_boundary': 'Expanded L4 subsystem evidence over multiple requests/candidates and one descriptor-error path. It is release-consumable L4 evidence, not final global deliverable completion.',
    }
    write_json(RUNROOT / 'generic_accel_l4_expanded_proof_matrix.json', matrix)
    print(json.dumps({'matrix': str(RUNROOT / 'generic_accel_l4_expanded_proof_matrix.json'), 'passed_runtime_rows': matrix['passed_runtime_rows'], 'expected_negative_rows': matrix['expected_negative_rows']}, indent=2))
    return 0 if matrix['passed_runtime_rows'] >= 3 and matrix['expected_negative_rows'] >= 1 else 2

if __name__ == '__main__':
    raise SystemExit(main())
