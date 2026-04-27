!
! Simplified test program to demonstrate QE electrons() with FPGA offload
!
PROGRAM test_qe_fpga_offload
  !
  USE fpga_systemc_interface
  USE, INTRINSIC :: iso_fortran_env, ONLY : output_unit
  !
  IMPLICIT NONE
  !
  INTEGER, PARAMETER :: DP = SELECTED_REAL_KIND(14, 200)
  !
  ! QE-like parameters
  INTEGER :: nbnd, npwx, nkstot, nspin
  INTEGER :: niter, nmix
  INTEGER :: iter_out, ierr, stdout
  REAL(DP) :: tr2, ethr, mixing_beta
  REAL(DP) :: dr2_out, etot_out, fpga_time_ns
  LOGICAL :: conv_elec
  !
  INTEGER :: ierr, stdout
  !
  stdout = output_unit
  !
  WRITE(stdout, '(A)') '========================================='
  WRITE(stdout, '(A)') 'QE electrons() with FPGA Offload Test'
  WRITE(stdout, '(A)') '========================================='
  WRITE(stdout, '(A)') ''
  !
  ! Initialize FPGA with F2 architecture
  !
  WRITE(stdout, '(A)') 'Step 1: Initialize FPGA accelerator'
  CALL fpga_init('F2', ierr)
  !
  IF (ierr /= 0) THEN
    WRITE(stdout, '(A)') 'ERROR: Failed to initialize FPGA'
    STOP 1
  ENDIF
  !
  WRITE(stdout, '(A)') '  SUCCESS: FPGA initialized with F2 architecture'
  WRITE(stdout, '(A)') ''
  !
  ! Set up test case (similar to si8 workload)
  !
  nbnd = 32          ! 32 bands
  npwx = 128         ! 128 basis functions
  nkstot = 1         ! 1 k-point
  nspin = 1          ! non-spin-polarized
  niter = 100        ! max 100 SCF iterations
  tr2 = 1.0D-8       ! energy convergence threshold
  ethr = 1.0D-9      ! diagonalization threshold
  mixing_beta = 0.7D0  ! mixing parameter
  nmix = 8           ! mixing dimension
  !
  WRITE(stdout, '(A)') 'Step 2: Set up test case (si8-like)'
  WRITE(stdout, '(A,I6)') '  Number of bands:      ', nbnd
  WRITE(stdout, '(A,I6)') '  Basis size:           ', npwx
  WRITE(stdout, '(A,I6)') '  Number of k-points:   ', nkstot
  WRITE(stdout, '(A,I6)') '  Number of spins:      ', nspin
  WRITE(stdout, '(A,I6)') '  Max SCF iterations:   ', niter
  WRITE(stdout, '(A,ES12.4)') '  Convergence threshold:', tr2
  WRITE(stdout, '(A)') ''
  !
  ! Execute electrons loop on FPGA
  !
  WRITE(stdout, '(A)') 'Step 3: Execute electrons() loop on FPGA'
  WRITE(stdout, '(A)') ''
  !
  CALL fpga_electrons_offload( &
      nbnd, npwx, nkstot, nspin, &
      niter, tr2, ethr, &
      mixing_beta, nmix, &
      iter_out, dr2_out, conv_elec, etot_out, fpga_time_ns, stdout )
  !
  WRITE(stdout, '(A)') ''
  WRITE(stdout, '(A)') 'Step 4: Check results'
  !
  IF (conv_elec) THEN
    WRITE(stdout, '(A)') '  SUCCESS: SCF converged'
    WRITE(stdout, '(A,I6)') '    Iterations:   ', iter_out
    WRITE(stdout, '(A,ES12.4)') '    Final error:  ', dr2_out
    WRITE(stdout, '(A,F15.8)') '    Total energy: ', etot_out
  ELSE
    WRITE(stdout, '(A)') '  WARNING: SCF did not converge'
    WRITE(stdout, '(A,I6)') '    Iterations:   ', iter_out
    WRITE(stdout, '(A,ES12.4)') '    Final error:  ', dr2_out
  ENDIF
  !
  WRITE(stdout, '(A)') ''
  !
  ! Finalize FPGA
  !
  WRITE(stdout, '(A)') 'Step 5: Finalize FPGA accelerator'
  CALL fpga_finalize()
  WRITE(stdout, '(A)') '  SUCCESS: FPGA finalized'
  !
  WRITE(stdout, '(A)') ''
  WRITE(stdout, '(A)') '========================================='
  WRITE(stdout, '(A)') 'Test completed successfully!'
  WRITE(stdout, '(A)') '========================================='
  !
END PROGRAM test_qe_fpga_offload
