# -*- coding: utf-8 -*-
import os
from pysilcam.__main__ import silcam_process
import pysilcam.postprocess as scpp
import unittest
import pandas as pd
from pysilcam.config import PySilcamSettings
from pysilcam.config import load_config

if "UNITTEST_DATA_PATH" in os.environ:
    ROOTPATH = os.environ['UNITTEST_DATA_PATH'] # 'E:/test data/hello_silcam/unittest_bamboo'
else:
    ROOTPATH = 'E:/test data/hello_silcam/unittest_entries'

# Get user-defined tensorflow model path from environment variable
MODEL_PATH = os.environ.get('SILCAM_MODEL_PATH', None)

@unittest.skipIf(not os.path.isdir(
    os.path.join(ROOTPATH, 'STANDARDS/StandardsBig')),
    "test path not accessible")
@unittest.skipIf(not os.path.isdir(
    os.path.join(ROOTPATH, 'STANDARDS/StandardsSmall')),
    "test path not accessible")

def test_big_standards():
    '''Testing that the large standards are sized correctly'''

    path = os.path.dirname(__file__)
    conf_file = os.path.join(path, 'config_glass_standards.ini')
    conf = load_config(conf_file)

    data_file = os.path.join(ROOTPATH, 'STANDARDS/StandardsBig')
    conf.set('General', 'datafile', os.path.join(ROOTPATH, 'STANDARDS', 'proc'))
    conf.set('General', 'logfile', os.path.join(ROOTPATH, 'STANDARDS', 'log.log'))
    if MODEL_PATH is not None:
        conf.set('NNClassify', 'model_path', MODEL_PATH)
    conf_file_hand = open(conf_file,'w')
    conf.write(conf_file_hand)
    conf_file_hand.close()

    stats_file = os.path.join(ROOTPATH, 'STANDARDS/proc/StandardsBig-STATS.csv')

    # if csv file already exists, it has to be deleted
    if (os.path.isfile(stats_file)):
        os.remove(stats_file)

    # call process function
    silcam_process(conf_file, data_file, multiProcess=False, nbImages=10)

    # check that csv file has been created
    assert os.path.isfile(stats_file), 'stats_file not created'

    # check that csv file has been properly built
    csvfile = open(stats_file)
    lines = csvfile.readlines()
    numline = len(lines)
    assert numline > 1 , 'csv file empty'

    # check the columns
    assert lines[0] == 'particle index,major_axis_length,minor_axis_length,equivalent_diameter,solidity,minr,minc,maxr,maxc,'\
            'probability_oil,probability_other,probability_bubble,probability_faecal_pellets,probability_copepod,'\
            'probability_diatom_chain,probability_oily_gas,export name,timestamp,saturation\n', 'columns not properly built'

    settings = PySilcamSettings(conf_file)
    stats = pd.read_csv(stats_file)
    d50 = scpp.d50_from_stats(stats, settings.PostProcess)
    assert (d50 > 310 and d50 < 330), 'incorrect d50'


@unittest.skipIf(not os.path.isdir(
    os.path.join(ROOTPATH, 'STANDARDS/StandardsBig')),
    "test path not accessible")
@unittest.skipIf(not os.path.isdir(
    os.path.join(ROOTPATH, 'STANDARDS/StandardsSmall')),
    "test path not accessible")
def test_small_standards():
    '''Testing that the small standards are sized correctly'''
    path = os.path.dirname(__file__)
    conf_file = os.path.join(path, 'config_glass_standards.ini')
    conf = load_config(conf_file)

    data_file = os.path.join(ROOTPATH, 'STANDARDS/StandardsSmall')
    conf.set('General', 'datafile', os.path.join(ROOTPATH, 'STANDARDS', 'proc'))
    conf.set('General', 'logfile', os.path.join(ROOTPATH, 'STANDARDS', 'log.log'))
    conf_file_hand = open(conf_file,'w')
    conf.write(conf_file_hand)
    conf_file_hand.close()

    stats_file = os.path.join(ROOTPATH, 'STANDARDS/proc/StandardsSmall-STATS.csv')

    # if csv file already exists, it has to be deleted
    if (os.path.isfile(stats_file)):
        os.remove(stats_file)

    # call process function
    silcam_process(conf_file, data_file, multiProcess=False, nbImages=10)

    # check that csv file has been created
    assert os.path.isfile(stats_file), 'stats_file not created'

    # check that csv file has been properly built
    csvfile = open(stats_file)
    lines = csvfile.readlines()
    numline = len(lines)
    assert numline > 1 , 'csv file empty'

    # check the columns
    assert lines[0] == 'particle index,major_axis_length,minor_axis_length,equivalent_diameter,solidity,minr,minc,maxr,maxc,'\
            'probability_oil,probability_other,probability_bubble,probability_faecal_pellets,probability_copepod,'\
            'probability_diatom_chain,probability_oily_gas,export name,timestamp,saturation\n', 'columns not properly built'

    settings = PySilcamSettings(conf_file)
    stats = pd.read_csv(stats_file)
    d50 = scpp.d50_from_stats(stats, settings.PostProcess)
    assert (d50 > 70 and d50 < 90), 'incorrect d50'
