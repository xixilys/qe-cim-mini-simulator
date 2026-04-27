#pragma once

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace qebs {

// Forward declarations
struct ClusterConfig;
struct ComputeUnitConfig;

/**
 * @brief Compute unit type enumeration
 * 
 * Defines the type of compute unit used in a cluster.
 */
enum class ComputeUnitType {
  CIM_ARRAY,           // Compute-in-Memory Array with Ozaki-II
  TRADITIONAL_FPGA,    // Traditional FPGA GEMM (blocked)
  PIM,                 // Processing-in-Memory (future)
  HYBRID               // Hybrid CIM+Traditional (future)
};

/**
 * @brief Compute unit configuration
 * 
 * Specifies the compute unit type and its parameters.
 */
struct ComputeUnitConfig {
  ComputeUnitType type = ComputeUnitType::CIM_ARRAY;
  
  // CIM Array specific parameters
  int cim_moduli_count = 16;           // Number of moduli for Ozaki-II
  int cim_array_rows = 256;            // CIM array dimensions
  int cim_array_cols = 256;
  double cim_frequency_mhz = 150.0;    // CIM clock frequency
  
  // Traditional FPGA specific parameters
  int fpga_tile_size = 32;             // Tile size for blocked GEMM
  int fpga_dsp_count = 128;            // Number of DSP slices
  double fpga_frequency_mhz = 300.0;   // FPGA clock frequency
  
  // PIM specific parameters (future)
  int pim_bank_count = 8;
  int pim_subarray_count = 16;
  
  // Common parameters
  int parallelism = 4;                 // Parallel compute lanes
  bool enable_karatsuba = true;        // Use Karatsuba 3M multiplication
  
  std::string brief() const;
};

/**
 * @brief Cluster type enumeration
 * 
 * Defines the functional type of a cluster.
 */
enum class ClusterType {
  OPERATOR_SWEEP,      // h_psi/s_psi operator sweep (Cluster A)
  REDUCED_BUILD,       // H_sub/S_sub reduction (Cluster B)
  HARDWARE_DIAG,       // Eigensolver (Cluster C)
  REFRESH_RESIDUAL,    // Residual and refresh (Cluster D)
  FUSED_BUILD_DIAG,    // Fused B+C (3-cluster architecture)
  CUSTOM               // Custom cluster type
};

/**
 * @brief Cluster configuration
 * 
 * Specifies a single cluster's type, compute units, and parameters.
 */
struct ClusterConfig {
  std::string cluster_id;              // e.g., "cluster_a", "cluster_0"
  ClusterType type = ClusterType::OPERATOR_SWEEP;
  bool enabled = true;                 // Whether this cluster is active
  std::string fusion_group;            // Fusion group identifier (e.g., "bc_fused")
  
  // Compute unit configuration
  ComputeUnitConfig compute_unit;
  
  // Cluster-specific parameters
  int on_chip_buffer_kb = 512;         // On-chip buffer size
  int dma_bandwidth_gbps = 100;        // DMA bandwidth
  bool enable_pipelining = true;       // Enable pipeline execution
  int pipeline_depth = 4;              // Pipeline stages
  
  // Resident object policy
  std::string resident_policy = "fit_first";  // fit_first, spill_tolerant
  double resident_budget_scale = 1.0;
  
  // Execution policy
  bool enable_backpressure = true;
  int max_concurrent_ops = 8;
  
  std::string brief() const;
};

/**
 * @brief Architecture configuration
 * 
 * Complete architecture specification including clusters, interconnect,
 * and global policies. This structure is projected from Phase 1 JSON templates.
 */
struct ArchitectureConfig {
  // Metadata
  std::string template_id;             // e.g., "4cluster_cim_baseline_v1"
  std::string template_label;          // Human-readable label
  std::string architecture_family;     // "F1", "F2", "F3", or custom
  
  // Cluster configuration
  std::vector<ClusterConfig> clusters;
  
  // Global policies
  std::string offload_scope = "balanced";           // single_hotpath, balanced, device_heavy
  std::string diag_policy = "device_first_fallback"; // cpu_only, device_first_fallback, aggressive_device
  bool enable_device_fft = true;
  bool force_host_diag = false;
  bool allow_cpu_diag_fallback = true;
  
  // Resource constraints (from VU9P limits)
  struct ResourceLimits {
    int max_dsp = 6840;
    int max_bram_18k = 4320;
    int max_uram = 960;
    int max_lut = 1182240;
    int max_ff = 2364480;
  } resource_limits;
  
  // Interconnect configuration
  struct InterconnectConfig {
    int axi_data_width = 512;          // AXI bus width (bits)
    int axi_burst_length = 256;        // AXI burst length
    double pcie_bandwidth_gbps = 32.0; // PCIe Gen3 x16
    double ddr_bandwidth_gbps = 76.8;  // DDR4-2400 (4 channels)
  } interconnect;
  
  // Timing configuration
  struct TimingConfig {
    double system_clock_mhz = 250.0;   // System clock frequency
    bool use_proxy_formulas = true;    // Use proxy formulas for compute units
    double proxy_uncertainty = 0.20;   // ±20% uncertainty
  } timing;
  
  // Validation
  bool is_valid() const;
  std::string validate() const;       // Returns error message if invalid
  
  // Resource estimation
  struct ResourceUsage {
    int dsp_used = 0;
    int bram_18k_used = 0;
    int uram_used = 0;
    int lut_used = 0;
    int ff_used = 0;
    
    bool within_limits(const ResourceLimits& limits) const;
    std::string brief() const;
  };
  ResourceUsage estimate_resources() const;
  
  // Utility
  std::string brief() const;
  int cluster_count() const { return static_cast<int>(clusters.size()); }
  
  // Factory methods
  static ArchitectureConfig create_default();
  static ArchitectureConfig from_f1_template();
  static ArchitectureConfig from_f2_template();
  static ArchitectureConfig from_f3_template();
  static ArchitectureConfig from_json_file(const std::string& path);
};

/**
 * @brief Helper functions for string conversion
 */
std::string to_string(ComputeUnitType type);
std::string to_string(ClusterType type);
ComputeUnitType compute_unit_type_from_string(const std::string& str);
ClusterType cluster_type_from_string(const std::string& str);

}  // namespace qebs
