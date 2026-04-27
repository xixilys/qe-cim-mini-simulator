!
! Copyright (C) 2026 Quantum ESPRESSO group
! This file is distributed under the terms of the
! GNU General Public License. See the file `License'
! in the root directory of the present distribution,
! or http://www.gnu.org/copyleft/gpl.txt .
!
!----------------------------------------------------------------------------
MODULE fpga_systemc_interface
  !----------------------------------------------------------------------------
  !
  ! This module provides Fortran interface to SystemC FPGA accelerator
  ! for offloading the electrons SCF loop
  !
  USE, INTRINSIC :: iso_c_binding
  !
  IMPLICIT NONE
  SAVE
  !
  ! Define DP precision (same as QE kinds module)
  INTEGER, PARAMETER :: DP = SELECTED_REAL_KIND(14, 200)
  !
  LOGICAL :: use_fpga_offload = .FALSE.
  !
  PRIVATE
  PUBLIC :: use_fpga_offload, fpga_electrons_offload, fpga_init, fpga_finalize
  !
  ! C interface types
  !
  TYPE, BIND(C) :: systemc_electrons_request
    INTEGER(C_INT) :: n_bands
    INTEGER(C_INT) :: n_basis
    INTEGER(C_INT) :: n_kpoints
    INTEGER(C_INT) :: n_spin
    INTEGER(C_INT) :: max_iterations
    REAL(C_DOUBLE) :: conv_threshold
    REAL(C_DOUBLE) :: diag_threshold
    REAL(C_DOUBLE) :: mixing_beta
    INTEGER(C_INT) :: mixing_ndim
    LOGICAL(C_BOOL) :: enable_cim
  END TYPE systemc_electrons_request
  !
  TYPE, BIND(C) :: systemc_electrons_result
    LOGICAL(C_BOOL) :: converged
    INTEGER(C_INT) :: iterations
    REAL(C_DOUBLE) :: final_error
    REAL(C_DOUBLE) :: total_energy
    REAL(C_DOUBLE) :: total_time_ns
  END TYPE systemc_electrons_result
  !
  ! C function interfaces
  !
  INTERFACE
    !
    INTEGER(C_INT) FUNCTION systemc_fpga_init(arch_name) BIND(C, name="systemc_fpga_init")
      USE, INTRINSIC :: iso_c_binding
      CHARACTER(KIND=C_CHAR), DIMENSION(*) :: arch_name
    END FUNCTION systemc_fpga_init
    !
    INTEGER(C_INT) FUNCTION systemc_fpga_electrons(req, result) &
      BIND(C, name="systemc_fpga_electrons")
      USE, INTRINSIC :: iso_c_binding
      IMPORT :: systemc_electrons_request, systemc_electrons_result
      TYPE(systemc_electrons_request), INTENT(IN) :: req
      TYPE(systemc_electrons_result), INTENT(OUT) :: result
    END FUNCTION systemc_fpga_electrons
    !
    SUBROUTINE systemc_fpga_finalize() BIND(C, name="systemc_fpga_finalize")
    END SUBROUTINE systemc_fpga_finalize
    !
  END INTERFACE
  !
CONTAINS
  !
  !------------------------------------------------------------------------
  SUBROUTINE fpga_init(architecture, ierr)
    !------------------------------------------------------------------------
    !
    ! Initialize FPGA accelerator with specified architecture
    !
    IMPLICIT NONE
    CHARACTER(LEN=*), INTENT(IN) :: architecture
    INTEGER, INTENT(OUT) :: ierr
    !
    CHARACTER(LEN=32) :: arch_c
    INTEGER :: i
    !
    ! Convert Fortran string to C string (null-terminated)
    arch_c = TRIM(architecture) // C_NULL_CHAR
    !
    ierr = systemc_fpga_init(arch_c)
    !
    IF (ierr == 0) THEN
      use_fpga_offload = .TRUE.
    ENDIF
    !
  END SUBROUTINE fpga_init
  !
  !------------------------------------------------------------------------
  SUBROUTINE fpga_finalize()
    !------------------------------------------------------------------------
    !
    ! Finalize FPGA accelerator
    !
    IMPLICIT NONE
    !
    CALL systemc_fpga_finalize()
    use_fpga_offload = .FALSE.
    !
  END SUBROUTINE fpga_finalize
  !
  !------------------------------------------------------------------------
  SUBROUTINE fpga_electrons_offload( &
      nbnd, npwx, nkstot, nspin, &
      niter, tr2, ethr, &
      mixing_beta, nmix, &
      iter_out, dr2_out, conv_elec, etot_out, time_ns_out, stdout )
    !------------------------------------------------------------------------
    !
    ! Offload entire electrons SCF loop to FPGA accelerator
    !
    ! Input:
    !   nbnd         : number of bands
    !   npwx         : maximum number of plane waves (basis size)
    !   nkstot       : total number of k-points
    !   nspin        : number of spin components
    !   niter        : maximum number of SCF iterations
    !   tr2          : convergence threshold for energy
    !   ethr         : convergence threshold for diagonalization
    !   mixing_beta  : mixing parameter
    !   nmix         : mixing dimension
    !
    ! Output:
    !   iter_out     : actual number of iterations performed
    !   dr2_out      : final SCF error
    !   conv_elec    : convergence flag
    !   etot_out     : total energy
    !   time_ns_out  : execution time in nanoseconds
    !
    IMPLICIT NONE
    !
    INTEGER, INTENT(IN) :: nbnd, npwx, nkstot, nspin
    INTEGER, INTENT(IN) :: niter, nmix, stdout
    REAL(DP), INTENT(IN) :: tr2, ethr, mixing_beta
    INTEGER, INTENT(OUT) :: iter_out
    REAL(DP), INTENT(OUT) :: dr2_out, etot_out, time_ns_out
    LOGICAL, INTENT(OUT) :: conv_elec
    !
    TYPE(systemc_electrons_request) :: req
    TYPE(systemc_electrons_result) :: result
    INTEGER :: ierr
    !
    ! Fill request structure
    req%n_bands = nbnd
    req%n_basis = npwx
    req%n_kpoints = nkstot
    req%n_spin = nspin
    req%max_iterations = niter
    req%conv_threshold = tr2
    req%diag_threshold = ethr
    req%mixing_beta = mixing_beta
    req%mixing_ndim = nmix
    req%enable_cim = .TRUE.  ! Use CIM architecture
    !
    ! Call FPGA accelerator
    ierr = systemc_fpga_electrons(req, result)
    !
    IF (ierr /= 0) THEN
      WRITE(stdout, '(5X,"ERROR: FPGA electrons offload failed")')
      conv_elec = .FALSE.
      iter_out = 0
      dr2_out = 1.0D10
      etot_out = 0.0_DP
      time_ns_out = 0.0_DP
      RETURN
    ENDIF
    !
    ! Extract results
    conv_elec = result%converged
    iter_out = result%iterations
    dr2_out = result%final_error
    etot_out = result%total_energy
    time_ns_out = result%total_time_ns
    !
    ! Print timing information
    WRITE(stdout, '(5X,"FPGA execution time: ",F12.6," ms")') &
      time_ns_out / 1.0D6
    !
  END SUBROUTINE fpga_electrons_offload
  !
END MODULE fpga_systemc_interface
