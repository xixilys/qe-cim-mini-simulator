MODULE fpga_electrons_module
  !
  ! Fortran interface for complete electrons loop offload to FPGA
  !
  USE ISO_C_BINDING
  USE fpga_offload_module, ONLY: fpga_device_t, global_fpga_device
  IMPLICIT NONE
  
  PRIVATE
  PUBLIC :: fpga_electrons_request_t, fpga_electrons_result_t
  PUBLIC :: fpga_electrons_offload_wrapper
  PUBLIC :: fpga_electrons_available
  
  ! Complete electrons loop request
  TYPE, BIND(C) :: fpga_electrons_request_t
    ! System dimensions
    INTEGER(C_INT) :: n_bands
    INTEGER(C_INT) :: n_basis
    INTEGER(C_INT) :: n_kpoints
    INTEGER(C_INT) :: n_spin
    INTEGER(C_INT) :: n_electrons
    
    ! SCF convergence parameters
    INTEGER(C_INT) :: max_iterations
    REAL(C_DOUBLE) :: conv_threshold
    REAL(C_DOUBLE) :: diag_threshold
    LOGICAL(C_BOOL) :: adaptive_threshold
    
    ! Mixing parameters
    REAL(C_DOUBLE) :: mixing_beta
    INTEGER(C_INT) :: mixing_ndim
    CHARACTER(KIND=C_CHAR) :: mixing_mode(32)
    
    ! Physical parameters
    REAL(C_DOUBLE) :: temperature
    CHARACTER(KIND=C_CHAR) :: occupations(32)
    
    ! Flags
    LOGICAL(C_BOOL) :: use_paw
    LOGICAL(C_BOOL) :: use_uspp
    LOGICAL(C_BOOL) :: lda_plus_u
    LOGICAL(C_BOOL) :: noncolin
    
    ! FPGA-specific parameters
    CHARACTER(KIND=C_CHAR) :: architecture(32)
    CHARACTER(KIND=C_CHAR) :: resident_policy(32)
    LOGICAL(C_BOOL) :: enable_cim
  END TYPE fpga_electrons_request_t
  
  ! Electrons loop result
  TYPE, BIND(C) :: fpga_electrons_result_t
    ! Convergence status
    LOGICAL(C_BOOL) :: converged
    INTEGER(C_INT) :: iterations
    REAL(C_DOUBLE) :: final_error
    
    ! Energies (in Ry)
    REAL(C_DOUBLE) :: total_energy
    REAL(C_DOUBLE) :: band_energy
    REAL(C_DOUBLE) :: hartree_energy
    REAL(C_DOUBLE) :: xc_energy
    REAL(C_DOUBLE) :: ewald_energy
    REAL(C_DOUBLE) :: paw_energy
    
    ! Fermi energy
    REAL(C_DOUBLE) :: fermi_energy
    REAL(C_DOUBLE) :: fermi_energy_up
    REAL(C_DOUBLE) :: fermi_energy_down
    
    ! Performance metrics
    REAL(C_DOUBLE) :: total_time_ns
    REAL(C_DOUBLE) :: c_bands_time_ns
    REAL(C_DOUBLE) :: sum_band_time_ns
    REAL(C_DOUBLE) :: mix_rho_time_ns
    
    ! Detailed timing (pointers)
    TYPE(C_PTR) :: iter_times_ns
    TYPE(C_PTR) :: iter_errors
  END TYPE fpga_electrons_result_t
  
  ! C interface declarations
  INTERFACE
    SUBROUTINE fpga_electrons_request_init_c(req) BIND(C, NAME='fpga_electrons_request_init')
      IMPORT :: fpga_electrons_request_t
      TYPE(fpga_electrons_request_t), INTENT(INOUT) :: req
    END SUBROUTINE fpga_electrons_request_init_c
    
    SUBROUTINE fpga_electrons_result_free_c(result) BIND(C, NAME='fpga_electrons_result_free')
      IMPORT :: fpga_electrons_result_t
      TYPE(fpga_electrons_result_t), INTENT(INOUT) :: result
    END SUBROUTINE fpga_electrons_result_free_c
    
    SUBROUTINE fpga_electrons_result_print_c(result) BIND(C, NAME='fpga_electrons_result_print')
      IMPORT :: fpga_electrons_result_t
      TYPE(fpga_electrons_result_t), INTENT(IN) :: result
    END SUBROUTINE fpga_electrons_result_print_c
    
    INTEGER(C_INT) FUNCTION fpga_electrons_offload_c( &
        dev, req, initial_rho, initial_wfc, result, &
        final_rho, final_wfc, final_et) &
        BIND(C, NAME='fpga_electrons_offload')
      IMPORT :: C_INT, C_PTR, fpga_device_t, fpga_electrons_request_t, fpga_electrons_result_t
      TYPE(fpga_device_t), INTENT(IN) :: dev
      TYPE(fpga_electrons_request_t), INTENT(IN) :: req
      TYPE(C_PTR), VALUE :: initial_rho
      TYPE(C_PTR), VALUE :: initial_wfc
      TYPE(fpga_electrons_result_t), INTENT(OUT) :: result
      TYPE(C_PTR), VALUE :: final_rho
      TYPE(C_PTR), VALUE :: final_wfc
      TYPE(C_PTR), VALUE :: final_et
    END FUNCTION fpga_electrons_offload_c
  END INTERFACE
  
CONTAINS

  FUNCTION fpga_electrons_available() RESULT(available)
    LOGICAL :: available
    available = global_fpga_device%initialized
  END FUNCTION fpga_electrons_available
  
  SUBROUTINE fpga_electrons_offload_wrapper( &
      nbnd, npwx, nks, nspin, nelec, &
      niter, tr2, ethr, mixing_beta, nmix, &
      rho_in, rho_out, et, evc, &
      converged, final_etot, iterations)
    !
    ! High-level wrapper for QE electrons loop
    !
    USE kinds, ONLY: DP
    IMPLICIT NONE
    
    ! Input: system dimensions
    INTEGER, INTENT(IN) :: nbnd, npwx, nks, nspin
    REAL(DP), INTENT(IN) :: nelec
    
    ! Input: convergence parameters
    INTEGER, INTENT(IN) :: niter, nmix
    REAL(DP), INTENT(IN) :: tr2, ethr, mixing_beta
    
    ! Input/output: charge density
    REAL(DP), INTENT(IN) :: rho_in(:,:)
    REAL(DP), INTENT(OUT) :: rho_out(:,:)
    
    ! Input/output: eigenvalues and wavefunctions
    REAL(DP), INTENT(INOUT) :: et(:,:)
    COMPLEX(DP), INTENT(INOUT) :: evc(:,:,:)
    
    ! Output: convergence status
    LOGICAL, INTENT(OUT) :: converged
    REAL(DP), INTENT(OUT) :: final_etot
    INTEGER, INTENT(OUT) :: iterations
    
    ! Local variables
    TYPE(fpga_electrons_request_t) :: req
    TYPE(fpga_electrons_result_t) :: result
    INTEGER(C_INT) :: status
    
    IF (.NOT. fpga_electrons_available()) THEN
      WRITE(*,'(5X,"ERROR: FPGA device not initialized")')
      converged = .FALSE.
      RETURN
    END IF
    
    CALL fpga_electrons_request_init_c(req)
    
    req%n_bands = nbnd
    req%n_basis = npwx
    req%n_kpoints = nks
    req%n_spin = nspin
    req%n_electrons = INT(nelec, C_INT)
    
    req%max_iterations = niter
    req%conv_threshold = tr2
    req%diag_threshold = ethr
    req%adaptive_threshold = .TRUE.
    
    req%mixing_beta = mixing_beta
    req%mixing_ndim = nmix
    
    req%enable_cim = .TRUE.
    
    status = fpga_electrons_offload_c( &
        global_fpga_device, req, &
        C_LOC(rho_in), C_LOC(evc), result, &
        C_LOC(rho_out), C_LOC(evc), C_LOC(et))
    
    IF (status /= 0) THEN
      WRITE(*,'(5X,"ERROR: FPGA electrons offload failed")')
      converged = .FALSE.
      CALL fpga_electrons_result_free_c(result)
      RETURN
    END IF
    
    converged = result%converged
    final_etot = result%total_energy
    iterations = result%iterations
    
    CALL fpga_electrons_result_print_c(result)
    
    CALL fpga_electrons_result_free_c(result)
    
  END SUBROUTINE fpga_electrons_offload_wrapper

END MODULE fpga_electrons_module
