PROGRAM test_fpga_interface
  USE fpga_systemc_interface
  IMPLICIT NONE
  
  TYPE(systemc_electrons_request) :: req
  TYPE(systemc_electrons_result) :: result
  TYPE(systemc_c_bands_request) :: c_bands_req
  INTEGER :: ierr
  
  WRITE(*,'(A)') '========================================='
  WRITE(*,'(A)') 'Testing SystemC FPGA Interface'
  WRITE(*,'(A)') '========================================='
  WRITE(*,*)
  
  WRITE(*,'(A)') 'Test 1: Initialize FPGA with F2 architecture'
  CALL fpga_init('F2', ierr)
  IF (ierr /= 0) THEN
    WRITE(*,'(A)') 'FAILED: Could not initialize FPGA'
    STOP 1
  END IF
  WRITE(*,'(A)') 'SUCCESS: FPGA initialized'
  WRITE(*,*)
  
  WRITE(*,'(A)') 'Test 2: Execute single c_bands computation'
  c_bands_req%n = 32
  c_bands_req%m = 128
  c_bands_req%k = 1
  CALL fpga_c_bands(c_bands_req, ierr)
  IF (ierr /= 0) THEN
    WRITE(*,'(A)') 'FAILED: c_bands execution failed'
    STOP 1
  END IF
  WRITE(*,'(A)') 'SUCCESS: c_bands completed'
  WRITE(*,*)
  
  WRITE(*,'(A)') 'Test 3: Execute complete electrons loop'
  req%n_bands = 32
  req%n_basis = 128
  req%n_kpoints = 1
  req%n_spin = 1
  req%max_iterations = 10
  req%conv_threshold = 1.0D-8
  req%diag_threshold = 1.0D-10
  req%mixing_beta = 0.7D0
  req%mixing_ndim = 8
  req%enable_cim = .TRUE.
  
  CALL fpga_electrons(req, result, ierr)
  IF (ierr /= 0) THEN
    WRITE(*,'(A)') 'FAILED: electrons loop execution failed'
    STOP 1
  END IF
  
  WRITE(*,'(A)') 'SUCCESS: electrons loop completed'
  WRITE(*,'(A,L1)') '  Converged: ', result%converged
  WRITE(*,'(A,I0)') '  Iterations: ', result%iterations
  WRITE(*,'(A,ES12.4)') '  Final error: ', result%final_error
  WRITE(*,'(A,F12.6)') '  Total energy: ', result%total_energy
  WRITE(*,'(A,F12.3,A)') '  Total time: ', result%total_time_ns * 1.0D-6, ' ms'
  WRITE(*,*)
  
  WRITE(*,'(A)') 'Test 4: Finalize FPGA'
  CALL fpga_finalize()
  WRITE(*,'(A)') 'SUCCESS: FPGA finalized'
  WRITE(*,*)
  
  WRITE(*,'(A)') '========================================='
  WRITE(*,'(A)') 'All tests passed!'
  WRITE(*,'(A)') '========================================='
  
END PROGRAM test_fpga_interface
