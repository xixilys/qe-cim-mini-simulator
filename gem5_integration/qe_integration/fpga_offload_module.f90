MODULE fpga_offload_module
  USE kinds, ONLY : DP
  USE iso_c_binding
  IMPLICIT NONE
  
  PRIVATE
  PUBLIC :: fpga_available, fpga_c_bands_compute, fpga_init_device, fpga_cleanup_device
  
  TYPE, BIND(C) :: fpga_device_t
    INTEGER(C_INT) :: fd
    TYPE(C_PTR) :: mmio_base
    INTEGER(C_SIZE_T) :: mmio_size
    LOGICAL(C_BOOL) :: initialized
  END TYPE fpga_device_t
  
  TYPE, BIND(C) :: fpga_c_bands_request_t
    INTEGER(C_INT32_T) :: n
    INTEGER(C_INT32_T) :: m
    INTEGER(C_INT32_T) :: k
    INTEGER(C_INT64_T) :: h_matrix_addr
    INTEGER(C_INT64_T) :: s_matrix_addr
    INTEGER(C_INT64_T) :: result_addr
  END TYPE fpga_c_bands_request_t
  
  TYPE(fpga_device_t), SAVE :: global_fpga_device
  LOGICAL, SAVE :: device_initialized = .FALSE.
  
  INTERFACE
    FUNCTION fpga_is_available_c() BIND(C, name='fpga_is_available')
      USE iso_c_binding
      LOGICAL(C_BOOL) :: fpga_is_available_c
    END FUNCTION fpga_is_available_c
    
    FUNCTION fpga_init_c(dev, device_path) BIND(C, name='fpga_init')
      USE iso_c_binding
      IMPORT :: fpga_device_t
      TYPE(fpga_device_t) :: dev
      TYPE(C_PTR), VALUE :: device_path
      INTEGER(C_INT) :: fpga_init_c
    END FUNCTION fpga_init_c
    
    SUBROUTINE fpga_cleanup_c(dev) BIND(C, name='fpga_cleanup')
      USE iso_c_binding
      IMPORT :: fpga_device_t
      TYPE(fpga_device_t) :: dev
    END SUBROUTINE fpga_cleanup_c
    
    FUNCTION fpga_c_bands_offload_c(dev, req, h_matrix, s_matrix, result_matrix) &
             BIND(C, name='fpga_c_bands_offload')
      USE iso_c_binding
      IMPORT :: fpga_device_t, fpga_c_bands_request_t
      TYPE(fpga_device_t) :: dev
      TYPE(fpga_c_bands_request_t) :: req
      TYPE(C_PTR), VALUE :: h_matrix
      TYPE(C_PTR), VALUE :: s_matrix
      TYPE(C_PTR), VALUE :: result_matrix
      INTEGER(C_INT) :: fpga_c_bands_offload_c
    END FUNCTION fpga_c_bands_offload_c
  END INTERFACE
  
CONTAINS
  
  FUNCTION fpga_available() RESULT(available)
    LOGICAL :: available
    available = fpga_is_available_c()
  END FUNCTION fpga_available
  
  SUBROUTINE fpga_init_device()
    INTEGER :: status
    IF (.NOT. device_initialized) THEN
      status = fpga_init_c(global_fpga_device, C_NULL_PTR)
      IF (status == 0) THEN
        device_initialized = .TRUE.
      END IF
    END IF
  END SUBROUTINE fpga_init_device
  
  SUBROUTINE fpga_cleanup_device()
    IF (device_initialized) THEN
      CALL fpga_cleanup_c(global_fpga_device)
      device_initialized = .FALSE.
    END IF
  END SUBROUTINE fpga_cleanup_device
  
  SUBROUTINE fpga_c_bands_compute(npw, npwx, nbnd, h_psi, s_psi, et, evc)
    INTEGER, INTENT(IN) :: npw, npwx, nbnd
    COMPLEX(DP), INTENT(IN) :: h_psi(npwx, nbnd)
    COMPLEX(DP), INTENT(IN) :: s_psi(npwx, nbnd)
    REAL(DP), INTENT(OUT) :: et(nbnd)
    COMPLEX(DP), INTENT(INOUT) :: evc(npwx, nbnd)
    
    TYPE(fpga_c_bands_request_t) :: req
    INTEGER :: status
    
    IF (.NOT. device_initialized) THEN
      CALL fpga_init_device()
    END IF
    
    IF (.NOT. device_initialized) THEN
      WRITE(*,*) 'ERROR: FPGA device not initialized'
      RETURN
    END IF
    
    req%n = nbnd
    req%m = npw
    req%k = 1
    req%h_matrix_addr = 0
    req%s_matrix_addr = 0
    req%result_addr = 0
    
    status = fpga_c_bands_offload_c(global_fpga_device, req, &
                                    C_LOC(h_psi), C_LOC(s_psi), C_LOC(et))
    
    IF (status /= 0) THEN
      WRITE(*,*) 'ERROR: FPGA c_bands offload failed'
    END IF
    
  END SUBROUTINE fpga_c_bands_compute
  
END MODULE fpga_offload_module
