#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@author: Kimmo Sääskilahti
ksaaskil@gmail.com

Made some modifications by Liang Ting
liangting.zj@gmail.com
2020/2/7 14:21:55
"""

from __future__ import division, print_function
import numpy as np
import sys

__all__ = ["SHCPostProc"]

class SHCPostProc(object):
    """
    Compute the spectral decomposition of heat current from the data
    produced using LAMMPS MD simulation.
    
    The velocities are read from the "compact" file produced with the C++-code
    compactify_vels.cpp from a LAMMPS dump file. If the dump file does not exist,
    it is produced by calling the binary ``compactify_vels``,
    which must be found in the environment's ``$PATH``.
    
    Minimal usage in Python::
        pP = SHCPostProc(Compact_VelocityFile, Kij_FilePrefix)    *** Gets all the attributes in the class ***
        pP.postProcess() # Calculate the heat current spectrum    
        
    Public attributes::
        - SHC_smooth (numpy float array): The chunk-averaged, smoothened spectral heat current
        - SHC_smooth2 (numpy float array): Square of the chunk-averaged, smoothened spectral heat current, used for estimating the error from the between-chunk variance
        - SHC_average (numpy float array): The chunk-averaged spectral heat current without smoothing
        - SHC_error (numpy float array): The estimated error from the between-chunk variance, None if only one chunk evaluated
        - oms_fft (numpy float array): The angular frequency grid (in the units of Hz if dt_md is given in the units of seconds in the initialization)
        
    :param Compact_VelocityFile: Path to file from where the velocities are read. Produced using the binary compactify_vels if the file does not exist. In this case, you must also supply the keyword argument LAMMPSDumpFile containing the velocities produced using LAMMPS.
    :type Compact_VelocityFile: str
    :param Kij_FilePrefix: The prefix used in trying to find the force constant matrix file Kij_FilePrefix.Kij.npy. If the file does not exist, the force constant calculator fcCalc is called using the keyword argument LAMMPSInFile (which must be supplied in this case).
    :type KijFilePrefix: str
    :param reCalcVels: Force recreation of the compact velocity file if True, defaults to False
    :type reCalcVels: boolean, optional
    :param reCalcFC: Re-calculate force constants if True, defaults to False
    :type reCalcFC: boolean, optional
    :param args: Additional keyword arguments
    
    Additional attributes:: 
    **** For different direction spectral SHC **** (Added by liang ting)
    :param in_plane: In_plane direction spectral current is to calculate. In my case, the in_plane direction includes the X and Y directions(unit box), which can be modified as needed.
    :type in_plane: boolean, optional
    :param out_of_plane: Out_of_plane direction spectral current is to calculate. In my case, the out_of_plane direction includes the Z direction(unit box), which can be modified as needed.
    :type in_plane: boolean, optional
    
    Additional keyword arguments::
           - dt_md (float): Timestep used in the NEMD simulation (seconds), used for inferring the sampling timestep and the frequency grid (default 1.0) (need to change from fs to s)
           - dn (float): The number of steps of velocities (Velocity sampling interval) in a LAMMPS. (default 10)
           - steps (float): The total number of steps of the output velocities in the LAMMPS. A MD simulation parameter (default 500000)
           - scaleFactor (float): Multiply the spectral heat current by this factor to convert to correct units (default 1.0)
           - LAMMPSDumpFile (str): Use this velocity dump file produced by LAMMPS for post-processing, needed only if the compact velocity file cannot be found (default None)
           - LAMMPSInFile (str): (1) Use this In_File for calculating the force constants if the force constant file cannot be found. 
                                 (2) This parameter is required if the force constant file does not exist (default None).
           - widthWin (float): Use this width for the smoothing window (Hz) (default 1.0) (1 THz = 1 × 10^12 Hz)
           - NChunks (int): The number of chunks to be read, this should be set to a sufficiently large value if the whole velocity file should be read (default 20)
           - chunkSize (int): (1) Used chunk size for reading the velocities, affects the frequency grid. 
                              (2) Performing FFT is faster if chunkSize is a power of 2.
                              (3) It affects the maximum frequency that can be reached 
                              (4) chunkSize = int(steps / dn / NChunks)
           - sampleTimestep (float): (1) This is the time interval in units of seconds between two frames of velocity data you save.
                                     (2) Its reciprocal divided by 2 is roughly the maximum frequency attainable.
           - backupPrefix (str): Prefix for pickling the post-processing object to a file after the read of each chunk (default None)
           - hstep (float): The displacement used in calculating the force constants by the finite-displacement method (default 0.01)
    """

    def __init__(self, Compact_VelocityFile, Kij_FilePrefix, in_plane=False, out_of_plane=False, reCalcVels=False, reCalcFC=False, **args):  
        
        self._tic()                                           # Compute run time
        
        # Attributes set by positional arguments
        self.compactVelocityFile = Compact_VelocityFile       # For velocity
        self.KijFilePrefix = Kij_FilePrefix                   # For atoms forces

        # Attributes set by keyword parameters below
        # MD Attributes
        self.dt_md = 1.0                                      # Default
        self.dn = 10                                          # frequency velocities are printed (Default)
        self.steps = 500000                                   # number of simulation steps (Default)
        self.NChunks = 20                                     # Default

        self.scaleFactor = 1.0                                # Default (convert to J)
        self.LAMMPSDumpFile = None                            # LAMMPS dump file of Velocity
        self.LAMMPSInFile = None                              # LAMMPS input file (For generate the forces)
        self.widthWin = 1.0                                   # Default  (Hz) 
        self.hstep = 0.01                                     # Default (For calculate the force constant)
        self.reCalcVels = reCalcVels                          # Boolean
        self.reCalcFC = reCalcFC                              # Boolean
        self.backupPrefix = None                              # For backup

        self.in_plane = in_plane
        self.out_of_plane = out_of_plane                      # For different directions
        
        # Other attributes (For calculate) (Will be assigned in the program)
        self.Kij = None      
        self.ids_L = None
        self.ids_R = None
        self.NL = None
        self.NR = None
        self.inds_interface = None                            # Used to compare with the atomic index in the dump_velovity file
        
        self.velsL = None                                     # It stores the atomic velocity on the left
        self.velsR = None                                     # It stores the atomic velocity on the right
        
        self.SHC_smooth = None
        self.SHC_smooth2 = None
        self.SHC_average = None
        self.SHC_error = None
        self.oms_fft = None

        for key, value in args.items():
            if not hasattr(self, key):
                raise AttributeError("Invalid argument " + key + " to PostProc!")
            print("\nUsing the value " + key + " = " + str(value) + ".")
            setattr(self, key, value)
        
        # MD attributes that need to be defined based on the input attributes    
        # MD Attributes   
        
        self.chunkSize = int(self.steps/self.dn/self.NChunks)
        
        '''
        This is the time interval in units of seconds between two frames of velocity data you save.
        It should be small enough such that the maximum frequency in your system can be reached.
        (self.sampleTimestep) Its reciprocal divided by 2 is roughly the maximum frequency attainable.
        '''
        self.sampleTimestep = self.dt_md * self.dn                           # Effective timestep for velocity data
        
        print('\nEffective timestep for velocity data is ' + str(self.sampleTimestep) + ' (s)')
 
     
        import os
        if self.reCalcVels or not os.path.isfile(self.compactVelocityFile):  # Check if the velocity file exists
            # Check that the LAMMPS Dump file exists
            if self.LAMMPSDumpFile is None or not os.path.isfile(self.LAMMPSDumpFile):
                raise ValueError("You must give the LAMMPS velocity dump file as an argument to create the file " + self.compactVelocityFile + "!")
                
            print ('\n' + self.compactVelocityFile + " is being generated, please wait.")
            # Run the C++ script
            self._compactVels(self.LAMMPSDumpFile, self.compactVelocityFile)

        else:
            print('\n' + self.compactVelocityFile + " exists, using the file for post-processing.")

        # Check the force constant file
        if self.reCalcFC or not os.path.isfile(self.KijFilePrefix + '.Kij.npy'):   # Check if the force constant file exists
            print("\nCreating file " + self.KijFilePrefix + ".")
            if self.LAMMPSInFile is None:
                raise ValueError("You must give the LAMMPSRestartFile as an argument so that the file " + self.KijFilePrefix + ".Kij.npy can be created!")
            self._calcFC(self.KijFilePrefix, self.LAMMPSInFile)
        else:  # Load the force constants from file
            self._loadFC(self.KijFilePrefix)

    def __enter__(self):
        return self

    def __exit__(self, t1, t2, t3):
        return False
        
    def _tic(self):
        """
        Same as MATLAB tic and toc functions. Use ty.tic() at the beginning of
        code you want to time and ty.toc() at the end. Once ty.toc() is reached,
        elapsted time will be printed to screen and optionally (by default) written
        to 'log.txt' file.
        """
        import time
        global startTime_for_tictoc
        startTime_for_tictoc = time.time()
        
    def _toc(self):
        """
        Same as MATLAB tic and toc functions. Use ty.tic() at the beginning of
        code you want to time and ty.toc() at the end. Once ty.toc() is reached,
        elapsted time will be printed to screen and optionally (by default) written
        to 'log.txt' file.
        """
        import time
        if 'startTime_for_tictoc' in globals():
            print(("\nThe time it takes to run the program is: "+
              str(np.round(time.time()-
                       startTime_for_tictoc,decimals=3))+" seconds."))
        else:
            print("\nToc: start time not set") 

    def _calcFC(self, fileprefix, LAMMPSInFile):
    	
        from force_calculate import fcCalc
        with fcCalc(fileprefix) as fc:
            fc.preparelammps(in_lammps = LAMMPSInFile, w_interface = 6.0)
            fc.fcCalc(self.hstep)
            fc.writeToFile()
            print('Force constant matrix file generate done')
            self.Kij = fc.Kij                                  # Reference (get Force constant matrix)
            print("\nSize of the Kij file is (3 * %d) x (3 * %d)." % (np.size(self.Kij, 0) / 3, np.size(self.Kij, 1) / 3)) # Get the number of rows(0) and columns(1) of a matrix
            self.ids_L = fc.ids_L                              # Reference (get the left interfacial atom indices)
            self.ids_R = fc.ids_R                              # Reference (get the right interfacial atom indices)
            self.NL = len(self.ids_L)                          # A number
            #print("len(ids_L) = %d" % self.NL)
            self.NR = len(self.ids_R)
            #print("len(ids_R) = %d" % self.NR)
            if (np.size(self.Kij, 0) / 3 != self.NL) or (np.size(self.Kij, 1) / 3 != self.NR):
                raise ValueError("Sizes in Kij and ids_L/R do not match!")
            
            self.inds_interface = fc.inds_interface            # Used to compare with the atomic index in the dump_velovity file
                 

    def _loadFC(self, KijFilePrefix):
    	
        print("\nLoading the force constants from " + KijFilePrefix + '.Kij.npy')
        self.Kij = np.load(KijFilePrefix + '.Kij.npy')
        print("\nSize of the Kij file is (3*%d)x(3*%d)." % (np.size(self.Kij, 0) / 3, np.size(self.Kij, 1) / 3))
        
        print("\nLoading left interfacial atom indices from " + KijFilePrefix + '.ids_L.npy')
        self.ids_L = np.load(KijFilePrefix + '.ids_L.npy')
        print("\nLoading right interfacial atom indices from " + KijFilePrefix + '.ids_R.npy')
        self.ids_R = np.load(KijFilePrefix + '.ids_R.npy')
        
        self.NL = len(self.ids_L)
        #print("\nlen(ids_L) = %d" % self.NL)
        self.NR = len(self.ids_R)
        #print("\nlen(ids_R) = %d" % self.NR)
        if (np.size(self.Kij, 0) / 3 != self.NL) or (np.size(self.Kij, 1) / 3 != self.NR):
            raise ValueError("Sizes in Kij and ids_L/R do not match!")
            
        # Used to compare with the atomic index in the dump_velovity file 
        print("\nLoading interface group\'s atom indices from " + KijFilePrefix + '.ids_Interface.npy') 
        self.inds_interface = np.load(KijFilePrefix + '.ids_Interface.npy')   
    
    def _compactVels(self, file_Vels, finalFile_Vels):
    	
        from subprocess import call
        command = ["compactify_vels", file_Vels, finalFile_Vels]
        print("\nRunning the " + '\"' + " ".join(command) + '\"' + ' command to generate the compact_velocity file.')
        call(command)

    def _smoothen(self, func, df, widthWin):
    	
        gwin = np.ceil(widthWin / df)                 # number of array elements in window
 	  
        if gwin % 2 == 0:                             # make sure its odd sized array
           gwin = gwin+1
           
        if gwin == 1:
        	 gauss = np.array([1])                      # if array is size 1, convolve with self

        else:
           n = 2*np.arange(0,gwin)/(gwin-1)-(1)       # centered at 0, sigma = 1
           n = (3*n)                                  # set width of profile to 6*sigma i.e. end values ~= 0
           gauss = np.exp(-np.multiply(n,n)/2.0)      # gaussian fx to convolve with
           gauss = gauss/np.sum(gauss)                # normalized gaussian
           
    	  # Smooth the value           
        smooth = np.convolve(func, gauss, mode = 'same')
        
        return smooth
    
    def _differ_direction(self):
    	
        if self.in_plane and not self.out_of_plane:
    	  	
    	  	 # Forces in_plane
    	  	 self.Kij[2::3, :] = 0                                      
    	  	 	
    	  	 # Velocity	in_plane                                         # Z-direction velocity
    	  	 self.velsL[2::3, :] = 0
    	  	 self.velsR[2::3, :] = 0                                     # The force and velocity in Z-direction set to zero
    	  	 
        elif self.out_of_plane and not self.in_plane:
    	  	
    	  	 # Forces out_of_plane                                       
           self.Kij[0::3, :] = 0                                       # The force and velocity in X-direction and Y-direction set to zero
           self.Kij[1::3, :] = 0
           	
           # Velocity	out_of_plane
           self.velsL[0::3, :] = 0                                     # X-direction velocity
           self.velsL[1::3, :] = 0                                     # Y-direction velocity (Left velocity)
           	
           self.velsR[0::3, :] = 0
           self.velsR[1::3, :] = 0                                     # Right velocity 	

        else:
        	 raise AttributeError('Can\'t calculate the spectral decomposition in different'
        	 ' directions at the same time')
    
    def postProcess(self):
        """
        Calculate the spectral decomposition and store to ``self.SHC_smooth``.
        :return: None
        """

        print("\nReading the compact velocity file " + self.compactVelocityFile + ".")
        fid = open(self.compactVelocityFile, 'r')
        s = fid.readline().strip().split()              # Read the Read the first line of the compact_velocity file
        Natoms = int(s[1])
        if Natoms != self.NL + self.NR:                 # Error checking (Use different error reporting methods)
            raise ValueError('Mismatch in the numbers of atoms '
                               'in the read velocity file and the used force constant file!')
        
        vel_sample_steps = int(fid.readline().strip().split()[1])       # velocity sample_steps in dump file
        if (vel_sample_steps * self.dt_md) != (self.sampleTimestep):    # Error checking
        	 sys.exit('SETTING ERROR: Different dump stride given in '
                 +str(self.compactVelocityFile))

        s = fid.readline()                              # skip comment (Atom ids:)
        #print('\n' + s)
        
        # Read the atom ids {Note that these indices (e.g. self.inds_interface) differ from atom IDs (in dump_velocity file) by a factor of one}
         
        indArray = np.fromfile(fid, dtype=int, count=Natoms, sep=" ")
   
        for j in range(Natoms):                                         # For error checking
            if (self.inds_interface[j] + 1) != int(indArray[j]):
               sys.exit('LAMMPS ERROR: ids in the vels_file don\'t match that in the force_file')

        s = fid.readline()                              # skip comment (------)
        #print(s)                                        # The file pointer stays here for now

        # Total number (in the interface group) of degrees of freedom
        
        NDOF = 3 * (self.NL + self.NR)
        
        '''
        numpy.fft.fftfreq(n, d=1.0)
        Return the Discrete Fourier Transform sample frequencies.
        f = [0, 1, ...,   n/2-1,     -n/2, ..., -1] / (d*n)   if n is even
        f = [0, 1, ..., (n-1)/2, -(n-1)/2, ..., -1] / (d*n)   if n is odd
        '''
        
        self.oms_fft = np.fft.rfftfreq(self.chunkSize, d=self.sampleTimestep) * 2 * np.pi
        Nfreqs = np.size(self.oms_fft)
        print('\nThe number of sampling frequencies is {0} and start to Chunk averaging process:'.format(Nfreqs))        

        # Initialize the spectral heat current arrays
        self.SHC_smooth = np.zeros(Nfreqs)
        self.SHC_smooth2 = np.zeros(Nfreqs)
        self.SHC_average = np.zeros(Nfreqs)

        exitFlag = False

        for k in np.arange(self.NChunks):            # Start the iteration over chunks (For average)
            # for k in range(0,2): (for test)        # Start the iteration over chunks
            print("\t\tChunk averaging process %d / %d" % (k + 1, self.NChunks))
            
            ## ************** Get velocities for each block *************
            # Read a chunk of velocitites
            
            velArray = np.fromfile(fid, dtype=np.dtype('f8'), count=self.chunkSize * NDOF, sep=" ")

            # Prepare for exit if the read size does not match the chunk size
            if np.size(velArray) == 0:
                print("Finished the file, exiting.")
                self.NChunks = k - 1
                break
            elif np.size(velArray) != self.chunkSize * NDOF:
                # Reaching the end of file           
                self.chunkSize = int(np.size(velArray) / NDOF)
                if k > 0:  # Not the first chunk
                    self.NChunks = k - 1
                    break
                else:
                    exitFlag = True
                    self.oms_fft = np.fft.rfftfreq(self.chunkSize, d=self.sampleTimestep) * 2 * np.pi
                    Nfreqs = np.size(self.oms_fft)
                    print("Changing chunk size to " + str(int(np.size(velArray) / NDOF)) + "!")

            # Reshape the array so that each row corresponds to different degree of freedom (e.g. particle 1, direction x, y, z etc.)
            
            velArray = np.reshape(velArray, (NDOF, self.chunkSize), order='F')    # Write in column order

            # FFT with respect to the second axis (NOTE THE USE OF RFFT)
            velFFT = np.fft.rfft(velArray, axis=1)                                 # axis = 0 for rows, axis = 1 for column 
            velFFT *= self.sampleTimestep
            
            self.velsL = np.zeros((3 * self.NL, Nfreqs), dtype = np.complex128)
            self.velsR = np.zeros((3 * self.NR, Nfreqs), dtype = np.complex128)
            
            ## Atoms on the left (self.ids_L is the left interfacial atom indices)
            
            self.velsL[0::3, :] = velFFT[3 * self.ids_L, :]                     # X-direction velocity
            self.velsL[1::3, :] = velFFT[3 * self.ids_L + 1, :]                 # Y-direction velocity 
            self.velsL[2::3, :] = velFFT[3 * self.ids_L + 2, :]                 # Z-direction velocity 

            ## Atoms on the right (self.ids_L is the right interfacial atom indices)
            
            self.velsR[0::3, :] = velFFT[3 * self.ids_R, :]                     # X-direction velocity
            self.velsR[1::3, :] = velFFT[3 * self.ids_R + 1, :]                 # Y-direction velocity
            self.velsR[2::3, :] = velFFT[3 * self.ids_R + 2, :]                 # Z-direction velocity
            	
            ## For different direction spectral SHC:
            if self.in_plane or self.out_of_plane:
            	
               self._differ_direction()

            # Spectral heat current for the specific chunk
            SHC = np.zeros(Nfreqs)
            
            '''
            In formula programming, the SHC here is already the sum of the left and right interface atoms
            '''
            for ki in range(1, Nfreqs):                                    # Skip the first one with zero frequency
                SHC[ki] = -2.0 * np.imag(np.dot(self.velsL[:, ki], np.dot(self.Kij, np.conj(self.velsR[:, ki])))) / self.oms_fft[ki]  # np.dot is the matrix product

            # Normalize correctly
            
            SHC /= (self.chunkSize * self.sampleTimestep)

            # Change units           

            SHC *= self.scaleFactor
            
            # Copy the SHC value before modifying it
            
            SHC_orig = SHC.copy()
            
            # Smooth the value           
            
            df = (self.oms_fft[1] - self.oms_fft[0]) / (2 * np.pi)     # Angular frequency, positive val (w is the angular frequency)
            SHC = self._smoothen(SHC, df, self.widthWin)

            # Time average
            if not exitFlag:                                           # If Nfreqs has changed, the running averaging cannot be performed
                self.SHC_smooth = (k * self.SHC_smooth + SHC) / (k + 1.0)
                # The square
                self.SHC_smooth2 = (k * self.SHC_smooth2 + SHC ** 2) / (k + 1.0)
                # The non-smoothened average
                self.SHC_average = (k * self.SHC_average + SHC_orig) / (k + 1.0)
                if self.backupPrefix is not None:
                    np.save(self.backupPrefix + '_backup_oms.npy', self.oms_fft)
                    np.save(self.backupPrefix + '_backup_SHC.npy', self.SHC_smooth)
                    import cPickle as pickle
                    with open(self.backupPrefix + '_run_PP.pckl', 'w') as pf:
                        pickle.dump(self, pf)
            elif exitFlag and k == 0:    # First chunk and new chunk size, needs re-initializing the vectors as Nfreqs may have changed
                self.SHC_smooth = SHC
                self.SHC_smooth2 = SHC ** 2
                self.SHC_average = SHC_orig
                self.NChunks = 1
                break
            else:                        # This should never be reached
                assert False, "SHCPostProc should not reach here (exitFlag=True and k>0)."

        # Calculate the error estimate at each frequency from the between-chunk variances
        
        if self.NChunks > 1:
            print("\nCalculating error estimates.")
            samplevar = (self.NChunks / (self.NChunks - 1.0)) * (self.SHC_smooth2 - self.SHC_smooth ** 2)
            self.SHC_error = np.sqrt(samplevar) / np.sqrt(self.NChunks)
            
            #print('\nThe estimated error of the between-chunk variance is {}.'.format(self.SHC_error))
            
        else:
            self.SHC_error = None

        print("\n********** Finished post-processing.**************")
        
        self._toc()
        
        
if __name__ == "__main__":
	
    fileprefix = 'Fij.dat'
    in_file = 'forces.in'                                        ## The in file for lammps
    atomic_velocities_file = 'vels.dat'
    compact_velocities_file = 'vels.compact.dat'
    frequency_window_width = 2e12                                ## Hz
    dn = 15
    
    #*************** eV/ps^2; 1 eV = 1.602e-19 J, 1 ps = 1e-12 s  ***************
    unit_scaling_factor = 1.602e-19 / 1e-20 * 1e4                ## convert: v*dF/du*v = [A/ps]*[eV/A]/[A]*[A/ps]  
    
    md_timestep = 0.5e-15                                        ## second
    area = 62.119 * 3.35                                         ## A^2, it depends on your case 
    Tem_jump = 19.3                                              ## 60K is the temperature jump
    Kb = 1.380649e-23                                            ## Boltzmann's constant, J/K
    
    postprocessor = SHCPostProc(compact_velocities_file,
                                fileprefix,
                                dt_md = md_timestep,
                                dn = dn,
                                scaleFactor = unit_scaling_factor,
                                LAMMPSDumpFile = atomic_velocities_file,
                                widthWin = frequency_window_width,
                                LAMMPSInFile = in_file,
                                in_plane = False,
                                out_of_plane = False,
                                reCalcVels = True,
                                reCalcFC = True)
                                
    postprocessor.postProcess()
    
    # Plotting if available
    
    import matplotlib.pylab as plt
    import scipy.integrate as sci                                                    # For calculate the area 
    
    # Unit conversion
    x_Frequency = postprocessor.oms_fft/(2*np.pi*1.0e12)                             # Conversion from Hz to THz
    
    # The unit of heat currents is Joule (J), which is W / Hz 
    # Calculate the Spectral thermal conductance
    y_ITC = postprocessor.SHC_smooth / (1.0e-12 * area * 1.0e-20 * Tem_jump * 1.0e9) # From W to GW (/1.0e9)
    
    # Calculate the phonon transmission T(w)                           
    T_w = postprocessor.SHC_smooth / (Kb * Tem_jump)                 # Dimensionless
    
    # Calculate the accumulated thermal conductance
    Freq_number = len(x_Frequency)
    accumulated_ITC = []
    accumulated_count = 0
    
    for i in range(Freq_number):
        accumulated_count = sci.trapz(y_ITC[0:i], x_Frequency[0:i])
        accumulated_ITC.append(accumulated_count)
    
    print('\nThe accumulated thermal conductance is ' + str(accumulated_count) + ' (GW/m^2/K)')
     
    # Save the frequencies and smoothened spectral heat currents to text file
    np.savetxt('frequencies_and_ITC.txt', np.column_stack((x_Frequency, y_ITC)))
    np.savetxt('frequencies_accumulated_ITC.txt', np.column_stack((x_Frequency, accumulated_ITC)))
    
    
    # *************************** Plotting ************************* (It can be reduced to a graph function)
    # Phonon transmission T(w)
    plt.plot(x_Frequency, T_w, '-', linewidth=3, label="Interfacial Phonon Transmission")   
    plt.xlabel('w/(2*pi) (THz)')
    plt.ylabel('Transmission')
    plt.xlim(0, max(x_Frequency))                             # Frequency range
    plt.ylim(0, max(T_w) + 5)                                 # It depends on your case
    plt.legend(fontsize=15, loc='best')          
    plt.savefig(fileprefix+'_Tw.png')
    plt.show()
    
    # Spectral thermal conductance
    plt.plot(x_Frequency, y_ITC, '-', linewidth = 3, label="Spectral thermal conductance")   
    plt.xlabel('w/(2*pi) (THz)')
    plt.ylabel('G(w) (GW/m^2/K/THz)')
    plt.xlim(0, max(x_Frequency))                             # Frequency range
    plt.ylim(0, max(y_ITC)+(max(y_ITC)/5))                    # It depends on your case
    print('\nThe total thermal conductance is (total area)' + str(sci.trapz(y_ITC, x_Frequency)) + ' (GW/m^2/K)\n')   
    plt.legend(fontsize=15, loc='best')          
    plt.savefig(fileprefix+'_SHC.png')
    plt.show()
    
    # Spectral accumulated thermal conductance
    plt.plot(x_Frequency, accumulated_ITC, 'm', linewidth = 3, label="Accumulated thermal conductance") 
    plt.xlabel('w/(2*pi) (THz)')
    plt.ylabel('G(w) (GW/m^2/K)')
    plt.xlim(0, max(x_Frequency))                             # Frequency range
    plt.ylim(0, accumulated_count + 1)                        # It depends on your case
    plt.legend(fontsize=15, loc='best')
    plt.savefig(fileprefix+'_accumulated_ITC.png')
    plt.show()