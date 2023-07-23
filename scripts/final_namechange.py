#!/usr/bin/env python
#------------------------------------------------------------------------------
# call: grim/scripts/copy_log_files.py --project=su2020 --grid_id=35469055[,xxxxxx,[yyy]]
#       can specify a list of comma-separated grid ID's (need to go in the right order)
#------------------------------------------------------------------------------

import subprocess, shutil, json, copy
import sys, string, getopt, glob, os, time, re, array
import tempfile

import grid_job
#------------------------------------------------------------------------------
class MovejsonFile:

    def __init__(self):
        self.fProject       = None
        self.fProjectDir    = None
        self.fFamilyID      = 'xxx_xxxx' # just to make up 
        self.fFileTypes     = 'art.json'      # or 'log,fcl' , comma-separated

        self.fUser          = os.getenv('USER')
        self.fGridIDList    = None;

        self.fOutputPath    = {}
        self.fOutputStreams = None

        self.fVerbose       = 0

        self.fRunningDir    = None;
        self.fCompletedDir  = None;
        self.fGridJob       = None;

        self.fUseRunningDir = 1
# ---------------------------------------------------------------------
    def Print(self,Name,level,Message):
        if(level>self.fVerbose): return 0;
        now     = time.strftime('%Y/%m/%d %H:%M:%S',time.localtime(time.time()))
        message = now+' [ RenameJsonFilename::'+Name+' ] '+Message
        print(message)
        
#----------------------------------------------------------------------
# Parse the command-line parameters.
# the only required one is --project=$Project which defines the tiki page
# where the rest of the parameters can be found.  
# --verbose=0 only print necessary error messages etc.
# --verbose=1 (default) print some summary of what was done
# --verbose=2 print detailed summary of what was done
# --verbose=10 dump everything
#------------------------------------------------------------------------------
    def ParseParameters(self):
        name = 'ParseParameters'
        
        self.Print(name,2,'Starting')
        self.Print(name,2, '%s' % sys.argv)

        try:
            optlist, args = getopt.getopt(sys.argv[1:], '',
                                          ['project=', 'verbose=', 'grid_id=', 'use-running-dir='] )
 
        except getopt.GetoptError:
            self.Print(name,0,'%s' % sys.argv)
            self.Print(name,0,'Errors arguments did not parse')
            return 110

        for key, val in optlist:

            # print('key,val = ',key,val)

            if key == '--project':
                self.fProject = val
            elif key == '--grid_id':
                self.fGridIDList = val.split(',')
            elif key == '--use-running-dir':
                self.fUseRunningDir = int(val)
            elif key == '--verbose':
                self.fVerbose = int(val)

        self.fRunningDir   = 'tmp/'+self.fProject+'/grid_job_status';
        self.fCompletedDir = 'tmp/'+self.fProject+'/completed_jobs'

        self.Print(name,1,'Done')
        return 0

#------------------------------------------------------------------------------
# check if segment completed successfuly, return: 0 if OK, non-zero if not OK
# so far, a placeholder
#------------------------------------------------------------------------------
    def check_segment(self,subdirectory):
        return 0;

#------------------------------------------------------------------------------
# 'job': of grid_job.GridJob type 
#------------------------------------------------------------------------------
    def movejson_file(self,job):
        name = 'rename_art_files'

        topdir = job.grid_output_dir();
        odir   = job.grid_output_dir()

        if (job.fileset()):
            odir=odir+'/'+job.fileset()
        print('odir:',odir)
        if (not os.path.exists(odir)): os.makedirs(odir,exist_ok=True);

        print('odir:',odir)
        #------------------------------------------------------------------------------
        # file_types is either 'art' (default) or 'art,json' etc
        #------------------------------------------------------------------------------
        file_types = self.fFileTypes.split(',');
        extracted_parts = []
        for ext in file_types:
            if (ext == 'art.json')  :
               # oodir = odir+'/'+ext;
               oodir = odir;
               if (not os.path.exists(oodir)): os.makedirs(oodir,exist_ok=True)

               list_of_dirs = glob.glob(topdir+'/*')
               list_of_dirs.sort()

               self.Print(name,1,'list_of_dirs:%s'%format(list_of_dirs));

               for sd1 in list_of_dirs:
                  print('sd1:',sd1)
                  ld1 = glob.glob(sd1+'/*')
                  ld1.sort()
                  for sd2 in ld1: 
                     self.Print(name,1,'sd2=%s'%sd2);
                     #------------------------------------------------------------------------------
                     # skip subdirectories like 00148.915da673
                     dbn = os.path.basename(sd2);
                     full_access_permission = 0o700
                     
                     print(dbn)
                     if (len(dbn.split('.')) == 1) :
                        # at this point, need to check whether the segment has completed successfully
                        # do not copy files for failed segments
                        # 'rc' is the return code, 0 if evethything is fine 
                        rc = self.check_segment(sd2);
                        keyword_to_check = ".art.modified"
                        destination_file = '/mu2e/data/users/namithac/destination_file.json'
                        if (rc == 0):
                           for fn in glob.glob(sd2+'/*.'+ext) :
                               input_file = os.path.basename(fn)
                               if keyword_to_check in input_file:
                                  new_filename = input_file.replace(".art.modified", "")
                                  print(sd2)
                                  print(new_filename)
                                  new_file_path = os.path.join(sd2, new_filename)
                                  os.rename(fn, new_file_path)
                        else:
                            print('skip failed segment , subdirectory:',sd2)
                     else:
                        print('in trouble: %s'%fn)
        
        #------------------------------------------------------------------------------
        # done, update the job status
        #------------------------------------------------------------------------------
        job.fStatus |= grid_job.kLogsCopiedBit;

 
#------------------------------------------------------------------------------
# main program, just make a GridSubmit instance and call its methods
#------------------------------------------------------------------------------
if (__name__ == '__main__'):

    x = MovejsonFile()
    x.ParseParameters()

    for item in x.fGridIDList:

        grid_id = item.split('@')[0]

        # read job status file
        if (x.fUseRunningDir == 1): fn = x.fRunningDir  +'/'+grid_id;
        else                      : fn = x.fCompletedDir+'/'+grid_id;

        job   = grid_job.GridJob(fn);

        doit = True;
        if (job.fStatus & grid_job.kLogsCopiedBit):
            # check if still want to proceed
            print('>>> log files of job grid_id=',grid_id,' have already been copied, do you want to proceed ? [y/n]')
            s = str(input())
            if (s[0] != 'y'): 
                doit = False;
            
        if (doit): 
            x.movejson_file(job)
            #------------------------------------------------------------------------------
            # done, update job status file with updated status
            #------------------------------------------------------------------------------
            fn_new = fn+'.tmp'
            rc     = job.write_status_file(fn_new);
            if (rc == 0): os.replace(fn_new,fn);

    sys.exit(0);
