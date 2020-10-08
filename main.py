import sys # for python version check + sys.exit
import os # for path
from cli import readCLIArgs
from daskrunner import DaskRunner, run
from dataset import Dataset

if __name__ == '__main__':
    args = readCLIArgs()

    datasetPath = args.datasetPath  # @todo check char '/Volumes/1ToApfsNVME/data-bids/day2day'
    datasetPath = os.path.normpath(datasetPath)
    runner = DaskRunner('.task_cache.csv')
    dataset = Dataset(datasetPath, '.bids_cache')
    print("path: " + datasetPath)


    # 0. Check python version.
    # @note f-strings require python 3.6, will throw syntax error instead though.
    assert sys.version_info >= (3, 6)


    # 1. Validate BIDS
    def validateBids():
        datasetAbsPath = os.path.abspath(datasetPath)
        logPath = 'log/bids-validator.txt'
        logPath = os.path.abspath(logPath)
        logDir = os.path.dirname(logPath)
        if not os.path.exists(logDir):
            os.makedirs(logDir)

        version = '1.5.4'
        cmd = f'''
            docker run -ti --rm
                -v "{datasetAbsPath}:/input:ro"
                --cpus 2.0
                -m 6G
                bids/validator:v{version}
                /input
                2>&1 >{logPath}
        '''

        didSucceed, returnCode, stdout, stderr = run(cmd)

        return didSucceed, returnCode


    # 2. Run QC.
    def generateMriQcSubjectReport(subjectId):
        datasetAbsPath = os.path.abspath(datasetPath)
        # @note must == the group task output dir one. Safe to parallelize.
        outputDir = 'out/mriqc'
        outputDir = os.path.abspath(outputDir)
        logPath = f'log/mriqc/{subjectId}.txt'
        logPath = os.path.abspath(logPath)
        logDir = os.path.dirname(logPath)
        if not os.path.exists(logDir):
            os.makedirs(logDir)

        # @note
        # -m 6G fixes `concurrent.futures.process.BrokenProcessPool: A process in
        # the process pool was terminated abruptly
        # while the future was running or pending.`.
        # cf. https://neurostars.org/t/mriqc-crashing-in-middle-of-scan/3173/3
        # @todo kill on "Traceback (most recent call last):"

        version = '0.15.2'
        cmd = f'''
            docker run -ti --rm
                -v "{datasetAbsPath}:/input:ro"
                -v "{outputDir}:/output"
                --cpus 2.0
                -m 6G
                poldracklab/mriqc:{version}
                /input /output
                participant --participant_label {subjectId}
                --no-sub
                --nprocs 2
                --mem_gb 6
                2>&1 >{logPath}
        '''

        didSucceed, returnCode, stdout, stderr = run(cmd)

        return didSucceed, returnCode


    def generateMriQcGroupReport():
        datasetAbsPath = os.path.abspath(datasetPath)
        outputDir = 'out/mriqc'
        outputDir = os.path.abspath(outputDir)
        logPath = 'log/mriqc/group.txt'
        logPath = os.path.abspath(logPath)
        logDir = os.path.dirname(logPath)
        if not os.path.exists(logDir):
            os.makedirs(logDir)

        version = '0.15.2'
        cmd = f'''
            docker run -ti --rm
                -v "{datasetAbsPath}:/input:ro"
                -v "{outputDir}:/output"
                --cpus 2.0
                -m 6G
                poldracklab/mriqc:{version}
                /input /output
                group
                --no-sub
                --nprocs 2
                --mem_gb 6
                2>&1 >{logPath}
        '''

        didSucceed, returnCode, stdout, stderr = run(cmd)

        return didSucceed, returnCode

    # 3. Preprocess anat
    def preprocessFMRiPrepAnatBySubject(subjectId):
        datasetAbsPath = os.path.abspath(datasetPath)
        outputDir = 'out/fmriprep'
        outputDir = os.path.abspath(outputDir)
        workDir = f'tmp/fmriprep/{subjectId}'
        workDir = os.path.abspath(workDir)
        licenseDir = 'licenses/'
        licenseDir = os.path.abspath(licenseDir)
        freesurferLicenseFile = 'freesurfer.txt'
        logPath = f'log/fmriprep/anat/{subjectId}.txt'
        logPath = os.path.abspath(logPath)
        logDir = os.path.dirname(logPath)
        if not os.path.exists(logDir):
            os.makedirs(logDir)
        
        version = '20.2.0rc2'
        cmd = f'''
            docker run -ti --rm \
                -v {datasetAbsPath}:/input:ro \
                -v {outputDir}:/output \
                -v {workDir}:/work \
                -v {licenseDir}:/licenses:ro \
                --cpus 2.0
                -m 6G
                poldracklab/fmriprep:{version} \
                -w /work \
                --fs-license /licenses/{freesurferLicenseFile} \
                --notrack \
                --skip-bids-validation \
                --fs-no-reconall \
                --ignore slicetiming \
                --output-spaces MNI152NLin6Asym MNI152NLin2009cAsym OASIS30ANTs \
                --anat-only \
                --participant-label {subjectId} \
                --nprocs 2 \
                --mem-mb 6000 \
                -vv \
                /input /output \
                participant
                2>&1 >{logPath}
        '''

        didSucceed, returnCode, stdout, stderr = run(cmd)

        return didSucceed, returnCode


    # 3. Preprocess func
    def preprocessFMRiPrepFuncBySession(subjectId, sessionId):
        datasetAbsPath = os.path.abspath(datasetPath)
        outputDir = 'out/fmriprep'
        outputDir = os.path.abspath(outputDir)
        workDir = f'tmp/fmriprep/{subjectId}-{sessionId}'
        workDir = os.path.abspath(workDir)
        licenseDir = 'licenses/'
        licenseDir = os.path.abspath(licenseDir)
        freesurferLicenseFile = 'freesurfer.txt'
        logPath = f'log/fmriprep/func/{subjectId}-{sessionId}.txt'
        logPath = os.path.abspath(logPath)
        logDir = os.path.dirname(logPath)
        if not os.path.exists(logDir):
            os.makedirs(logDir)

        cmd1 = '''
            mkdir -p "''' + workDir + '''";
            printf '%s' '{
                "fmap": {
                    "datatype": "fmap"
                },
                "bold": {
                    "datatype": "func",
                    "suffix": "bold",
                    "session": "''' + sessionId + '''"
                },
                "sbref": {
                    "datatype": "func",
                    "suffix": "sbref",
                    "session": "''' + sessionId + '''"
                },
                "flair": {"datatype": "anat", "suffix": "FLAIR"},
                "t2w": {"datatype": "anat", "suffix": "T2w"},
                "t1w": {"datatype": "anat", "suffix": "T1w"},
                "roi": {"datatype": "anat", "suffix": "roi"}
            }' > "''' + workDir + '''/bids_filter.json"
        '''

        didSucceed, returnCode, stdout, stderr = run(cmd1, oneliner=True)

        if not didSucceed:
            return didSucceed, returnCode

        version = '20.2.0rc2'
        cmd2 = f'''
            docker run -ti --rm
                -v "{datasetAbsPath}:/input:ro"
                -v "{outputDir}:/output"
                -v "{outputDir}:/anat-fast-track:ro"
                -v "{workDir}:/work"
                -v "{licenseDir}:/licenses:ro"
                --cpus 2.0
                -m 6G
                poldracklab/fmriprep:{version}
                -w /work
                --fs-license /licenses/{freesurferLicenseFile}
                --notrack
                --skip-bids-validation
                --fs-no-reconall
                --ignore slicetiming
                --participant-label {subjectId}
                --bids-filter-file /work/bids_filter.json
                --nprocs 2
                --mem-mb 6000
                -vv
                /input /output
                participant
                2>&1 >{logPath}
        '''

        didSucceed, returnCode, stdout, stderr = run(cmd2)

        return didSucceed, returnCode


    # 1. BidsValidator.
    didSucceed = runner.runTask(
        'validate_bids',
        lambda: validateBids()
    )
    if not didSucceed:
        sys.exit(1)

    # 2. MRIQC: qc by subjects.
    subjectIds = dataset.getSubjectIds()
    successfulSubjectIds, failedSubjectIds = runner.batchTask(
        'mriqc_subj',
        lambda subjectId: generateMriQcSubjectReport(subjectId),
        subjectIds
    )
    if len(successfulSubjectIds) == 0:
        sys.exit(2)

    # 3. MRIQC: group qc.
    didSucceed = runner.runTask(
        'mriqc_group',
        lambda: generateMriQcGroupReport()
    )
    if not didSucceed:
        sys.exit(3)

    # 4. FMRiPrep: anat by subjects.
    successfulSubjectIds, failedSubjectIds = runner.batchTask(
        'fmriprep_anat',
        lambda subjectId: preprocessFMRiPrepAnatBySubject(subjectId),
        successfulSubjectIds
    )
    if len(successfulSubjectIds) == 0:
        sys.exit(4)

    # 5. FMRiPrep: func by subjects.
    sessionIds = [
        (subjectId, sessionId)
        for subjectId in successfulSubjectIds
        for sessionId in dataset.getSessionIdsBySubjectId(subjectId)
    ]
    successfulSessionIds, failedSessionIds = runner.batchTask(
        'fmriprep_func',
        lambda subjectId, sessionId:
            preprocessFMRiPrepFuncBySession(subjectId, sessionId),
        sessionIds
    )
    if len(successfulSessionIds) == 0:
        sys.exit(5)

    # 6. Merge result and generate reports.
