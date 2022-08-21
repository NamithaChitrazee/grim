#!/bin/env python
#
# a script to discover metadata about a file
# and write out a json file summary suitable to passing to SAM
# -h print help
#

# needed to run in py2 and py3
from __future__ import  print_function

import os
import re
import sys
import getopt
import json
import subprocess
import traceback
import time
import hashlib
import string
import tempfile

##############################################################
# print the help
##############################################################

def printHelp():
    print( """
jsonMaker  [OPTIONS] ... [FILES] ...

  Create json files which hold metadata information about the file
to be uploaded. The file list can contain data, and other types,
of files (foo.bar) to be uploaded.  If foo.bar.json is in the list, 
its contents will be added to the json for foo.bar.
If a generic json file is supplied, it's contents will be
added to all output json files.  Output is a json file for each input 
file, suitable to presenting to the upload FTS server together with 
the data file.
   If the input file is an art file, jsonMaker must run
a module over the file in order to extract run and event
information, so a mu2e offline release that contains the module
must be setup.

   -h 
       print help
   -v LEVEL
       verbose level, 0 to 10, default=1
   -x 
       perform write/copy of files.  Default is to evaluate the
       upload parameters, but not not write or move anything.
   -c
       copy the data file to the upload area after processing
       Will move the json file too, unless overidden by an explicit -d.
   -m
       mv the data file to the upload area after processing. 
       Useful if the data file is already in
       /pnfs/mu2e/scratch where the FTS is.
       Will move the json file too, unless overidden by an explicit -d.
   -e
       just rename the data file where it is
   -s FILE
       FILE contains a list of input files to operate on.
   -p METHOD
      How to match a input json file to a data file
      METHOD="none" for no json input file for each data file (default)
      METHOD="file" pair an input json file with a data file based on the 
      fact that if the file is foo, the json is foo.json.
      METHOD="dir" pair a json file and a data file based on the fact that 
      they are in the same directory, whatever their names are.
   -j FILE
       a json file fragment to add to the json for all files,
       typically used to supply MC parameters.
   -i PAR=VALUE
       a json file entry to add to the json for all files, like
        -i mc.primary_particle=neutron
        -i mc.primary_particle="neutron"  
        -i mc.simulation_stage=2 
       Can be repeated.  Will supersede values given in -j
   -a FILE
       a text file with parent file sam names - usually would only
       be used if there was one data file to be processed.
   -t TAG
       text to prepend to the sequencer field of the output filename.
       This can be useful for non-art datasets which have different
       components uploaded at different times with different jsonMaker 
       commands, but intended to be in the same dataset, such as a series
       of backup tarballs from different stages of processing.
   -d DIR
       directory to write the json files in.  Default is ".".
       If DIR="same" then write the json in the same directory as the 
       the data file. If DIR="fts" then write it to the FTS directory. 
       If -m or -c is set, then -d "fts" is implied unless overidden by 
       an explicit -d.
   -f FILE_FAMILY
       the file_family for these files - required
   -r NAME
       this will trigger renaming the data files by the pattern in NAME
       example: -r mcs.batman.beam-2014.fcl-100..art
       The blank sequencer ".." will be replaced by a sequence number 
       like ".0001." or first run and subrun for art files.
   -l DIR
       write a file of the data file name and json file name
       followed by the fts directory where they should go, suitable
       for driving a "ifdh cp -f" command to move all files in one lock.
       This file will be named for the dataset plus "command" 
        plus a time string.
   -g 
       the command file will be written (implies -l) and then
       when all files are evaluated and json files written, execute
       the command file with "ifdh cp -f commandfile". Useful
       to use one lock file to execute all ifdh commands.
       Nullifies -c and -m.

  Requires python 2.7 or greater for subprocess.check_output and 
     2.6 or greater for json module.
  version 2.3
    """)

##############################################################
# class to hold the command line settings
##############################################################

class Parms:
    def __init__(self):
        self.execute = False
        self.executeF = False
        self.verbose = int(1)
        self.inFile = ""
        self.genericJson = {}
        self.jsonDir = ""
        self.parentTxt = ""
        self.seqTag = ""
        self.comDir = ""
        self.copy = False
        self.move = False
        self.groupCp = False
        self.inPlace = False
        self.pair = "none"
        self.reName = ""
        self.file_family = ""
        self.fts  = "/pnfs/mu2e/scratch/fts"
        self.ftsp = "/pnfs/mu2e/persistent/fts"
        # this fcl move to the Print library, remove after transition
        self.res_fcl = "Print/fcl/printSam.fcl"
        self.res_fcl2 = "Analyses/test/runEventSubRun.fcl"
        self.validDataTiers = ["raw","rec","ntd","ext","rex","xnt"]
        self.validMCTiers  = ["cnf","sim","mix","dig","mcs","nts"]
        self.validOthTiers = ["log","bck","etc"]
        self.validExtensions = \
            ["art","root","tar","tgz","tbz","txt","log","fcl","mid","stn","enc"]
        self.validFF = ["phy-sim","phy-nts","phy-etc",
                        "usr-sim","usr-nts","usr-etc","tst-cos"]
        self.validGenerator = ["beam","stopped_particle","cosmic","mix",
                               "unknown"]
        self.validPrimary = ["proton","pbar","electron","muon","photon",
                             "neutron","mix","unknown"]
        self.resExeOk = False
        self.ifdhOk = False
        self.fileCount = 0

##############################################################
# Class to hold all the info about an upload file
##############################################################

class UploadFile:

    errMess = []
    nerr = 0

    BADFILESPEC =   1<<nerr
    errMess.append("file does not exist or couldn't be opened")
    nerr = nerr + 1

    DUPLICATEFILE = 1<<nerr
    errMess.append("duplicate file name")
    nerr = nerr + 1
    
    BADEXTENSION =  1<<nerr
    errMess.append("file extention is not recognized")
    nerr = nerr + 1

    JSONREADERROR = 1<<nerr
    errMess.append("failed to read json file")
    nerr = nerr + 1

    BADFILENAME =  1<<nerr
    errMess.append("file name has disallowed field contents or number of fields")
    nerr = nerr + 1

    RESFAILED   =  1<<nerr
    errMess.append("failed to extract run/evt/sub from data file")
    nerr = nerr + 1

    MISSINGFILEFAMILY   =  1<<nerr
    errMess.append("file family was not provided")
    nerr = nerr + 1

    WRONGFILEFAMILY   =  1<<nerr
    errMess.append("file family is not consistent with file format or owner")
    nerr = nerr + 1

    NORUNTYPE   =  1<<nerr
    errMess.append("file_type is 'data', 'run_type' is not defined yet")
    nerr = nerr + 1

    def __init__(self):
        self.baseDir = ""       # dirname of data file
        self.baseName = ""      # basename of data file
        self.dataFileName = ""  # full filespec of data file
        self.jsonFileName = ""  # full filespec
        self.jsoxFileName = ""  # full filespec
        self.dataFile = False
        self.jsonFile = False
        self.jsoxFile = False
        self.jsonReady = False
        self.state = int(0)
        self.json = {}
        self.seq = -1
    #
    #
    #
    def __str__(self):
        line = ""
        if self.jsonFile:
            line = line + (" j")
        else:
            line = line + ("  ")
        if self.jsoxFile:
            line = line + (" x")
        else:
            line = line + ("  ")
        line = line + "%5d"%(self.state)
        line = line + "  "+self.baseName
        return line

##############################################################
# check if a file spec in fn matches the file names
# in UploadFile file and put it in the list at the right place
##############################################################

def insertFile(par,files,fnr):

    # work with the full path name.  This achieves two things
    # 1) assures the dh.source_file is the full path
    #   for future parentage questions
    # 2) makes the file specs in the log file portable

    if par.verbose >4 :
        print( 'Including '+fnr )

    cmd = "readlink -f "+fnr
    fn = subprocess.check_output(cmd,shell=True).decode('utf-8').strip()

    # separate out basename and extension
    base = os.path.basename(fn) 
    dir  = os.path.dirname(fn)
    ext = base.split(".")[-1]

    # json or jsox files for foo.root are like 
    # foo.root.json, so need to strip the json
    # to get down to the data file name
    ext2 = ""
    if ext == "json" or ext == "jsox":
        ext2 = ext
        n = -(len(ext)+1)
        base = base[0:n]
        ext = base.split(".")[-1]
        if par.pair == "none":
            print("ERROR - json or jsox files on input, but no pairing specified")
            printHelp
            sys.exit(2)

    if par.verbose > 8:
        print("insertFile: fn="+fn+"\n"\
              "     base = "+base+" ext="+ext+"  ext2="+ext2)

    # check if it exists
    ex = os.path.exists(fn)
    if par.verbose > 8:
        print(fn+" exists = " + "%s"%(ex))
                
    for fnt in files:

        #
        # see if the file matches this record
        #
        match = False
        if par.pair == "dir":
            #print("comparing: "+dir+" and "+fnt.baseDir)
            if dir == fnt.baseDir:
                match = True
        elif par.pair == "file":
            if base == fnt.baseName:
                match = True
        else:
            # allow a match if the file is the same - detects duplicates
            if dir == fnt.baseDir and base == fnt.baseName:
                match = True

        if match :
            if par.verbose > 8:
                print("found match for "+fn+" in the global file list")
            # if the file was already found, this is a duplicate
            # otherwise add the filename to the record
            if ext2 == "json":
                if fnt.jsonFileName != "":
                    fnt.state = fnt.state | fnt.DUPLICATEFILE
                fnt.jsonFileName = fn
                fnt.jsonFile = True
            elif ext2 == "jsox":
                if fnt.jsoxFileName != "":
                    fnt.state = fnt.state | fnt.DUPLICATEFILE
                fnt.jsoxFileName = fn
                fnt.jsoxFile = True
            else :
                if fnt.dataFileName != "":
                    fnt.state = fnt.state | fnt.DUPLICATEFILE
                fnt.dataFileName = fn
                fnt.dataFile = True

            return 0
                
    # if not found in the list, create a new instance
    # of UploadFile and add it to the list
    file = UploadFile()
    file.baseName = base
    file.baseDir = dir
    if ext2 == "json":
        file.jsonFileName = fn            
        file.jsonFile = True
    elif ext2 == "jsox":
        file.jsoxFileName = fn
        file.jsoxFile = True
    else:
        file.dataFileName = fn
        file.dataFile = True

    if par.verbose > 8:
        print("adding "+fn+" to the global file list")
        print(file)

    #
    # put the new file on the list
    #
    files.append(file)

    return 0

##############################################################
# read in the input directory
##############################################################

def buildJson(par,file):

    if par.verbose>0 :
        print("Building json for "+file.dataFileName)


    # this will be the main dictionary for the JSON file
    jd = dict()

    #
    # if there is a generic json available at command line, include that
    #
    jd.update(par.genericJson)

    # if json exists, use that, if not try jsonx,
    # if both exist, ignore jsonx
    inp = ""
    if file.jsoxFile : inp = file.jsoxFileName
    if file.jsonFile : inp = file.jsonFileName

    # read whatever json is available
    if inp != "":
        fj = open(inp,"r")
        try:
            jt = json.load(fj)
        except:
            print("Error reading json content in file "+inp)
            print(sys.exc_info()[0])
            file.state = file.state | file.JSONREADERROR
            fj.close()
            return 1
        fj.close()
        jd.update(jt)

        if par.verbose> 8:
            print("Reading JSON from "+inp)
            print(json.dumps(jd,sort_keys=True, indent=4))

    #
    # go through the list of requirements and see
    # what"s missing and try to supply it,
    # or if any constriants are violated
    #

    # check/build the fields based on the name
    buildJsonName(par,file,jd)

    # check/build the fields based on the run/event/subrun
    if par.reName != "":
        ext = par.reName.split(".")[-1]
    else:
        ext = file.baseName.split(".")[-1]
    if ext == "art":
        buildJsonRES(par,file,jd)

    # check/build any other fields
    buildJsonOther(par,file,jd)

    #
    if par.verbose > 8:
        print("Final values of json file for "+file.dataFileName)
        print(json.dumps(jd, indent=4))

    # save it in the file object
    file.json = jd

    return 0


##############################################################
# check the values in the file name against the dictionary
# if the values were missing from the dictionary, add them
##############################################################

def buildJsonName(par,file,jp):

    # the name, with extension but no directory
    if par.reName != "" :
        dname = par.reName
    else:
        dname = file.dataFileName.split("/")[-1]
        
    # should be 6 dot-separated fields
    if dname.count(".") != 5 :
        file.state = file.state | file.BADFILENAME
        if par.verbose>4:
            print("ERROR filename has wrong number of dot fields, ",\
            dname.count("."))
        # if not enough dot fields, can't continue to parse
        if dname.count(".") < 5 :
            print("ERROR filename has too few fields, can't continue")
            sys.exit(2)

    if 'file_name' in jp:
        # file name in json was wrong, that shouldn"t happen
        if jp['file_name'] != dname:
            if par.verbose>4:
                print("ERROR file name did not match json",\
                jp['file_name'],"!=",dname)
            file.state = file.state | file.BADFILENAME
    else:
        # not a problem, just add it
        jp['file_name'] = dname

    tier = dname.split(".")[0]
    if not tier in par.validDataTiers+par.validMCTiers+par.validOthTiers :
        if par.verbose>4:
            print("ERROR data tier not in ",\
                par.validDataTiers+par.validMCTiers+par.validOthTiers)
        file.state = file.state | file.BADFILENAME
    if 'data_tier' in jp:
        if jp['data_tier'] != tier:
            if par.verbose>4:
                print("ERROR data tier did not match json",\
                jp['data_tier'],"!=",tier)
            file.state = file.state | file.BADFILENAME
    else:
        jp['data_tier'] = tier

    # second field is username
    usern = dname.split(".")[1]
    if 'dh.owner' in jp:
        if jp['dh.owner'] != usern:
            if par.verbose>4:
                print("ERROR owner did not match json",\
                jp['dh.owner'],"!=",usern)
            file.state = file.state | file.BADFILENAME
    else:
        jp['dh.owner'] = usern

    # check that description, configuration and sequencer are not null
    if  len(dname.split(".")[2]) == 0 or \
        len(dname.split(".")[3]) == 0 or \
        (len(dname.split(".")[4]) == 0 and par.reName == ""):
        if par.verbose>4:
            print("ERROR description, configuration or sequencer is null",\
                dname)
        file.state = file.state | file.BADFILENAME

    if 'dh.description' in jp:
        if jp['dh.description'] != dname.split(".")[2]:
            if par.verbose>4:
                print("ERROR description did not match json",\
                jp['dh.description'],"!=",dname.split(".")[2])
            file.state = file.state | file.BADFILENAME
    else:
        jp['dh.description'] = dname.split(".")[2]

    if 'dh.configuration' in jp:
        if jp['dh.configuration'] != dname.split(".")[3]:
            if par.verbose>4:
                print("ERROR configuration did not match json",\
                jp['dh.configuration'],"!=",dname.split(".")[3])
            file.state = file.state | file.BADFILENAME
    else:
        jp['dh.configuration'] = dname.split(".")[3]

    if 'dh.sequencer' in jp:
        if jp['dh.sequencer'] != dname.split(".")[4]:
            if par.verbose>4:
                print("ERROR sequencer did not match json",\
                jp['dh.sequencer'],"!=",dname.split(".")[4])
            file.state = file.state | file.BADFILENAME
    else:
        jp['dh.sequencer'] = dname.split(".")[4]

    ext = dname.split(".")[-1]
    if not ext in par.validExtensions :
        # only fixed type of extensions allowed
        if par.verbose>4:
            print("ERROR file extension",ext,"is not in ",\
                par.validExtensions)
        file.state = file.state | file.BADFILENAME
    if 'file_format' in jp:
        if jp['file_format'] != ext:
            if par.verbose>4:
                print("ERROR extension did not match json",\
                jp['file_format'],"!=",ext)
            file.state = file.state | file.BADFILENAME
    else:
        jp['file_format'] = ext

    return 0


##############################################################
# check if it is possible to run the run/event/subrun module
##############################################################

def checkRES(par):
    #cmd="/bin/bash -c "
    cmd = ""
    cmd = cmd + "[ -x `which mu2e` ] && "
    cmd = cmd + "[ -e ${MU2E_BASE_RELEASE}/"+par.res_fcl+" ] "
    cmd = cmd + " && echo OK"
    check = subprocess.check_output(cmd,shell=True).decode('utf-8')

    if check.strip() != "OK":
        print("ERROR could not find RunEventSubRun module")
        return False
    else:
        if par.verbose > 3 :
            print("RunEventSubRun module check is OK")
        return True

    
##############################################################
# check if it is possible to run the run/event/subrun module
##############################################################

def checkIfdh(par):

    cmd = 'if [ -n "`which ifdh 2> /dev/null`" ]; then echo OK; fi'
    check = subprocess.check_output(cmd,shell=True).decode('utf-8')

    if check.strip() != "OK":
        print("WARNING - could not find ifdh")
        return False
    else:
        if par.verbose > 3 :
            print("ifdh check is OK")

    #cmd = 'if  grd-proxy-info > /dev/null 2>&1 ; then echo OK; fi'
    #check = subprocess.check_output(cmd,shell=True).decode('utf-8')
    #
    #if check.strip() != "OK":
    #    print("WARNING - failed grid-proxy-info check")
    #    return False
    #else:
    #    if par.verbose > 3 :
    #        print("ifdh check is OK")
    #
    #cmd = 'if "" ; then echo OK; fi'
    #check = subprocess.check_output(cmd,shell=True).decode('utf-8')
    #
    #if check.strip() != "OK":
    #    print("WARNING - failed grid-proxy-info check")
    #    return False
    #else:
    #    if par.verbose > 3 :
    #        print("ifdh check is OK")

    return True

    
##############################################################
# check the run/event/subrun json entries
##############################################################

def buildJsonRES(par, file, jp):

    #
    # if the dictionary already contains the RES,
    # (it could be in an available json file)
    # then skip the process of adding it.
    #
    ok = True
    if "event_count"      not in jp : ok = False
    if "first_run_event"  not in jp : ok = False
    if "first_event"      not in jp : ok = False
    if "last_run_event"   not in jp : ok = False
    if "last_event"       not in jp : ok = False
    if "first_run_subrun" not in jp : ok = False
    if "first_subrun"     not in jp : ok = False
    if "last_run_subrun"  not in jp : ok = False
    if "last_subrun"      not in jp : ok = False
    if "runs"             not in jp : ok = False

    if ok : return 0

    #
    # create the command to run the RES art module
    #
    cmd = "mu2e "
    cmd = cmd+ "-c "+par.res_fcl+" "
    cmd = cmd+ "-s "+file.dataFileName
    cmd = cmd+ " 2>&1 "

    if par.verbose > 4 :
        print("Running run/event grabber on "+file.dataFileName)

    err = False
    res = ""
    try:
        res = subprocess.check_output(cmd,shell=True).decode('utf-8')
    except subprocess.CalledProcessError as cpe:
        print("ERROR: RES call reports an executable return code ",\
                                               cpe.returncode)
        err = True
    except:
        print("ERROR: RES call reports a subprocess method error ")
        print(traceback.print_exc())
        #print(sys.exc_info()[2].print_exc())
        err = True

    if par.verbose > 9 or err:
        print("output of RES call:")
        print(res)

    if err :
        file.state = file.state | file.RESFAILED
        return 1

    # these strings mark the printed results
    sp0 = res.find("start RunEventSubRun::endJob summary") + 37
    sp1 = res.find("end RunEventSubRun::endJob summary") - 1
    res = res[sp0:sp1]
    if par.verbose > 9 :
        print("output from RES exe run:")
        print(res)

    # it should be a json format
    err = False
    try:
        jp_res = json.loads(res)
    except:
        if par.verbose> 0:
            print("ERROR: RES json did not load")
        err = True

    if par.verbose > 8 or err:
        print("json file from RES exe run:")
        print(json.dumps(jp_res,indent=4))

    if len(jp_res) < 8:
        if par.verbose> 0:
            print("ERROR: RES exe did not produce correct "\
                "number of json fields, ",len(jp_res))
        file.state = file.state | file.RESFAILED

    # add in these fields to the main json
    jp.update(jp_res)

    return 0


##############################################################
# check the run/event/subrun json entries
##############################################################

def buildJsonOther(par, file, jp):

    #
    # create final file name if rename requested
    # 
    if par.reName != "" :
        # if art file, use first run_subrun
        if jp['file_format'] == "art":
            if 'dh.first_run_subrun' in jp :
                jp['dh.sequencer'] = "{0:s}{1:08d}_{2:06d}".format(     \
                par.seqTag,jp['dh.first_run_subrun'],jp['dh.first_subrun'])
            else:
                # in case RES failed
                jp['dh.sequencer'] = "{0:s}{1:04d}".format(  \
                    par.seqTag,par.fileCount)
        else:
            # use file counter
            jp['dh.sequencer'] = "{0:s}{1:04d}".format(  \
                par.seqTag,par.fileCount)

        jp['file_name'] = \
                   jp['data_tier']+"."+jp['dh.owner']+"."+ \
                   jp['dh.description']+"."+jp['dh.configuration']+"."+  \
                   jp['dh.sequencer']+"."+jp['file_format']
    else:
        # use data file name
        jp['file_name'] = (file.dataFileName).split("/")[-1]

    file.baseName = jp['file_name']

    #
    # the dataset is a file name without the sequencer
    #
    jp['dh.dataset'] = \
                   jp['data_tier']+"."+jp['dh.owner']+"."+ \
                   jp['dh.description']+"."+jp['dh.configuration']+"."+ \
                   jp['file_format']


    #
    # check if file name has only alphnumeric and ._-
    #
    if re.match('^[\w\.-]+$',jp['file_name']) == None:
        file.state = file.state | file.BADFILENAME
        if par.verbose > 4:
            print("ERROR - file name has illegal characters")

    #
    # check for file_family
    #
    if par.file_family not in par.validFF :
        if par.verbose > 4:
            print("ERROR - file family",par.file_family,"not in",par.validFF)
        file.state = file.state | file.MISSINGFILEFAMILY
    # only mu2e should upload to phy-*
    if par.file_family[0:3]=="phy" and \
       jp['dh.owner'] != "mu2e":
        file.state = file.state | file.WRONGFILEFAMILY
        if par.verbose>4:
            print("ERROR - file family type \"phy-\" but owner not mu2e")
    # only expect art files in sim ff
    # and occasionally a root file like mustops or encrypted files
    if par.file_family[4:7]=="sim" and \
           (jp['file_format'] != "art" and \
            jp['file_format'] != "root" and \
            jp['file_format'] != "enc" ):
        file.state = file.state | file.WRONGFILEFAMILY
        if par.verbose>4:
            print("ERROR - file family type \"-sim\" but file type not art")
    # only expect root files in nts ff
    if par.file_family[4:7]=="nts" and \
       (jp['file_format'] != "stn" and \
        jp['file_format'] != "root"    ) :
        file.state = file.state | file.WRONGFILEFAMILY
        if par.verbose>4:
            print("ERROR - file family type \"-nts\" but file type not root")

    #
    # add file size
    #
    jp["file_size"] = os.path.getsize(file.dataFileName)

    #
    # add sha256 hash
    #
    jp["dh.sha256"] = sha256OfFile(file.dataFileName)

    #
    # add content_status, always good at upload
    #
    jp["content_status"] = "good";

    #
    # set file_type (data/MC) based on data_tier
    #
    data_tier = file.baseName.split(".")[0]
    if data_tier in par.validDataTiers:
        file_type = "data"
    elif data_tier in par.validMCTiers:
        file_type = "mc"
    else:
        file_type = "other"

    jp['file_type'] = file_type

    if par.verbose > 9 :
        print("data_tier is "+data_tier+" and file_type is " + file_type)


    #
    # record the original data file in source_file
    # don't overwrite if it was already there from a json file
    #
    if 'dh.source_file' not in jp:
        jp['dh.source_file'] = file.dataFileName

    #
    # the runs list come from RES exe but it doesn't 
    # know what the run type is
    #
    
    # this if prevents any data from being processed
    # without code to process run_types being inserted here
    if jp['file_type'] not in ["mc","other"]  and jp['file_format'] != "mid":
        file.state = file.state | file.NORUNTYPE
        if par.verbose>4 :
            print("ERROR - file_type is 'data', 'run_type' not defined")
        
    #
    #  clean up runs entry
    #
    if 'runs' in jp :
        #
        # if this is MC and the runs list is very long,
        # then set the list to empty since it takes too long 
        # to enter in SAM db.  Also prefer empty to partial data.
        #
        if jp['file_type'] == "mc":
            if len(jp['runs']) > 100:
                if par.verbose>4 :
                    print("INFO - metadata runs list for MC is too long, zero it")
                jp['runs'] = []

        # replace run_type in runs list
        for r in jp['runs']:
            if r[2]=="unknown" :
                r[2] = jp['file_type']
           


##############################################################
# first summary print
##############################################################

def printSummary1(files):
    nd = 0
    nj = 0
    nx = 0
    ne = 0
    for fnt in files:
        if fnt.dataFile : nd = nd + 1
        if fnt.jsonFile : nj = nj + 1
        if fnt.jsoxFile : nx = nx + 1
        if fnt.state != 0 : ne = ne + 1
    print('Parsed input, found:')
    print('%4d data files'% nd)
    print('%4d json files'% nj)
    print('%4d jsox files'% nx)
    print('%4d files in error'% ne)


##############################################################
# create sha256 hash of the data file
##############################################################
def sha256OfFile(filepath):
    sha = hashlib.sha256()
    with open(filepath, 'rb') as f:
        # loop allows large files
        while True:
            block = f.read(2**10) # one-megabyte blocks.
            if not block: break
            sha.update(block)
        return sha.hexdigest()

##############################################################
# interpret the command line, fill the file list
##############################################################
def parseCommandOptions(par,files):

    # the generic json file name, will be read below, if needed
    genericJsonFs = ""
    # don't overwrite custom fts dir
    lockFtsDir = False;

    try:
        opts, args = getopt.getopt(sys.argv[1:],
                 "hxXcmgep:v:j:i:d:a:t:f:r:l:s:o:",["help"])
    except getopt.GetoptError:
        printHelp
        sys.exit(2)

    for opt, arg in opts:
        if opt in ("-h", "--help"):
            printHelp()
            sys.exit(0)
        elif opt == "-x":
            par.execute = True
        elif opt == "-X":
            par.executeF = True
        elif opt == "-c":
            par.copy = True
            # unless overruled by -d, move json too
            if par.jsonDir == "":
                par.jsonDir = "fts"
        elif opt == "-m":
            par.move = True
            # unless overruled by -d, move json too
            if par.jsonDir == "":
                par.jsonDir = "fts"
        elif opt == "-g":
            par.groupCp = True
            # unless overruled by -l, create command file in .
            if par.comDir == "":
                par.comDir = "."
        elif opt == "-e":
            par.inPlace = True
        elif opt == "-v":
            par.verbose = int(arg)
        elif opt == "-p":
            par.pair = arg
        elif opt == "-s":
            par.inFile = arg
        elif opt == "-j":
            genericJsonFs = arg
        elif opt == "-i":
            # can be repeated, so deal with it immediately
            k = arg.split("=")[0]
            v = arg.split("=")[1]
            if v.isdigit():
                par.genericJson[k] = int(v)
            else:
                if v == "":
                    print("ERROR - value in argument to -i is empty:"+arg)
                    sys.exit(2)
                par.genericJson[k] = v
        elif opt == "-d":
            par.jsonDir = arg
        elif opt == "-a":
            par.parentTxt = arg
        elif opt == "-t":
            par.seqTag = arg
        elif opt == "-f":
            par.file_family = arg
        elif opt == "-r":
            par.reName = arg
        elif opt == "-l":
            par.comDir = arg
        elif opt == "-o":
            # undocumented option for testing
            par.fts = arg
            lockFtsDir = True

    if par.verbose >4:
        print('Parsed command parameters:')
        print(' -v ',par.verbose,' (verbose)')
        print(' -x ',par.execute,' (execute upload)')
        print(' -X ',par.executeF,' (execute upload, ignore checks)')
        print(' -s ',par.inFile,' (file with list of input files)')
        print(' -c ',par.copy,' (copy output files to FTS)')
        print(' -m ',par.move,' (move output files to FTS)')
        print(' -g ',par.groupCp,' (run ifdh -f at the end)')
        print(' -e ',par.inPlace,' (rename data file in place)')
        print(' -p ',par.pair,' (pairing method)')
        print(' -j ',genericJsonFs,' (generic json file)')
        print(' -d ',par.jsonDir,' (destination for json files)')
        print(' -a ',par.parentTxt,' (txt fle of parent file sam files)')
        print(' -t ',par.seqTag,' (txt to prepend to sequencer field)')
        print(' -f ',par.file_family,' (file_family)')
        print(' -r ',par.reName,' (rename files)')
        print(' -l ',par.comDir,' (log of renamed files)')

    if par.file_family == "":
        print("ERROR - file_family is required")
        sys.exit(2)

    # if this is a phy* file family then switch to where those are
    if par.file_family[0:3] == "phy" and not lockFtsDir:
        par.fts = par.ftsp

    if par.verbose >4:
        print('FTS directory set to',par.fts)

    if par.pair not in ["file","dir","none"]:
        print("ERROR - pairing method must be 'file' or 'dir'")
        sys.exit(2)

    if par.groupCp and (par.jsonDir == "" or par.jsonDir.lower() == "fts") :
        print("ERROR - when using -g to do a grouped ifdh, you must use -d ")
        print("to specify a directory to temporarily hold the json files")
        sys.exit(2)

    # after get opts, the only args left are
    # those without flags, which should be filespecs
    for fn in args:
        insertFile(par,files,fn)

    #
    # if a list of input files was provided, add those
    #
    if par.inFile != "":
        fin = open(par.inFile,'r')
        for fn in fin:
            print("read "+fn)
            fn = fn.strip(" \t \n")
            insertFile(par,files,fn)
        fin.close()


    if par.verbose > 8:
        print(" j x stat    filename")
        for fnt in files:
            print(fnt)

    if par.verbose > 1:
        printSummary1(files)

    # read in the generic json, which applies to all files
    # these values could potentially overwrite values supplied with -i
    if genericJsonFs != "":
        jt = {}
        fj = open(genericJsonFs,"r")
        try:
            jt = json.load(fj)
        except:
            print("Error reading json content in file "+fj)
            print(sys.exc_info()[0])
        fj.close()
        if par.verbose> 8:
            print("Reading JSON from "+genericJsonFs)
            print(json.dumps(jt,sort_keys=True, indent=4))

        # save it for when file json is created
        for k in jt.keys():
            # do not supersede values given at command line
            if k not in par.genericJson :
                par.genericJson[k] = jt[k]

    if par.parentTxt != "":
        lt = []
        try:
            fj = open(par.parentTxt,"r")
            tt = fj.read()
            fj.close()
            tt = tt.replace(","," ")
            tt = tt.replace("\n"," ")
            lt = tt.split();
        except:
            print("Error reading content in file ",fj)
            print(sys.exc_info()[0])

        if par.verbose> 8:
            print("Reading parents from "+par.parentTxt)
            print(lt)

        # save it for when file json is created
        if len(lt) > 0:
            if 'parents' in par.genericJson:
                par.genericJson['parents'] = par.genericJson['parents'] +lt
            else:
                par.genericJson['parents'] = lt

    # check if this release has made the fcl location transition
    if not os.path.isfile(os.environ["MU2E_BASE_RELEASE"]+"/"+par.res_fcl):
        par.res_fcl = par.res_fcl2

    par.resExeOk = checkRES(par)
    par.ifdhOk = checkIfdh(par)



##############################################################
# write the json files
##############################################################

def writeJson(par,files):
    # content_status
    # do error sumary  
    # rename files if required
    # add create data and user  os.environ["USER"]
    #datetime.datetime.now().isoformat(" ")


    # count and report any errors
    nerr = UploadFile.nerr
    errl = [0]*nerr

    nf = 0
    ne = 0
    for file in files:
        # count data files (ignore json)
        if file.dataFileName != "":
            nf = nf +1
            # count how many files have what errors
            e = False
            for i in range(nerr):
                if file.state & (1<<i):
                    errl[i] = errl[i] + 1
                    e = True
            if e : ne = ne + 1

    if par.verbose > 0:
        print("\nFile error summary:")
        print("{:5d} data files found, {} have errors".format(nf,ne))
        print("")

        if ne > 0 : 
            print("Listing of errors:")
            for i in range(nerr):
                if errl[i] >0:
                    print("{:5d} {}".format(errl[i],UploadFile.errMess[i]))
                    # now give at least one file name
                    for f in files:
                        if f.state & (1<<i) > 0:
                            print("        for example: ",file.dataFileName)
                            break

    if ne > 0 :
        print("\nERROR - errors detected - exiting without writing json files")
        sys.exit(1)

    #
    # write the log file of the old and new SAM name, if requested
    #

    writeLog =  par.comDir != "" and len(files) > 0 and par.execute
    if writeLog:
        lfn = par.comDir + "/" + files[0].json['dh.dataset']+".command." \
              +str(time.time()).split(".")[0]
        try:
            lfs = open(lfn,"w")
        except:
            print("ERROR: Error opening log file "+lfn)
            print(sys.exc_info()[0])
            sys.exit(2)
           

    # check if the fts is local (so OS-level commands can be used)
    localFts = False
    cmd = "if [ -d "+par.fts+" ]; then echo OK; fi"
    checkCmd = subprocess.check_output(cmd,shell=True).decode('utf-8').strip()
    if checkCmd == "OK" :
        localFts = True
    if par.verbose >5 :
        print('localFts is ',localFts)

    #
    # process each file
    #

    for file in files:

        #
        # the fts area has subdirectories to manage large
        # numbers of files.  Pick a 3-digit subdir based on file's name
        #
        hdir = "%03d"%( hash(file.baseName)%1000 )
        
        #
        # move data file to the FTS area, if requested
        #
        dodir = par.fts+"/"+par.file_family+"/"+hdir
        newfn = dodir+"/"+file.baseName
        if (par.copy or par.move) and not par.groupCp:

            if localFts:
                cmd = ""
            else:
                cmd = "ifdh "

            if par.copy:
                cmd = cmd+"cp "+file.dataFileName+" "+newfn
            else:
                cmd = cmd+"mv "+file.dataFileName+" "+newfn

            if par.execute:
                if par.verbose>4:
                    print("Executing: "+cmd)
                try:
                    subprocess.check_call(cmd,shell=True)
                except subprocess.CalledProcessError as cpe:
                    if par.verbose>0:
                        print("ERROR executing "+cmd)
                        print("Exiting now...")
                    sys.exit(2)
            else:
                if par.verbose>4:
                    print("Would execute: "+cmd)

        #
        # just rename if requested
        #
        if par.inPlace:
            
            if file.baseDir == "":
                cmd = "mv "+file.dataFileName+" "+file.baseName
            else:
                cmd = "mv "+file.dataFileName+" "+ \
                file.baseDir+"/"+file.baseName

            if par.execute:
                if par.verbose>4:
                    print("Executing: "+cmd)
                try:
                    subprocess.check_call(cmd,shell=True)
                except subprocess.CalledProcessError as cpe:
                    if par.verbose>0:
                        print("ERROR executing "+cmd)
                        print("Exiting now...")
                    sys.exit(2)
            else:
                if par.verbose>4:
                    print("Would execute: "+cmd)

        #
        # write the move in the log if requested
        #
        if writeLog:
            lfs.write(file.dataFileName+" "+newfn+"\n")

        #
        # create json output file in tmp area
        #
        fnj = "tempfile"
        if par.execute :
            outfile = tempfile.NamedTemporaryFile(delete=False, mode="w")
            fnj = outfile.name
            json.dump(file.json,outfile,indent=4)
            outfile.write("\n")
            outfile.close()

        #
        # move json to the output area
        #
        odir = os.getcwd()
        if par.jsonDir.lower() == "same":
            if "/" in file.dataFileName:
                odir = file.dataFileName[0:file.dataFileName.rfind("/")]
        elif par.jsonDir.lower() == "fts":
            odir = par.fts+"/"+par.file_family+"/"+hdir
        elif par.jsonDir != "":
            odir = par.jsonDir
            if odir[0] != "/":
                odir = os.getcwd()+"/"+odir 
        newfnj = odir+"/"+file.baseName+".json"

        # check if the output dir is local (so OS-level commands can be used)
        localDir = False
        cmd = "[ -d "+odir+" ] && echo OK"
        checkCmd = subprocess.check_output(cmd,shell=True).decode('utf-8').strip()
        if checkCmd == "OK" :
            localDir = True
        if par.verbose >5 :
            print('localDir is ',localDir)

        #
        # the actual copy
        # it is a tiny file - use cp if possible, and 
        # use ifdh if it is a remote copy to dcache
        #
        if localDir :
            cmd = "cp "
        else:
            cmd = "ifdh cp "

        cmd = cmd+fnj+" "+newfnj
        cmd2 = "rm -f "+fnj

        # this executes even if groupCp is requested 
        # we have to get the json file off of tmp area
        # to a holding area
        if par.execute:
            if par.verbose>4 :
                print("Executing: "+cmd)
            try:
                subprocess.check_call(cmd,shell=True)
                subprocess.check_call(cmd2,shell=True)
            except subprocess.CalledProcessError as cpe:
                if par.verbose>0:
                    print("ERROR executing "+cmd)
                    print("Exiting now...")
                sys.exit(2)
        else:
            if par.verbose>4 :
                print("Would execute: "+cmd)

        #
        # write the move in the log if requested
        #
        if writeLog:
            # if fts, then the json is already in final position
            if par.jsonDir.lower() != "fts":
                # we know the json file is now in the
                # json output dir and newfnj points to it
                # write the idfh command
                lfs.write(newfnj+" "+par.fts+"/"+par.file_family+"/"+hdir+"/" \
                          +file.baseName+".json"+"\n")


    if writeLog:
        lfs.close()

    # execute an ifdh cp command on the command file, if requested
    if par.groupCp and par.execute:
        res = ""
        cmd = "ifdh cp -f "+lfn
        if par.verbose>4: 
            print("in group copy, com="+cmd)
        try:
            res = subprocess.check_output(cmd,shell=True).decode('utf-8')
        except:
            print("ERROR: failed to execute:")
            print(cmd)
            print(traceback.print_exc())
            err = True


    return 0

##############################################################
# main
##############################################################
if __name__ == "__main__":

    # a list of command line parameters
    par = Parms()

    # an array of class UploadFile, contains
    # all info for each data+json file pair
    files = []

    # interpret the command line
    # and create the list of files
    parseCommandOptions(par,files);

    # check for res and ifdh
    if par.execute:
        if not par.resExeOk:
            print("WARNING - mu2e exe not found - will fail to operate on art files!")
        if not par.ifdhOk:
            print("WARNING - ifdh or grid proxy not found - data movement may fail")

    # for each file, read the json files
    # determine if all required metadata is available
    # compute what is needed, set flags for errors
    for file in files:
        buildJson(par,file);
        par.fileCount = par.fileCount + 1

    # write the json files
    # report any errors
    # error exit if errors are found
    writeJson(par,files)

    sys.exit(0)
