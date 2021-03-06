#!/usr/bin/env python3
from olctools.accessoryFunctions.accessoryFunctions import combinetargets, filer, GenObject, MetadataObject, \
    make_path, run_subprocess, write_to_logfile
from olctools.accessoryFunctions.metadataprinter import MetadataPrinter
from genemethods.typingclasses.resistance import ResistanceNotes
from genemethods.assemblypipeline.GeneSeekr import GeneSeekr
from genemethods.sipprCommon.objectprep import Objectprep
from genemethods.sipprCommon.sippingmethods import Sippr
from genemethods.genesippr.genesippr import GeneSippr
from genemethods.serosippr.serosippr import SeroSippr
from genemethods.sipprCommon.kma_wrapper import KMA
from genemethods.geneseekr.blast import BLAST
from Bio.Seq import Seq
from Bio import SeqIO
from Bio.SeqRecord import SeqRecord
from glob import glob
import xlsxwriter
import threading
import logging
import pandas
import shutil
import os
import re

__author__ = 'adamkoziol'


class GDCS(object):

    def main(self):
        """
        Run the necessary methods in the correct order
        """
        if not os.path.isfile(self.gdcs_report):
            logging.info('Starting {at} analysis pipeline'.format(at=self.analysistype))
            # Extract the number of core genes found out of the total number of core genes for that genus.
            self.gene_tally()
            # Create the reports
            self.reporter()
        else:
            self.report_parse()

    def gene_tally(self):
        """
        Tally the number of core genes present out of the total number of expected core genes for MLST, rMLST, and
        cgMLST analyses
        """
        for sample in self.runmetadata.samples:
            genes_present = 0
            genes_total = 0
            # Create the GenObject with the necessary attributes
            setattr(sample, self.analysistype, GenObject())
            for analysistype in self.analyses:
                sample[self.analysistype]['{at}_genes_present'.format(at=analysistype)] = 0
                sample[self.analysistype]['{at}_genes_total'.format(at=analysistype)] = 0
                try:
                    # Add the total number of genes in the database of the current analysis type
                    sample[self.analysistype]['{at}_genes_present'.format(at=analysistype)] \
                        += len(sample[analysistype].combined_metadata_results)
                    sample[self.analysistype]['{at}_genes_total'.format(at=analysistype)] \
                        += len(sample[analysistype].combined_metadata_results)
                    # A gene can be present multiple times in the list of the mismatches to sequence type attribute.
                    # Only consider each gene once
                    counted_genes = list()
                    # Subtract genes that are not present in the strain
                    for mismatch in sample[analysistype].mismatchestosequencetype:
                        for gene, allele in mismatch.items():
                            if gene not in counted_genes:
                                counted_genes.append(gene)
                                # If the gene is not present in the strain, and the profile, subtract the gene from
                                # both the genes present and genes total
                                if allele == 'NA (N)':
                                    sample[self.analysistype]['{at}_genes_present'.format(at=analysistype)] -= 1
                                    sample[self.analysistype]['{at}_genes_total'.format(at=analysistype)] -= 1
                                # If the gene is missing in the strain, but present in the profile, only subtract
                                # the gene from the genes present
                                elif 'NA (' in allele:
                                    sample[self.analysistype]['{at}_genes_present'.format(at=analysistype)] -= 1

                except AttributeError:
                    pass
                # Add the MLST and rMLST genes to the running totals
                if analysistype != 'cgmlst':
                    # Increment the genes present and total variables with the results from the current analysis
                    genes_present += sample[self.analysistype]['{at}_genes_present'.format(at=analysistype)]
                    genes_total += sample[self.analysistype]['{at}_genes_total'.format(at=analysistype)]
            # Calculate the total core results
            sample[self.analysistype].coreresults = '{pres}/{total}'.format(pres=genes_present,
                                                                            total=genes_total)

    def reporter(self):
        """
        Create a report of the core genes present / total genes for each strain
        """
        data = 'Strain,Genus,TotalCore,MLST_genes,rMLST_genes,cgMLST_genes,\n'
        for sample in self.runmetadata.samples:
            # Extract the closest reference genus
            try:
                genus = sample.general.closestrefseqgenus
            except AttributeError:
                try:
                    genus = sample.general.referencegenus
                except AttributeError:
                    genus = 'ND'
            data += '{sn},{genus},{total},'.format(sn=sample.name,
                                                   genus=genus,
                                                   total=sample[self.analysistype].coreresults)
            for analysis in self.analyses:
                data += '{present}/{total},'.format(present=sample[self.analysistype]['{at}_genes_present'
                                                    .format(at=analysis)],
                                                    total=sample[self.analysistype]['{at}_genes_total'
                                                    .format(at=analysis)])
            data += '\n'
        with open(self.gdcs_report, 'w') as report:
            report.write(data)

    def report_parse(self):
        """
        Parse an existing GDCS report, and extract the results
        """
        nesteddictionary = dict()
        # Use pandas to read in the CSV file, and convert the pandas data frame to a dictionary (.to_dict())
        dictionary = pandas.read_csv(self.gdcs_report).to_dict()
        # Iterate through the dictionary - each header from the CSV file
        for header in dictionary:
            # Sample is the primary key, and value is the value of the cell for that primary key + header combination
            for sample, value in dictionary[header].items():
                # Update the dictionary with the new data
                if sample not in nesteddictionary:
                    nesteddictionary[sample] = dict()
                nesteddictionary[sample].update({header: value})
        for sample in self.runmetadata.samples:
            # Create the GenObject with the necessary attributes
            setattr(sample, self.analysistype, GenObject())
        report_strains = list()
        for key in nesteddictionary:
            strain = nesteddictionary[key]['Strain']
            report_strains.append(strain)
            for sample in self.runmetadata.samples:
                if strain == sample.name:
                    self.genobject_populate(key=key,
                                            sample=sample,
                                            nesteddictionary=nesteddictionary)
        for sample in self.runmetadata.samples:
            if sample.name not in report_strains:
                self.genobject_populate(key=None,
                                        sample=sample,
                                        nesteddictionary=dict())

    def genobject_populate(self, key, sample, nesteddictionary):
        try:
            # Pull the necessary values from the report
            for header, value in nesteddictionary[key].items():
                if header == 'TotalCore':
                    sample[self.analysistype].coreresults = value
                elif header == 'MLST_genes':
                    sample[self.analysistype].mlst_genes_present, sample[self.analysistype].mlst_genes_total \
                        = value.split('/')
                elif header == 'rMLST_genes':
                    sample[self.analysistype].rmlst_genes_present, \
                    sample[self.analysistype].rmlst_genes_total \
                        = value.split('/')
        except KeyError:
            pass

    def __init__(self, inputobject):
        self.reports = str()
        self.samples = inputobject.runmetadata
        self.starttime = inputobject.starttime
        self.completemetadata = inputobject.runmetadata
        self.path = inputobject.path
        self.analysescomplete = True
        self.reportpath = inputobject.reportpath
        self.runmetadata = inputobject.runmetadata
        self.homepath = inputobject.homepath
        self.analysistype = 'gdcs'
        self.cutoff = 0.9
        self.pipeline = True
        self.revbait = False
        self.sequencepath = inputobject.path
        self.targetpath = os.path.join(inputobject.reffilepath, self.analysistype)
        self.cpus = inputobject.cpus
        self.threads = int(self.cpus / len(self.runmetadata.samples)) \
            if self.cpus / len(self.runmetadata.samples) > 1 else 1
        self.logfile = inputobject.logfile
        self.analyses = ['mlst', 'rmlst', 'cgmlst']
        self.gdcs_report = os.path.join(self.reportpath, '{at}.csv'.format(at=self.analysistype))


class Plasmids(GeneSippr):

    def runner(self):
        """
        Run the necessary methods in the correct order
        """
        logging.info('Starting {at} analysis pipeline'.format(at=self.analysistype))
        if not self.pipeline:
            general = None
            for sample in self.runmetadata.samples:
                general = getattr(sample, 'general')
            if general is None:
                # Create the objects to be used in the analyses
                objects = Objectprep(self)
                objects.objectprep()
                self.runmetadata = objects.samples
        # Run the analyses
        ShortKSippingMethods(self, self.cutoff)
        # Create the reports
        self.reporter()
        # Print the metadata
        MetadataPrinter(self)

    def reporter(self):
        """
        Creates a report of the results
        """
        # Create the path in which the reports are stored
        make_path(self.reportpath)
        data = 'Strain,Gene,PercentIdentity,Length,FoldCoverage\n'
        with open(os.path.join(self.reportpath, self.analysistype + '.csv'), 'w') as report:
            for sample in self.runmetadata.samples:
                data += sample.name + ','
                try:
                    if sample[self.analysistype].results:
                        multiple = False
                        for name, identity in sample[self.analysistype].results.items():
                            if not multiple:
                                data += '{},{},{},{}\n'.format(name, identity,
                                                               len(sample[self.analysistype].sequences[name]),
                                                               sample[self.analysistype].avgdepth[name])
                            else:
                                data += ',{},{},{},{}\n'.format(name, identity,
                                                                len(sample[self.analysistype].sequences[name]),
                                                                sample[self.analysistype].avgdepth[name])
                            multiple = True
                    else:
                        data += '\n'
                except AttributeError:
                    data += '\n'
            report.write(data)


class PlasmidExtractor(object):

    def main(self):
        """
        Run the methods in the correct order
        """
        self.run_plasmid_extractor()
        self.parse_report()

    def run_plasmid_extractor(self):
        """
        Create and run the plasmid extractor system call
        """
        logging.info('Extracting plasmids')
        # Define the system call
        extract_command = 'PlasmidExtractor.py -i {inf} -o {outf} -p {plasdb} -d {db} -t {cpus} -nc' \
            .format(inf=self.path,
                    outf=self.plasmid_output,
                    plasdb=os.path.join(self.plasmid_db, 'plasmid_db.fasta'),
                    db=self.plasmid_db,
                    cpus=self.cpus)
        # Only attempt to extract plasmids if the report doesn't already exist
        if not os.path.isfile(self.plasmid_report):
            # Run the system calls
            out, err = run_subprocess(extract_command)
            # Acquire thread lock, and write the logs to file
            self.threadlock.acquire()
            write_to_logfile(extract_command, extract_command, self.logfile)
            write_to_logfile(out, err, self.logfile)
            self.threadlock.release()

    def parse_report(self):
        """
        Parse the plasmid extractor report, and populate metadata objects
        """
        logging.info('Parsing Plasmid Extractor outputs')
        # A dictionary to store the parsed excel file in a more readable format
        nesteddictionary = dict()
        # Use pandas to read in the CSV file, and convert the pandas data frame to a dictionary (.to_dict())
        dictionary = pandas.read_csv(self.plasmid_report).to_dict()
        # Iterate through the dictionary - each header from the CSV file
        for header in dictionary:
            # Sample is the primary key, and value is the value of the cell for that primary key + header combination
            for sample, value in dictionary[header].items():
                # Update the dictionary with the new data
                try:
                    nesteddictionary[sample].update({header: value})
                # Create the nested dictionary if it hasn't been created yet
                except KeyError:
                    nesteddictionary[sample] = dict()
                    nesteddictionary[sample].update({header: value})
        # Get the results into the metadata object
        for sample in self.metadata:
            # Initialise the plasmid extractor genobject
            setattr(sample, self.analysistype, GenObject())
            # Initialise the list of all plasmids
            sample[self.analysistype].plasmids = list()
            # Iterate through the dictionary of results
            for line in nesteddictionary:
                # Extract the sample name from the dictionary in a manner consistent with the rest of the COWBAT
                # pipeline e.g. 2014-SEQ-0276_S2_L001 becomes 2014-SEQ-0276
                sample_name = nesteddictionary[line]['Sample']
                # Use the filer method to extract the name
                name = list(filer([sample_name]))[0]
                # Ensure that the names match
                if name == sample.name:
                    # Append the plasmid name extracted from the dictionary to the list of plasmids
                    sample[self.analysistype].plasmids.append(nesteddictionary[line]['Plasmid'])
        # Copy the report to the folder containing all reports for the pipeline
        try:
            shutil.copyfile(self.plasmid_report, os.path.join(self.reportpath, 'plasmidReport.csv'))
        except IOError:
            pass

    def __init__(self, inputobject):
        self.path = inputobject.path
        self.reportpath = inputobject.reportpath
        self.reffilepath = inputobject.reffilepath
        self.analysistype = 'plasmidextractor'
        self.plasmid_output = os.path.join(self.path, self.analysistype)
        self.plasmid_db = os.path.join(self.reffilepath, self.analysistype)
        self.plasmid_report = os.path.join(self.plasmid_output, 'plasmidReport.csv')
        self.start = inputobject.starttime
        self.cpus = inputobject.cpus
        self.logfile = inputobject.logfile
        self.threadlock = threading.Lock()
        self.metadata = inputobject.runmetadata.samples


class Serotype(SeroSippr):

    def runner(self):
        """
        Run the necessary methods in the correct order
        """
        sero_report = os.path.join(self.reportpath, 'serosippr.csv')
        if os.path.isfile(sero_report):
            self.report_parse(sero_report)
        else:
            logging.info('Starting {} analysis pipeline'.format(self.analysistype))
            # Run the analyses
            ShortKSippingMethods(self, self.cutoff)
            self.serotype_escherichia()
            self.serotype_salmonella()
            # Create the reports
            self.reporter()
            # Print the metadata
            MetadataPrinter(self)

    def report_parse(self, sero_report):
        """
        Parse an existing report, and extract the results
        :param sero_report: type STR: Name and absolute path of the report
        """
        with open(sero_report, 'r') as report:
            next(report)
            for line in report:
                data = line.rstrip().split(',')
                for sample in self.runmetadata.samples:
                    if sample.name in line:
                        if data[1]:
                            setattr(sample, self.analysistype, GenObject())
                            o_results, h_results = data[1].split(':')
                            sample[self.analysistype].o_set = [o_results.split(' ')[0]]
                            try:
                                sample[self.analysistype].best_o_pid = o_results.split(' ')[1].replace('(', '') \
                                    .replace(')', '')
                            except IndexError:
                                sample[self.analysistype].best_o_pid = 'ND'
                            sample[self.analysistype].h_set = [h_results.split(' ')[0]]
                            try:
                                sample[self.analysistype].best_h_pid = h_results.split(' ')[1].replace('(', '') \
                                    .replace(')', '')
                            except IndexError:
                                sample[self.analysistype].best_h_pid = 'ND'


class ShortKSippingMethods(Sippr):

    def main(self):
        """
        Run the methods in the correct order for pipelines
        """
        # Find the target files
        self.targets()
        kmer = 15 if self.analysistype == 'GDCS' else 17
        # Use bbduk to bait the FASTQ reads matching the target sequences
        self.bait(maskmiddle='t', k=kmer)
        # If desired, use bbduk to bait the target sequences with the previously baited FASTQ files
        if self.revbait:
            self.reversebait(maskmiddle='t', k=kmer)
        # Run the bowtie2 read mapping module
        self.mapping()
        # Use samtools to index the sorted bam file
        self.indexing()
        # Parse the results
        # self.parsing()
        self.parsebam()
        # Filter out any sequences with cigar features such as internal soft-clipping from the results
        # self.clipper()


class ResSippr(GeneSippr):

    def runner(self):
        """
        Run the necessary methods in the correct order
        """
        logging.info('Starting {} analysis pipeline'.format(self.analysistype))
        if not self.pipeline:
            general = None
            for sample in self.runmetadata.samples:
                general = getattr(sample, 'general')
            if general is None:
                # Create the objects to be used in the analyses
                objects = Objectprep(self)
                objects.objectprep()
                self.runmetadata = objects.samples
        # Run the analyses
        ShortKSippingMethods(inputobject=self,
                             cutoff=self.cutoff,
                             allow_soft_clips=self.allow_soft_clips)

    # noinspection PyMissingConstructor
    def __init__(self, args, pipelinecommit, startingtime, scriptpath, analysistype, cutoff, pipeline, revbait,
                 allow_soft_clips=False):
        """
        :param args: command line arguments
        :param pipelinecommit: pipeline commit or version
        :param startingtime: time the script was started
        :param scriptpath: home path of the script
        :param analysistype: name of the analysis being performed - allows the program to find databases
        :param cutoff: percent identity cutoff for matches
        :param pipeline: boolean of whether this script needs to run as part of a particular assembly pipeline
        :param allow_soft_clips: Boolean whether the BAM parsing should exclude sequences with internal soft clips
        """
        # Initialise variables
        # super().__init__(args, pipelinecommit, startingtime, scriptpath, analysistype, cutoff, pipeline, revbait)
        self.commit = str(pipelinecommit)
        self.starttime = startingtime
        self.homepath = scriptpath
        # Define variables based on supplied arguments
        self.path = os.path.join(args.path)
        assert os.path.isdir(self.path), u'Supplied path is not a valid directory {0!r:s}'.format(self.path)
        try:
            self.sequencepath = os.path.join(args.sequencepath)
        except AttributeError:
            self.sequencepath = self.path
        assert os.path.isdir(self.sequencepath), u'Sequence path  is not a valid directory {0!r:s}' \
            .format(self.sequencepath)
        try:
            self.targetpath = os.path.join(args.reffilepath, analysistype)
        except AttributeError:
            self.targetpath = os.path.join(args.targetpath)
        self.reportpath = os.path.join(self.path, 'reports')
        assert os.path.isdir(self.targetpath), u'Target path is not a valid directory {0!r:s}' \
            .format(self.targetpath)
        try:
            self.bcltofastq = args.bcltofastq
        except AttributeError:
            self.bcltofastq = False
        try:
            self.miseqpath = args.miseqpath
        except AttributeError:
            self.miseqpath = str()
        try:
            self.miseqfolder = args.miseqfolder
        except AttributeError:
            self.miseqfolder = str()
        try:
            self.fastqdestination = args.fastqdestination
        except AttributeError:
            self.fastqdestination = str()
        try:
            self.forwardlength = args.forwardlength
        except AttributeError:
            self.forwardlength = 'full'
        try:
            self.reverselength = args.reverselength
        except AttributeError:
            self.reverselength = 'full'
        self.numreads = 2 if self.reverselength != 0 else 1
        try:
            self.customsamplesheet = args.customsamplesheet
        except AttributeError:
            self.customsamplesheet = False
        self.logfile = args.logfile
        # Set the custom cutoff value
        self.cutoff = float(cutoff)
        try:
            self.averagedepth = int(args.averagedepth)
        except AttributeError:
            self.averagedepth = 10
        try:
            self.copy = args.copy
        except AttributeError:
            self.copy = False
        self.runmetadata = args.runmetadata
        # Use the argument for the number of threads to use, or default to the number of cpus in the system
        self.cpus = int(args.cpus)
        try:
            self.threads = int(self.cpus / len(self.runmetadata.samples)) if self.cpus / len(self.runmetadata.samples) \
                                                                             > 1 else 1
        except TypeError:
            self.threads = self.cpus
        self.taxonomy = {'Escherichia': 'coli', 'Listeria': 'monocytogenes', 'Salmonella': 'enterica'}
        self.analysistype = analysistype
        self.pipeline = pipeline
        self.revbait = revbait
        self.allow_soft_clips = allow_soft_clips


class Resistance(ResSippr):

    def main(self):
        res_report = os.path.join(self.reportpath, 'resfinder.csv')
        if os.path.isfile(res_report):
            self.parse_report(res_report=res_report)
        else:
            self.runner()
            # Create the reports
            self.reporter()

    def parse_report(self, res_report):
        """
        Parse an existing report, and extract the results
        :param res_report: type STR: name and absolute path of the report
        """
        for sample in self.runmetadata.samples:
            setattr(sample, self.analysistype, GenObject())
            sample[self.analysistype].results = dict()
            sample[self.analysistype].pipelineresults = list()
            sample[self.analysistype].avgdepth = dict()
            with open(res_report, 'r') as report:
                next(report)
                for line in report:
                    try:
                        strain, res, gene, allele, accession, perc_ident, length, fold_cov = line.rstrip().split(',')
                        if sample.name in line:
                            if strain:
                                name = '{gene}_{accession}_{allele}'.format(gene=gene,
                                                                            accession=accession,
                                                                            allele=allele)
                                sample[self.analysistype].results[name] = perc_ident
                                sample[self.analysistype].pipelineresults.append(
                                    '{rgene} ({pid}%) {rclass}'.format(rgene=gene,
                                                                       pid=perc_ident,
                                                                       rclass=res))
                                sample[self.analysistype].avgdepth[name] = fold_cov
                    except ValueError:
                        pass

    def reporter(self):
        """
        Creates a report of the results
        """
        logging.info('Creating {at} report'.format(at=self.analysistype))
        resistance_classes = ResistanceNotes.classes(self.targetpath)
        # Find unique gene names with the highest percent identity
        for sample in self.runmetadata.samples:
            try:
                if sample[self.analysistype].results:
                    # Initialise a dictionary to store the unique genes, and their percent identities
                    sample[self.analysistype].uniquegenes = dict()
                    for name, identity in sample[self.analysistype].results.items():
                        # Split the name of the gene from the string e.g. ARR-2_1_HQ141279 yields ARR-2
                        genename = name.split('_')[0]
                        # Set the best observed percent identity for each unique gene
                        try:
                            # Pull the previous best identity from the dictionary
                            bestidentity = sample[self.analysistype].uniquegenes[genename]
                            # If the current identity is better than the old identity, save it
                            if float(identity) > float(bestidentity):
                                sample[self.analysistype].uniquegenes[genename] = float(identity)
                        # Initialise the dictionary if necessary
                        except KeyError:
                            sample[self.analysistype].uniquegenes[genename] = float(identity)
            except AttributeError:
                pass
        # Create the path in which the reports are stored
        make_path(self.reportpath)
        # Initialise strings to store the results
        data = 'Strain,Resistance,Gene,Allele,Accession,PercentIdentity,Length,FoldCoverage\n'
        with open(os.path.join(self.reportpath, self.analysistype + '.csv'), 'w') as report:
            for sample in self.runmetadata.samples:
                # Create an attribute to store the string for the eventual pipeline report
                sample[self.analysistype].pipelineresults = list()
                if sample[self.analysistype].results:
                    results = False
                    for name, identity in sorted(sample[self.analysistype].results.items()):
                        # Extract the necessary variables from the gene name string
                        gname, genename, accession, allele = ResistanceNotes.gene_name(name)
                        # Retrieve the best identity for each gene
                        try:
                            percentid = sample[self.analysistype].uniquegenes[gname]
                        # Beta-lactamases will not have the allele and version from the gene name defined above
                        except KeyError:
                            percentid = sample[self.analysistype].uniquegenes[gname.split('-')[0]]
                        # If the percent identity of the current gene matches the best percent identity, add it to
                        # the report - there can be multiple occurrences of genes e.g.
                        # sul1,1,AY224185,100.00,840 and sul1,2,CP002151,100.00,927 are both included because they
                        # have the same 100% percent identity
                        if float(identity) == percentid:
                            try:
                                # Determine resistance phenotype of the gene
                                res = ResistanceNotes.resistance(name, resistance_classes)
                                # Populate the results
                                data += '{sn},{res},{gene},{allele},{accession},{identity},{length},{depth}\n'.format(
                                    sn=sample.name,
                                    res=res,
                                    gene=genename,
                                    allele=allele,
                                    accession=accession,
                                    identity=identity,
                                    length=len(sample[self.analysistype].sequences[name]),
                                    depth=sample[self.analysistype].avgdepth[name])
                                sample[self.analysistype].pipelineresults.append(
                                    '{rgene} ({pid}%) {rclass}'.format(rgene=genename,
                                                                       pid=identity,
                                                                       rclass=res)
                                )
                                results = True
                            except KeyError:
                                pass
                    if not results:
                        data += '{sn}\n'.format(sn=sample.name)
                else:
                    data += '{sn}\n'.format(sn=sample.name)
            # Write the string to the file
            report.write(data)


class ResFinder(GeneSeekr):

    @staticmethod
    def sequencenames(contigsfile):
        """
        Takes a multifasta file and returns a list of sequence names
        :param contigsfile: multifasta of all sequences
        :return: list of all sequence names
        """
        sequences = list()
        for record in SeqIO.parse(open(contigsfile, "rU", encoding="iso-8859-15"), "fasta"):
            sequences.append(record.id)
        return sequences

    def strainer(self):
        for sample in self.metadata:
            if sample.general.bestassemblyfile != 'NA':
                setattr(sample, self.analysistype, GenObject())
                targets = glob(os.path.join(self.targetpath, '*.tfa'))
                targetcheck = glob(os.path.join(self.targetpath, '*.tfa'))
                if targetcheck:
                    try:
                        combinedtargets = glob(os.path.join(self.targetpath, '*.fasta'))[0]
                    except IndexError:
                        combinetargets(targets, self.targetpath)
                        combinedtargets = glob(os.path.join(self.targetpath, '*.fasta'))[0]
                    sample[self.analysistype].targets = targets
                    sample[self.analysistype].combinedtargets = combinedtargets
                    sample[self.analysistype].targetpath = self.targetpath
                    sample[self.analysistype].targetnames = self.sequencenames(combinedtargets)
                    sample[self.analysistype].reportdir = os.path.join(sample.general.outputdirectory,
                                                                       self.analysistype)
                    make_path(sample[self.analysistype].reportdir)
                else:
                    # Set the metadata file appropriately
                    sample[self.analysistype].targets = 'NA'
                    sample[self.analysistype].combinedtargets = 'NA'
                    sample[self.analysistype].targetpath = 'NA'
                    sample[self.analysistype].targetnames = 'NA'
                    sample[self.analysistype].reportdir = 'NA'
                    sample[self.analysistype].blastresults = 'NA'
            else:
                # Set the metadata file appropriately
                setattr(sample, self.analysistype, GenObject())
                sample[self.analysistype].targets = 'NA'
                sample[self.analysistype].combinedtargets = 'NA'
                sample[self.analysistype].targetpath = 'NA'
                sample[self.analysistype].targetnames = 'NA'
                sample[self.analysistype].reportdir = 'NA'
                sample[self.analysistype].blastresults = 'NA'

    def resfinderreporter(self):
        """
        Custom reports for ResFinder analyses. These reports link the gene(s) found to their resistance phenotypes
        """
        # Initialise resistance dictionaries from the notes.txt file
        resistance_classes = ResistanceNotes.classes(self.targetpath)
        # Create a workbook to store the report. Using xlsxwriter rather than a simple csv format, as I want to be
        # able to have appropriately sized, multi-line cells
        workbook = xlsxwriter.Workbook(os.path.join(self.reportpath, '{}.xlsx'.format(self.analysistype)))
        # New worksheet to store the data
        worksheet = workbook.add_worksheet()
        # Add a bold format for header cells. Using a monotype font size 10
        bold = workbook.add_format({'bold': True, 'font_name': 'Courier New', 'font_size': 8})
        # Format for data cells. Monotype, size 10, top vertically justified
        courier = workbook.add_format({'font_name': 'Courier New', 'font_size': 8})
        courier.set_align('top')
        # Initialise the position within the worksheet to be (0,0)
        row = 0
        col = 0
        # A dictionary to store the column widths for every header
        columnwidth = dict()
        extended = False
        headers = ['Strain', 'Gene', 'Allele', 'Resistance', 'PercentIdentity', 'PercentCovered', 'Contig', 'Location',
                   'nt_sequence']
        for sample in self.metadata:
            # Create an attribute to store the string for the eventual pipeline report
            sample[self.analysistype].pipelineresults = list()
            sample[self.analysistype].sampledata = list()
            try:
                blastresults = sample[self.analysistype].blastresults
            except AttributeError:
                blastresults = 'NA'
            # Process the sample only if the script could find targets
            if blastresults != 'NA':
                for result in sample[self.analysistype].blastresults:
                    # Set the name to avoid writing out the dictionary[key] multiple times
                    name = result['subject_id']
                    # Use the ResistanceNotes gene name extraction method to get the necessary variables
                    gname, genename, accession, allele = ResistanceNotes.gene_name(name)
                    # Initialise a list to store all the data for each strain
                    data = list()
                    # Determine resistance phenotype of the gene
                    resistance = ResistanceNotes.resistance(name, resistance_classes)
                    # Append the necessary values to the data list
                    data.append(genename)
                    data.append(allele)
                    data.append(resistance)
                    percentid = result['percentidentity']
                    data.append(percentid)
                    data.append(result['alignment_fraction'])
                    data.append(result['query_id'])
                    data.append('...'.join([str(result['low']), str(result['high'])]))
                    try:
                        # Populate the attribute storing the resfinder results
                        sample[self.analysistype].pipelineresults.append(
                            '{rgene} ({pid}%) {rclass}'.format(rgene=genename,
                                                               pid=percentid,
                                                               rclass=resistance))
                        # Only if the alignment option is selected, for inexact results, add alignments
                        if self.align and percentid != 100.00:

                            # Align the protein (and nucleotide) sequences to the reference
                            self.alignprotein(sample, name)
                            if not extended:
                                # Add the appropriate headers
                                headers.extend(['aa_Identity',
                                                'aa_Alignment',
                                                'aa_SNP_location',
                                                'nt_Alignment',
                                                'nt_SNP_location'
                                                ])
                                extended = True
                            # Create a FASTA-formatted sequence output of the query sequence
                            record = SeqRecord(sample[self.analysistype].dnaseq[name],
                                               id='{}_{}'.format(sample.name, name),
                                               description='')
                            # Add the alignment, and the location of mismatches for both nucleotide and amino
                            # acid sequences
                            data.extend([record.format('fasta'),
                                         sample[self.analysistype].aaidentity[name],
                                         sample[self.analysistype].aaalign[name],
                                         sample[self.analysistype].aaindex[name],
                                         sample[self.analysistype].ntalign[name],
                                         sample[self.analysistype].ntindex[name]
                                         ])
                        else:
                            record = SeqRecord(Seq(result['subject_sequence']),
                                               id='{}_{}'.format(sample.name, name),
                                               description='')
                            data.append(record.format('fasta'))
                            if self.align:
                                # Add '-'s for the empty results, as there are no alignments for exact matches
                                data.extend(['100', '-', '-', '-', '-'])
                    # If there are no blast results for the target, add a '-'
                    except (KeyError, TypeError):
                        data.append('-')
                    sample[self.analysistype].sampledata.append(data)

        if 'nt_sequence' not in headers:
            headers.append('nt_sequence')
        # Write the header to the spreadsheet
        for header in headers:
            worksheet.write(row, col, header, bold)
            # Set the column width based on the longest header
            try:
                columnwidth[col] = len(header) if len(header) > columnwidth[col] else columnwidth[
                    col]
            except KeyError:
                columnwidth[col] = len(header)
            worksheet.set_column(col, col, columnwidth[col])
            col += 1
        # Increment the row and reset the column to zero in preparation of writing results
        row += 1
        col = 0
        # Write out the data to the spreadsheet
        for sample in self.metadata:
            if not sample[self.analysistype].sampledata:
                # Increment the row and reset the column to zero in preparation of writing results
                row += 1
                col = 0
                # Set the width of the row to be the number of lines (number of newline characters) * 12
                worksheet.set_row(row)
                worksheet.set_column(col, col, columnwidth[col])
            for data in sample[self.analysistype].sampledata:
                columnwidth[col] = len(sample.name) + 2
                worksheet.set_column(col, col, columnwidth[col])
                worksheet.write(row, col, sample.name, courier)
                col += 1
                # List of the number of lines for each result
                totallines = list()
                for results in data:
                    #
                    worksheet.write(row, col, results, courier)
                    try:
                        # Counting the length of multi-line strings yields columns that are far too wide, only count
                        # the length of the string up to the first line break
                        alignmentcorrect = len(str(results).split('\n')[1])
                        # Count the number of lines for the data
                        lines = results.count('\n') if results.count('\n') >= 1 else 1
                        # Add the number of lines to the list
                        totallines.append(lines)
                    except IndexError:
                        try:
                            # Counting the length of multi-line strings yields columns that are far too wide, only count
                            # the length of the string up to the first line break
                            alignmentcorrect = len(str(results).split('\n')[0])
                            # Count the number of lines for the data
                            lines = results.count('\n') if results.count('\n') >= 1 else 1
                            # Add the number of lines to the list
                            totallines.append(lines)
                        # If there are no newline characters, set the width to the length of the string
                        except AttributeError:
                            alignmentcorrect = len(str(results))
                            lines = 1
                            # Add the number of lines to the list
                            totallines.append(lines)
                    # Increase the width of the current column, if necessary
                    try:
                        columnwidth[col] = alignmentcorrect if alignmentcorrect > columnwidth[col] else \
                            columnwidth[col]
                    except KeyError:
                        columnwidth[col] = alignmentcorrect
                    worksheet.set_column(col, col, columnwidth[col])
                    col += 1
                # Set the width of the row to be the number of lines (number of newline characters) * 12
                worksheet.set_row(row, max(totallines) * 11)
                # Increase the row counter for the next strain's data
                row += 1
                col = 0
        # Close the workbook
        workbook.close()

    def object_clean(self):
        """
        Remove large attributes from the metadata objects
        """
        for sample in self.metadata:
            try:
                delattr(sample[self.analysistype], 'aaidentity')
                delattr(sample[self.analysistype], 'aaalign')
                delattr(sample[self.analysistype], 'aaindex')
                delattr(sample[self.analysistype], 'ntalign')
                delattr(sample[self.analysistype], 'ntindex')
                delattr(sample[self.analysistype], 'dnaseq')
                delattr(sample[self.analysistype], 'blastresults')
            except AttributeError:
                pass

    def __init__(self, inputobject):
        self.resfinderfields = ['query_id', 'subject_id', 'positives', 'mismatches', 'gaps', 'evalue', 'bit_score',
                                'subject_length', 'alignment_length', 'query_start', 'query_end']
        self.analysistype = 'resfinder_assembled'
        self.metadata = inputobject.runmetadata.samples
        self.cutoff = 70
        self.start = inputobject.starttime
        self.reportdir = inputobject.reportpath
        self.pipeline = True
        self.referencefilepath = inputobject.reffilepath
        self.targetpath = os.path.join(self.referencefilepath, 'resfinder')
        self.threads = inputobject.cpus
        self.align = True
        self.logfile = inputobject.logfile
        self.unique = True
        self.strainer()
        self.runmetadata = MetadataObject()
        self.runmetadata.samples = self.metadata
        GeneSeekr.__init__(self, self)
        self.resfinderreporter()
        self.object_clean()


class Prophages(BLAST):

    def create_reports(self):
        with open(os.path.join(self.reportpath, 'prophages.csv'), 'w') as report:
            data = 'Strain,Gene,Host,PercentIdentity,PercentCovered,Contig,Location\n'
            # Set the required variables to load prophage data from a summary file
            overview = glob(os.path.join(self.targetpath, '*.txt'))[0]
            # A dictionary to store the parsed excel file in a more readable format
            prophagedata = dict()
            # Use pandas to read in the excel file, and subsequently convert the pandas data frame to a dictionary
            # (.to_dict()). Only read the first fourteen columns (parse_cols=range(14)), as later columns are not
            # relevant to this script
            dictionary = pandas.read_csv(overview, sep='\t').to_dict()
            # Iterate through the dictionary - each header from the excel file
            for header in dictionary:
                # Sample is the primary key, and value is the value of the cell for that primary key + header combo
                for sample, value in dictionary[header].items():
                    # Update the dictionary with the new data
                    try:
                        prophagedata[sample].update({header: value})
                    # Create the nested dictionary if it hasn't been created yet
                    except KeyError:
                        prophagedata[sample] = dict()
                        prophagedata[sample].update({header: value})
            for sample in self.metadata:
                # Create a set to ensure that genes are only entered into the report once
                genes = set()
                if sample.general.bestassemblyfile != 'NA':
                    try:
                        if sample[self.analysistype].blastlist:
                            for result in sample[self.analysistype].blastlist:
                                gene = result['subject_id']
                                if gene not in genes:
                                    # Iterate through the phage data in the dictionary
                                    for query_id, phage in prophagedata.items():
                                        if phage['id_prophage'] == gene:
                                            # Add the data to the row
                                            data += '{sn},{gene},{host},{ident},{cov},{contig},{start}..{stop}\n' \
                                                .format(sn=sample.name,
                                                        gene=gene,
                                                        host=phage['host'],
                                                        ident=result['percentidentity'],
                                                        cov=result['alignment_fraction'] if float(
                                                            result['alignment_fraction']) <= 100 else '100.0',
                                                        contig=result['query_id'],
                                                        start=result['low'],
                                                        stop=result['high'])
                                    genes.add(gene)
                                    # Set multiple to true for any additional hits for this sample
                        else:
                            data += '{sn}\n'.format(sn=sample.name)
                    except AttributeError:
                        data += '{sn}\n'.format(sn=sample.name)
                else:
                    data += '{sn}\n'.format(sn=sample.name)
            report.write(data)


class Univec(BLAST):

    def create_reports(self):
        with open(os.path.join(self.reportpath, 'univec.csv'), 'w') as report:
            data = 'Strain,Gene,Description,PercentIdentity,PercentCovered,Contig,Location\n'
            for sample in self.metadata:
                if sample.general.bestassemblyfile != 'NA':
                    # Create a set to ensure that genes are only entered into the report once
                    genes = set()
                    try:
                        if sample[self.analysistype].blastlist:
                            gene_set = set()
                            for result in sample[self.analysistype].blastlist:
                                gene_set.add(result['subject_id'])
                            for gene in sorted(list(gene_set)):
                                for result in sample[self.analysistype].blastlist:
                                    if gene == result['subject_id']:
                                        # Parse the reference file in order to extract the description of the BLAST hits
                                        for entry in SeqIO.parse(sample[self.analysistype].combinedtargets, 'fasta'):
                                            # Find the corresponding entry for the gene
                                            if entry.id.lstrip('g') == gene:
                                                # Cut out the description from the entry.description using regex
                                                # e.g. 'gnl|uv|X66730.1:1-2687-49 B.bronchiseptica plasmid pBBR1 genes
                                                # for mobilization and replication' only save the string after '2687-49'
                                                description = re.findall('\d+-\d+\s(.+)', entry.description)[0]
                                                # Replace commas with semicolons
                                                description = description.replace(',', ';')
                                                # Don't add the same gene more than once to the report
                                                if gene not in genes:
                                                    data += '{sn},{gene},{desc},{pi},{pc},{cont},{start}..{stop}\n' \
                                                        .format(sn=sample.name,
                                                                gene=gene.split('|')[-1],
                                                                desc=description,
                                                                pi=result['percentidentity'],
                                                                pc=result['alignment_fraction'] if float(
                                                                    result['alignment_fraction']) <= 100 else '100.0',
                                                                cont=result['query_id'],
                                                                start=result['low'],
                                                                stop=result['high'])
                                                    # Add the gene name to the set
                                                    genes.add(gene)
                        else:
                            data += '{sn}\n'.format(sn=sample.name)
                    except AttributeError:
                        data += '{sn}\n'.format(sn=sample.name)
                else:
                    data += '{sn}\n'.format(sn=sample.name)
            report.write(data)


class Verotoxin(KMA):

    def main(self):
        self.targets()
        self.index_targets()
        self.load_kma_db()
        self.run_kma_mem_mode()
        self.run_kma()
        self.unload_kma_db()
        self.parse_kma_outputs()
        self.verotoxin_subtyping()
        self.reporter()
        self.kma_report()

    def verotoxin_subtyping(self):
        """
        Use the virulence results to perform verotoxin subtyping analyses
        """
        logging.info('Performing verotoxin subtyping')
        for sample in self.runmetadata.samples:
            sample[self.analysistype].verotoxin_subtypes = dict()
            sample[self.analysistype].verotoxin_subtypes_set = set()
            sample[self.analysistype].verotoxindict = dict()
            if sample[self.analysistype].kmaresults:
                # If there are many results for a sample, don't write the sample name in each line of the report
                for name, identity in sorted(sample[self.analysistype].kmaresults.items()):
                    if 'stx' in name:
                        try:
                            if ':' in name:
                                gene, allele, accession, subtype = name.split(':')
                            else:
                                gene, accession, subtype = name.split('_')
                            # Split off the 'stx' from the name
                            gene_type = gene.split('stx')[-1]
                            self.dictionary_populate(sample=sample,
                                                     gene_type=gene_type,
                                                     subtype=subtype,
                                                     identity=identity)
                        # Ignore entries without a subtype
                        except ValueError:
                            pass
                # Perform subtyping - iterate through the three categories of verotoxin genes: vtx1 and vtx2 with
                # subunits, and vtx2 without a subunit
                for a_subunit in ['1A', '2A', '2']:
                    # Use the subunit name to set the name of the B subunit
                    b_subunit = a_subunit.replace('A', 'B')
                    # Determine whether the verotoxin gene is vtx1 or vtx2
                    verotoxin_gene = a_subunit[0]
                    # If the sample lacks a particular verotoxin subunit, a KeyError will occur. This is fine. Not
                    # all samples have any/all verotoxin subunits
                    try:
                        for subtype, percent_id in sorted(sample[self.analysistype].verotoxindict[a_subunit].items()):
                            # Create a string to with the desired output name of the gene/subtype
                            vtx_gene = 'vtx{gene}{subtype}'.format(gene=verotoxin_gene,
                                                                   subtype=subtype)
                            # The subunit-less '2' verotoxin gene needs special treatment
                            if a_subunit != '2':
                                try:
                                    # Populate the dictionary with the verotoxin gene: (subunit A %ID, subunit B %ID)
                                    # e.g. vtx2A: (100.0, 100.0)
                                    sample[self.analysistype].verotoxin_subtypes[vtx_gene] = \
                                        (percent_id,
                                         sample[self.analysistype].verotoxindict[b_subunit][subtype])
                                    # Add the verotoxin gene to the set of sample subtypes
                                    sample[self.analysistype].verotoxin_subtypes_set.add(vtx_gene)
                                except KeyError:
                                    # There are no 2B genes present in the database for subtype vtx2b, allow a match
                                    # for this subtype if only the '2A' gene is present
                                    if a_subunit == '2A' and subtype == 'b':
                                        sample[self.analysistype].verotoxin_subtypes[vtx_gene] = (percent_id,)
                                        sample[self.analysistype].verotoxin_subtypes_set.add(vtx_gene)
                            else:
                                # Only add the results from the subunit-less gene if it is the only match for that
                                # subtype. e.g. if vtx2b already is present in the dictionary, do not look at the hits
                                # for it again
                                if vtx_gene not in sample[self.analysistype].verotoxin_subtypes:
                                    sample[self.analysistype].verotoxin_subtypes[vtx_gene] = (percent_id,)
                                    sample[self.analysistype].verotoxin_subtypes_set.add(vtx_gene)
                    except KeyError:
                        pass
                # Create a string summarizing the verotoxin subtypes present. Create a semi-colon-separated list of the
                # sorted subtypes e.g. vtx1a;vtx2a;vtx2c if there were subtypes detected. Otherwise, set the subtype
                # to 'ND'
                sample[self.analysistype].verotoxin_subtypes_set = \
                    ';'.join(sorted(sample[self.analysistype].verotoxin_subtypes_set)) \
                    if sample[self.analysistype].verotoxin_subtypes_set else 'ND'
            # If there are no results, set the profile to 'ND'
            else:
                sample[self.analysistype].verotoxin_subtypes_set = 'ND'

    def dictionary_populate(self, sample, gene_type, subtype, identity):
        """
        Populate the supplied nested dictionary with the necessary values. Initialise the dictionary as required
        """
        if gene_type not in sample[self.analysistype].verotoxindict:
            sample[self.analysistype].verotoxindict[gene_type] = dict()
        if subtype not in sample[self.analysistype].verotoxindict[gene_type]:
            sample[self.analysistype].verotoxindict[gene_type].update({subtype: identity})
        if identity > sample[self.analysistype].verotoxindict[gene_type][subtype]:
            sample[self.analysistype].verotoxindict[gene_type][subtype] = identity

    def reporter(self):
        """
        Create a summary report of the verotoxin subtyping
        """
        logging.info('Creating verotoxin subtyping summary report')
        # Initialise a string with the report headers
        data = 'Strain,ToxinProfile\n'
        # Set the name of the summary report
        report = os.path.join(self.reportpath, 'verotoxin_summary.csv')
        with open(report, 'w') as summary:
            for sample in self.runmetadata.samples:
                # Store the subtype string for each sample
                data += '{sn},{subtypes}\n'.format(sn=sample.name,
                                                   subtypes=sample[self.analysistype].verotoxin_subtypes_set)
            # Write the string to the report
            summary.write(data)


class Virulence(GeneSippr):

    def runner(self):
        """
        Run the necessary methods in the correct order
        """

        vir_report = os.path.join(self.reportpath, 'virulence.csv')
        if os.path.isfile(vir_report):
            self.report_parse(vir_report)
        else:
            logging.info('Starting {at} analysis pipeline'.format(at=self.analysistype))
            if not self.pipeline:
                general = None
                for sample in self.runmetadata.samples:
                    general = getattr(sample, 'general')
                if general is None:
                    # Create the objects to be used in the analyses
                    objects = Objectprep(self)
                    objects.objectprep()
                    self.runmetadata = objects.samples
            Sippr(inputobject=self,
                  cutoff=self.cutoff,
                  k=19,
                  allow_soft_clips=True)
            # Create the reports
            self.reporter()
        # Print the metadata
        MetadataPrinter(self)

    def report_parse(self, vir_report):
        """
        Parse and existing report, and extract the results
        :param vir_report: type STR: Name and absolute path of the report
        """
        for sample in self.runmetadata.samples:
            setattr(sample, self.analysistype, GenObject())
            sample[self.analysistype].results = dict()
            sample[self.analysistype].avgdepth = dict()
            with open(vir_report, 'r') as report:
                next(report)
                for line in report:
                    try:
                        strain, gene, allele, description, accession, perc_ident, fold_cov = line.rstrip().split(',')
                        if sample.name in line:
                            if strain:
                                name = '{gene}_{accession}_{allele}'.format(gene=gene,
                                                                            accession=accession,
                                                                            allele=allele)
                                sample[self.analysistype].results[name] = perc_ident
                                sample[self.analysistype].avgdepth[name] = fold_cov
                    except ValueError:
                        pass

    def reporter(self):
        """
        Creates a report of the results
        """
        # Create a set of all the gene names without alleles or accessions e.g. sul1_18_AY260546 becomes sul1
        genedict = dict()
        # Load the notes file to a dictionary
        notefile = os.path.join(self.targetpath, 'notes.txt')
        with open(notefile, 'r') as notes:
            for line in notes:
                # Ignore comment lines - they will break the parsing
                if line.startswith('#'):
                    continue
                # Split the line on colons e.g. stx1Aa:  Shiga toxin 1, subunit A, variant a: has three variables after
                # the split: gene(stx1Aa), description(Shiga toxin 1, subunit A, variant a), and _(\n)
                try:
                    gene, description, _ = line.split(':')
                # There are exceptions to the parsing. Some lines only have one :, while others have three. Allow for
                # these possibilities.
                except ValueError:
                    try:
                        gene, description = line.split(':')
                    except ValueError:
                        gene, description, _, _ = line.split(':')
                # Set up the description dictionary
                genedict[gene] = description.replace(', ', '_').strip()
        # Find unique gene names with the highest percent identity
        for sample in self.runmetadata.samples:
            try:
                if sample[self.analysistype].results:
                    # Initialise a dictionary to store the unique genes, and their percent identities
                    sample[self.analysistype].uniquegenes = dict()
                    for name, identity in sample[self.analysistype].results.items():
                        # Split the name of the gene from the string e.g. stx1:11:Z36899:11 yields stx1
                        if ':' in name:
                            sample[self.analysistype].delimiter = ':'
                        else:
                            sample[self.analysistype].delimiter = '_'
                        genename = name.split(sample[self.analysistype].delimiter)[0]
                        # Set the best observed percent identity for each unique gene
                        try:
                            # Pull the previous best identity from the dictionary
                            bestidentity = sample[self.analysistype].uniquegenes[genename]
                            # If the current identity is better than the old identity, save it
                            if float(identity) > float(bestidentity):
                                sample[self.analysistype].uniquegenes[genename] = float(identity)
                        # Initialise the dictionary if necessary
                        except KeyError:
                            sample[self.analysistype].uniquegenes[genename] = float(identity)
            except AttributeError:
                raise
        # Create the path in which the reports are stored
        make_path(self.reportpath)
        # Initialise strings to store the results
        data = 'Strain,Gene,Subtype/Allele,Description,Accession,PercentIdentity,FoldCoverage\n'
        with open(os.path.join(self.reportpath, self.analysistype + '.csv'), 'w') as report:
            for sample in self.runmetadata.samples:
                try:
                    if sample[self.analysistype].results:
                        # If there are many results for a sample, don't write the sample name in each line of the report
                        for name, identity in sorted(sample[self.analysistype].results.items()):
                            # Check to see which delimiter is used to separate the gene name, allele, accession, and
                            # subtype information in the header
                            if len(name.split(sample[self.analysistype].delimiter)) == 4:
                                # Split the name on the delimiter: stx2A:63:AF500190:d; gene: stx2A, allele: 63,
                                # accession: AF500190, subtype: d
                                genename, allele, accession, subtype = name.split(sample[self.analysistype].delimiter)
                            elif len(name.split(sample[self.analysistype].delimiter)) == 3:
                                # Treat samples no subtype e.g. icaC:intercellular adhesion protein C: differently.
                                # Extract the allele as the 'subtype', and the gene name, and accession as above
                                genename, subtype, accession = name.split(sample[self.analysistype].delimiter)
                            else:
                                genename = name
                                subtype = ''
                                accession = ''
                            # Retrieve the best identity for each gene
                            percentid = sample[self.analysistype].uniquegenes[genename]
                            # If the percent identity of the current gene matches the best percent identity, add it to
                            # the report - there can be multiple occurrences of genes e.g.
                            # sul1,1,AY224185,100.00,840 and sul1,2,CP002151,100.00,927 are both included because they
                            # have the same 100% percent identity
                            if float(identity) == percentid:
                                # Treat the initial vs subsequent results for each sample slightly differently - instead
                                # of including the sample name, use an empty cell instead
                                try:
                                    description = genedict[genename]
                                except KeyError:
                                    description = 'ND'
                                # Populate the results
                                data += '{samplename},{gene},{subtype},{description},{accession},{identity},{depth}\n' \
                                    .format(samplename=sample.name,
                                            gene=genename,
                                            subtype=subtype,
                                            description=description,
                                            accession=accession,
                                            identity=identity,
                                            depth=sample[self.analysistype].avgdepth[name])
                    else:
                        data += sample.name + '\n'
                except (KeyError, AttributeError):
                    data += sample.name + '\n'
            # Write the strings to the file
            report.write(data)

    def __init__(self, args, pipelinecommit, startingtime, scriptpath, analysistype, cutoff, pipeline, revbait,
                 allow_soft_clips=False):
        self.runmetadata = args.runmetadata

        self.path = os.path.join(args.path)
        try:
            self.targetpath = os.path.join(args.targetpath, analysistype)
        except AttributeError:
            self.targetpath = os.path.join(args.reffilepath, analysistype)
        self.logfile = args.logfile
        self.cpus = args.cpus
        super().__init__(self, pipelinecommit, startingtime, scriptpath, analysistype, cutoff, pipeline,
                         revbait, allow_soft_clips)
        self.runner()
