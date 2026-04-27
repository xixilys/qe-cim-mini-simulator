# Phase 2 Plan: Multi-Workload & Multi-Objective DSE

**Start Date**: 2026-04-23  
**Target Duration**: 1-2 weeks  
**Status**: 📋 Planning → Implementation

---

## 🎯 Phase 2 Objectives

### Primary Goals

1. **Multi-Workload Evaluation**
   - Run DSE on 5+ different QE workloads
   - Identify workload-dependent design trade-offs
   - Find robust designs across workloads

2. **Multi-Objective Optimization**
   - Add 3rd objective: Area/Resource Cost
   - Generate true Pareto frontier (time vs energy vs area)
   - Add resource constraints (DSP/BRAM/LUT limits)

3. **Model Validation**
   - Validate top-5 designs with SystemC model
   - Calibrate fast model parameters
   - Measure prediction accuracy

4. **Sensitivity Analysis**
   - Parameter robustness testing
   - Workload sensitivity analysis
   - Design margin analysis

---

## 📋 Detailed Task Breakdown

### Week 1: Multi-Workload DSE

#### Task 1.1: Workload Characterization (Day 1-2)

**Objective**: Characterize 5 representative workloads

**Workloads to Use**:
1. **Si-small** (existing): npw=2945, nkb=144, m=16
2. **GaN-medium**: npw=4200, nkb=96, m=20
3. **MoS2-small**: npw=2800, nkb=80, m=14
4. **TiO2-medium**: npw=3500, nkb=112, m=24
5. **Graphene-large**: npw=5500, nkb=160, m=32

**Steps**:
- [ ] Create workload characterization script
- [ ] Compute workload features:
  - Compute intensity (FLOPs/byte)
  - Memory pressure (data size / cache size)
  - FFT pressure (FFT grid size)
  - Projector density (nkb/npw ratio)
  - Band count scaling (m)
- [ ] Generate workload feature matrix
- [ ] Visualize workload diversity

**Deliverable**: `workloads/analysis/workload_features_v2.csv`

---

#### Task 1.2: Multi-Workload DSE Engine (Day 2-3)

**Objective**: Extend DSE engine to handle multiple workloads

**Implementation**:
```python
class MultiWorkloadDSE:
    def __init__(self, workloads: List[Dict], design_space_path: Path):
        self.workloads = workloads
        self.dse_engines = [BayesianDSE(...) for _ in workloads]
    
    def run_optimization(self, n_iterations: int, strategy: str):
        # Strategy options:
        # 1. "sequential": Optimize each workload separately
        # 2. "average": Optimize average performance across workloads
        # 3. "worst_case": Optimize worst-case performance
        # 4. "pareto": Multi-objective across workloads
        pass
```

**Steps**:
- [ ] Implement `MultiWorkloadDSE` class
- [ ] Add workload aggregation strategies
- [ ] Implement parallel workload evaluation
- [ ] Add workload-specific result tracking

**Deliverable**: `scripts/dse/run_multi_workload_dse.py`

---

#### Task 1.3: Run Multi-Workload DSE (Day 3-4)

**Objective**: Execute DSE on 5 workloads

**Experiments**:
1. **Individual Optimization** (5 × 30 trials = 150 trials)
   - Optimize each workload separately
   - Find workload-specific optimal designs
   
2. **Average Performance** (50 trials)
   - Optimize average performance across all workloads
   - Find robust design
   
3. **Worst-Case Performance** (50 trials)
   - Optimize worst-case performance
   - Find conservative design

**Steps**:
- [ ] Run individual workload DSE (5 workloads)
- [ ] Run average performance DSE
- [ ] Run worst-case performance DSE
- [ ] Collect and organize results

**Deliverable**: `results/multi_workload/`
- `individual_results_*.csv` (5 files)
- `average_performance_results.csv`
- `worst_case_results.csv`

---

#### Task 1.4: Multi-Workload Analysis (Day 4-5)

**Objective**: Analyze workload-dependent trade-offs

**Analysis**:
- [ ] Compare optimal designs across workloads
- [ ] Identify workload-sensitive parameters
- [ ] Measure design robustness
- [ ] Generate workload sensitivity plots

**Metrics**:
- **Design Diversity**: How different are optimal designs?
- **Parameter Sensitivity**: Which parameters vary most?
- **Performance Variance**: How much does performance vary?
- **Robustness Score**: How well does average design perform on each workload?

**Deliverable**: `docs/MULTI_WORKLOAD_ANALYSIS.md`

---

### Week 2: Multi-Objective Optimization

#### Task 2.1: Add Area Objective (Day 6)

**Objective**: Extend performance model with area/resource cost

**Area Model**:
```python
def compute_area_cost(design_point: Dict) -> float:
    # Weighted sum of resources
    dsp_cost = design_point['dsp_count'] * 1.0
    bram_cost = design_point['bram_kb'] * 0.1
    lut_cost = design_point['lut_count'] * 0.001
    
    area_cost = dsp_cost + bram_cost + lut_cost
    return area_cost
```

**Steps**:
- [ ] Implement area cost function
- [ ] Update performance model to return 3 objectives
- [ ] Validate area estimates against FPGA specs

**Deliverable**: Updated `models/fast/performance_model.py`

---

#### Task 2.2: Add Resource Constraints (Day 6-7)

**Objective**: Add FPGA resource constraints

**Constraints**:
```python
constraints = [
    "dsp_utilization <= 0.80",      # 80% max DSP
    "bram_utilization <= 0.70",     # 70% max BRAM
    "lut_utilization <= 0.60",      # 60% max LUT
    "power_consumption <= 75.0",    # 75W max power
]
```

**Steps**:
- [ ] Implement constraint checking in performance model
- [ ] Add constraint handling to Bayesian Optimization
- [ ] Test constraint enforcement

**Deliverable**: Updated `scripts/dse/run_bayesian_dse.py`

---

#### Task 2.3: Run 3-Objective DSE (Day 7-8)

**Objective**: Generate true Pareto frontier

**Configuration**:
```python
objectives = {
    "time_s": ObjectiveProperties(minimize=True, threshold=5e-5),
    "energy_j": ObjectiveProperties(minimize=True, threshold=0.003),
    "area_cost": ObjectiveProperties(minimize=True, threshold=50000),
}
```

**Steps**:
- [ ] Configure 3-objective Bayesian Optimization
- [ ] Run 100-trial DSE with constraints
- [ ] Extract Pareto frontier
- [ ] Analyze trade-offs

**Deliverable**: `results/pareto/three_objective_pareto_v2.csv`

---

#### Task 2.4: Pareto Analysis (Day 8-9)

**Objective**: Analyze multi-objective trade-offs

**Analysis**:
- [ ] Visualize 3D Pareto frontier
- [ ] Identify knee points (best trade-offs)
- [ ] Compute hypervolume indicator
- [ ] Generate trade-off curves (time vs area, energy vs area)

**Visualizations**:
1. 3D scatter plot (time, energy, area)
2. 2D projections (3 plots)
3. Parallel coordinates plot
4. Radar chart for top-5 designs

**Deliverable**: `docs/MULTI_OBJECTIVE_ANALYSIS.md`

---

### Week 2: Model Validation

#### Task 3.1: SystemC Integration (Day 9-10)

**Objective**: Integrate SystemC model for mid-fidelity evaluation

**Implementation**:
```python
class SystemCModel:
    def __init__(self, systemc_binary_path: Path):
        self.binary = systemc_binary_path
    
    def evaluate(self, design_point: Dict, workload: Dict) -> Dict:
        # Generate SystemC config
        # Run SystemC simulation
        # Parse results
        return {'time_cycles': ..., 'energy_j': ..., 'area': ...}
```

**Steps**:
- [ ] Create SystemC wrapper script
- [ ] Implement design point → SystemC config converter
- [ ] Test SystemC evaluation on 1 design
- [ ] Validate against fast model

**Deliverable**: `models/mid/systemc_model.py`

---

#### Task 3.2: Top-5 Design Validation (Day 10-11)

**Objective**: Validate top-5 designs with SystemC

**Designs to Validate**:
1. Best time design
2. Best energy design
3. Best area design
4. Knee point design #1
5. Knee point design #2

**Steps**:
- [ ] Run SystemC simulation for each design
- [ ] Compare fast model vs SystemC predictions
- [ ] Compute prediction errors
- [ ] Identify model calibration needs

**Metrics**:
- **Time Error**: |t_fast - t_systemc| / t_systemc
- **Energy Error**: |e_fast - e_systemc| / e_systemc
- **Area Error**: |a_fast - a_systemc| / a_systemc

**Deliverable**: `results/validation/systemc_validation_v2.csv`

---

#### Task 3.3: Model Calibration (Day 11-12)

**Objective**: Calibrate fast model based on SystemC results

**Calibration Strategy**:
1. Identify systematic biases in fast model
2. Adjust model parameters (e.g., pipeline efficiency, memory latency)
3. Re-run validation
4. Iterate until error < 10%

**Steps**:
- [ ] Analyze prediction errors
- [ ] Identify calibration parameters
- [ ] Update fast model
- [ ] Re-validate

**Deliverable**: Updated `models/fast/performance_model.py` (calibrated)

---

### Week 2: Sensitivity Analysis

#### Task 4.1: Parameter Robustness (Day 12-13)

**Objective**: Test design robustness to parameter variations

**Method**: Monte Carlo sampling
- Vary each parameter by ±10%
- Measure performance variance
- Identify sensitive parameters

**Steps**:
- [ ] Implement robustness testing script
- [ ] Run 1000 Monte Carlo samples per design
- [ ] Compute robustness metrics
- [ ] Visualize sensitivity

**Deliverable**: `docs/SENSITIVITY_ANALYSIS.md`

---

#### Task 4.2: Workload Sensitivity (Day 13)

**Objective**: Test design performance across workload variations

**Method**: Workload perturbation
- Vary npw, nkb, m by ±20%
- Measure performance degradation
- Identify workload-sensitive designs

**Steps**:
- [ ] Generate perturbed workloads
- [ ] Evaluate designs on perturbed workloads
- [ ] Compute sensitivity scores
- [ ] Rank designs by robustness

**Deliverable**: `results/sensitivity/workload_sensitivity_v2.csv`

---

#### Task 4.3: Design Margin Analysis (Day 14)

**Objective**: Compute design margins for production

**Margins to Compute**:
- **Timing Margin**: Slack before timing violation
- **Power Margin**: Headroom before power limit
- **Resource Margin**: Unused DSP/BRAM/LUT

**Steps**:
- [ ] Implement margin calculation
- [ ] Compute margins for top-10 designs
- [ ] Recommend production design with margins

**Deliverable**: `results/margins/design_margins_v2.csv`

---

## 📊 Expected Outcomes

### Quantitative Results

1. **Multi-Workload Performance**
   - 5 workload-specific optimal designs
   - 1 robust design (average performance)
   - 1 conservative design (worst-case)
   - Performance variance: <20% across workloads

2. **Multi-Objective Pareto**
   - 10-20 Pareto-optimal designs
   - 3-5 knee points identified
   - Trade-off curves quantified

3. **Validation Accuracy**
   - Fast model error: <10% vs SystemC
   - Calibrated model error: <5% vs SystemC

4. **Robustness Metrics**
   - Parameter sensitivity: <15% variance
   - Workload sensitivity: <25% variance
   - Design margins: >20% headroom

### Qualitative Insights

1. **Workload Dependencies**
   - Which parameters are workload-sensitive?
   - Can one design fit all workloads?
   - What are the trade-offs?

2. **Multi-Objective Trade-offs**
   - Time vs Area: How much area for 2× speedup?
   - Energy vs Area: Can we reduce energy without area increase?
   - Optimal operating points for different use cases

3. **Design Recommendations**
   - Best design for performance-critical applications
   - Best design for energy-constrained systems
   - Best design for area-limited FPGAs
   - Best all-around design

---

## 🛠️ Implementation Plan

### Priority Order

**Week 1 (High Priority)**:
1. Task 1.1: Workload Characterization
2. Task 1.2: Multi-Workload DSE Engine
3. Task 1.3: Run Multi-Workload DSE
4. Task 1.4: Multi-Workload Analysis

**Week 2 (Medium Priority)**:
5. Task 2.1: Add Area Objective
6. Task 2.2: Add Resource Constraints
7. Task 2.3: Run 3-Objective DSE
8. Task 2.4: Pareto Analysis

**Week 2 (Lower Priority)**:
9. Task 3.1: SystemC Integration
10. Task 3.2: Top-5 Design Validation
11. Task 3.3: Model Calibration

**Week 2 (Optional)**:
12. Task 4.1: Parameter Robustness
13. Task 4.2: Workload Sensitivity
14. Task 4.3: Design Margin Analysis

---

## 📁 Deliverables Checklist

### Code
- [ ] `scripts/dse/run_multi_workload_dse.py`
- [ ] `scripts/workload/characterize_workloads.py`
- [ ] `models/mid/systemc_model.py`
- [ ] `scripts/analysis/analyze_pareto.py`
- [ ] `scripts/analysis/sensitivity_analysis.py`

### Data
- [ ] `workloads/analysis/workload_features_v2.csv`
- [ ] `results/multi_workload/*.csv` (7 files)
- [ ] `results/pareto/three_objective_pareto_v2.csv`
- [ ] `results/validation/systemc_validation_v2.csv`
- [ ] `results/sensitivity/*.csv` (3 files)

### Documentation
- [ ] `docs/MULTI_WORKLOAD_ANALYSIS.md`
- [ ] `docs/MULTI_OBJECTIVE_ANALYSIS.md`
- [ ] `docs/SENSITIVITY_ANALYSIS.md`
- [ ] `docs/PHASE2_SUMMARY.md`

### Visualizations
- [ ] Multi-workload comparison plots (5)
- [ ] 3D Pareto frontier plot
- [ ] Trade-off curves (3)
- [ ] Sensitivity heatmaps (2)
- [ ] Validation scatter plots (3)

---

## 🎯 Success Criteria

### Must Have (Phase 2 Complete)
- [x] Multi-workload DSE runs successfully on 5 workloads
- [ ] 3-objective Pareto frontier generated
- [ ] Top-5 designs validated with SystemC
- [ ] Fast model calibrated (error <10%)
- [ ] Comprehensive analysis documentation

### Nice to Have (Stretch Goals)
- [ ] Sensitivity analysis complete
- [ ] Design margins computed
- [ ] Automated report generation
- [ ] Interactive visualization dashboard

---

## 🚀 Getting Started

### Immediate Next Steps (Today)

1. **Create workload characterization script**
   ```bash
   python3 scripts/workload/characterize_workloads.py
   ```

2. **Implement multi-workload DSE engine**
   ```bash
   # Edit: scripts/dse/run_multi_workload_dse.py
   ```

3. **Run first multi-workload experiment**
   ```bash
   python3 scripts/dse/run_multi_workload_dse.py --workloads 5 --trials 30
   ```

---

**Status**: 📋 Ready to Start  
**Next Action**: Implement Task 1.1 (Workload Characterization)
