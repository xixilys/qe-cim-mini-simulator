!
! Fortran Interface to SystemC FPGA Model
!
! This module provides Fortran bindings to the C wrapper for the SystemC
! DFT FPGA model, enabling direct integration with QE.
!
MODULE fpga_systemc_interface
  USE iso_c_binding
  IMPLICIT NONE
  
  PRIVATE
  PUBLIC :: fpga_init, fpga_electrons, fpga_c_bands, fpga_finalize
  PUBLIC :: systemc_electrons_request, systemc_electrons_result
  PUBLIC :: systemc_c_bands_request
  
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
  
  TYPE, BIND(C) :: systemc_electrons_result
    LOGICAL(C_BOOL) :: converged
    INTEGER(C_INT) :: iterations
    REAL(C_DOUBLE) :: final_error
    REAL(C_DOUBLE) :: total_energy
    REAL(C_DOUBLE) :: total_time_ns
  END TYPE systemc_electrons_result
  
  TYPE, BIND(C) :: systemc_c_bands_request
    INTEGER(C_INT) :: n
    INTEGER(C_INT) :: m
    INTEGER(C_INT) :: k
  END TYPE systemc_c_bands_request
  
  INTERFACE
    FUNCTION systemc_fpga_init_c(architecture) BIND(C, NAME='systemc_fpga_init')
      USE iso_c_binding
      INTEGER(C_INT) :: systemc_fpga_init_c
      CHARACTER(KIND=C_CHAR), DIMENSION(*) :: architecture
    END FUNCTION systemc_fpga_init_c
    
    FUNCTION systemc_fpga_electrons_c(req, result) BIND(C, NAME='systemc_fpga_electrons')
      USE iso_c_binding
      IMPORT :: systemc_electrons_request, systemc_electrons_result
      INTEGER(C_INT) :: systemc_fpga_electrons_c
      TYPE(systemc_electrons_request), INTENT(IN) :: req
      TYPE(systemc_electrons_result), INTENT(OUT) :: result
    END FUNCTION systemc_fpga_electrons_c
    
    FUNCTION systemc_fpga_c_bands_c(req) BIND(C, NAME='systemc_fpga_c_bands')
      USE iso_c_binding
      IMPORT :: systemc_c_bands_request
      INTEGER(C_INT) :: systemc_fpga_c_bands_c
      TYPE(systemc_c_bands_request), INTENT(IN) :: req
    END FUNCTION systemc_fpga_c_bands_c
    
    SUBROUTINE systemc_fpga_finalize_c() BIND(C, NAME='systemc_fpga_finalize')
    END SUBROUTINE systemc_fpga_finalize_c
    
    FUNCTION systemc_fpga_get_error_c() BIND(C, NAME='systemc_fpga_get_error')
      USE iso_c_binding
      TYPE(C_PTR) :: systemc_fpga_get_error_c
    END FUNCTION systemc_fpga_get_error_c
  END INTERFACE
  
CONTAINS

  SUBROUTINE fpga_init(architecture, ierr)
    CHARACTER(LEN=*), INTENT(IN) :: architecture
    INTEGER, INTENT(OUT) :: ierr
    CHARACTER(LEN=LEN_TRIM(architecture)+1, KIND=C_CHAR) :: c_arch
    
    c_arch = TRIM(architecture) // C_NULL_CHAR
    ierr = systemc_fpga_init_c(c_arch)
    
    IF (ierr /= 0) THEN
      CALL print_fpga_error()
    END IF
  END SUBROUTINE fpga_init
  
  SUBROUTINE fpga_electrons(req, result, ierr)
    TYPE(systemc_electrons_request), INTENT(IN) :: req
    TYPE(systemc_electrons_result), INTENT(OUT) :: result
    INTEGER, INTENT(OUT) :: ierr
    
    ierr = systemc_fpga_electrons_c(req, result)
    
    IF (ierr /= 0) THEN
      CALL print_fpga_error()
    END IF
  END SUBROUTINE fpga_electrons
  
  SUBROUTINE fpga_c_bands(req, ierr)
    TYPE(systemc_c_bands_request), INTENT(IN) :: req
    INTEGER, INTENT(OUT) :: ierr
    
    ierr = systemc_fpga_c_bands_c(req)
    
    IF (ierr /= 0) THEN
      CALL print_fpga_error()
    END IF
  END SUBROUTINE fpga_c_bands
  
  SUBROUTINE fpga_finalize()
    CALL systemc_fpga_finalize_c()
  END SUBROUTINE fpga_finalize
  
  SUBROUTINE print_fpga_error()
    TYPE(C_PTR) :: c_str_ptr
    CHARACTER(LEN=256), POINTER :: f_str
    
    c_str_ptr = systemc_fpga_get_error_c()
    IF (C_ASSOCIATED(c_str_ptr)) THEN
      CALL C_F_POINTER(c_str_ptr, f_str)
      WRITE(*,'(A,A)') 'FPGA Error: ', TRIM(f_str)
    END IF
  END SUBROUTINE print_fpga_error

END MODULE fpga_systemc_interface
