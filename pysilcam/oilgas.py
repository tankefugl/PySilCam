# -*- coding: utf-8 -*-
'''
module for processing Oil and Gas SilCam data
'''
import pysilcam.postprocess as sc_pp
from pysilcam.config import PySilcamSettings
from pysilcam.datalogger import DataLogger
import itertools
import pandas as pd
import numpy as np
import os
import http.server
import socketserver
from multiprocessing import Process, Queue
import time
import struct
import serial
import serial.tools.list_ports
import glob
import sys
from tqdm import tqdm
import logging

solidityThresh = 0.95
logger = logging.getLogger(__name__)


def getListPortCom():
    try:
        if sys.platform.startswith('win'):
            com_list = [comport.device for comport in serial.tools.list_ports.comports()]
        elif sys.platform.startswith('linux'):
            com_list = glob.glob('/dev/tty[A-Za-z]*')
    except AttributeError:
        com_list = []

    return com_list


def extract_gas(stats, THRESH=0.85):
    ma = stats['minor_axis_length'] / stats['major_axis_length']
    stats = stats[ma>0.3]
    stats = stats[stats['solidity']>solidityThresh]
    ind = np.logical_or((stats['probability_bubble']>stats['probability_oil']),
            (stats['probability_oily_gas']>stats['probability_oil']))

    # ind2 = np.logical_or((stats['probability_bubble'] > THRESH),
            # (stats['probability_oily_gas'] > THRESH))

    ind2 = stats['probability_bubble'] > THRESH

    ind = np.logical_and(ind, ind2)

    stats = stats[ind]
    return stats


def extract_oil(stats, THRESH=0.85):
    ma = stats['minor_axis_length'] / stats['major_axis_length']
    stats = stats[ma>0.3]
    stats = stats[stats['solidity']>solidityThresh]
    ind = np.logical_or((stats['probability_oil']>stats['probability_bubble']),
            (stats['probability_oil']>stats['probability_oily_gas']))

    ind2 = (stats['probability_oil'] > THRESH)

    ind = np.logical_and(ind, ind2)

    stats = stats[ind]
    return stats


def gor_timeseries(stats, settings):
    from tqdm import tqdm

    u = stats['timestamp'].unique()
    td = pd.to_timedelta('00:00:' + str(settings.window_size / 2.))

    sample_volume = sc_pp.get_sample_volume(settings.pix_size, path_length=settings.path_length)

    gor = []
    time = []

    for t in tqdm(u):
        dt = pd.to_datetime(t)
        stats_ = stats[(pd.to_datetime(stats['timestamp']) < (dt + td)) & (pd.to_datetime(stats['timestamp']) > (dt - td))]

        oilstats = extract_oil(stats_)
        dias, vd_oil = sc_pp.vd_from_stats(oilstats, settings)
        nims = sc_pp.count_images_in_stats(oilstats)
        sv = sample_volume * nims
        vd_oil /= sv

        gasstats = extract_gas(stats_)
        dias, vd_gas = sc_pp.vd_from_stats(gasstats, settings)
        nims = sc_pp.count_images_in_stats(gasstats)
        sv = sample_volume * nims
        vd_gas /= sv

        gor_ = sum(vd_gas)/sum(vd_oil)

        time.append(pd.to_datetime(t))
        gor.append(gor_)

    if (len(gor) == 0) or (np.isnan(max(gor))):
        gor = np.nan
        time = np.nan

    return gor, time


class rt_stats():
    '''
    Class for maintining realtime statistics
    '''
    def __init__(self, settings):
        self.stats = pd.DataFrame
        self.settings = settings
        self.dias = []
        self.vd_oil = []
        self.vd_gas = []
        self.oil_d50 = np.nan
        self.gas_d50 = np.nan
        self.saturation = np.nan

    def update(self):
        '''
        Updates the rt_stats to remove data from before the specified window of seconds
        given in the config ini file, here: settings.PostProcess.window_size
        '''
        self.stats = sc_pp.extract_latest_stats(self.stats,
                self.settings.PostProcess.window_size)

        #extract seperate stats on oil and gas
        self.oil_stats = extract_oil(self.stats)
        self.gas_stats = extract_gas(self.stats)

        #calculate d50
        self.oil_d50 = sc_pp.d50_from_stats(self.oil_stats,
            self.settings.PostProcess)
        self.gas_d50 = sc_pp.d50_from_stats(self.gas_stats,
                self.settings.PostProcess)

        self.dias, self.vd_oil = sc_pp.vd_from_stats(self.oil_stats,
                    self.settings.PostProcess)
        self.dias, self.vd_gas = sc_pp.vd_from_stats(self.gas_stats,
                    self.settings.PostProcess)

        self.saturation = np.max(self.stats.saturation)


    def to_csv(self, filename):
        '''
        Writes the rt_stats data to a csv file
        
        Args:
            filename (str) : filename of the csv file to write to
        '''
        df = pd.DataFrame()
        df['Oil d50[um]'] = [self.oil_d50]
        df['Gas d50[um]'] = [self.gas_d50]
        # @todo include saturation here too
        df['saturation [%]'] = [self.saturation]
        df.to_csv(filename, index=False, mode='w') # do not append to this file


class ServerThread(Process):
    '''
    Class for managing http server for sharing realtime data
    '''
    def __init__(self, ip):
        '''
        Setup the server
        
        Args:
            ip (str) : string defining the local ip address of the machine that will run this function
        '''
        super(ServerThread, self).__init__()
        self.ip = ip
        self.go()

    def run(self):
        '''
        Start the server on port 8000
        '''
        PORT = 8000
        #address = '192.168.1.2'
        Handler = http.server.SimpleHTTPRequestHandler
        with socketserver.TCPServer((self.ip, PORT), Handler) as httpd:
            logger.info("serving at port: {0}".format(PORT))
            httpd.serve_forever()

    def go(self):
        self.start()


def ogdataheader():
    '''
    Possibly a redundant function....
    '''
    ogheader = 'Y, M, D, h, m, s, '

    bin_mids_um, bin_limits_um = sc_pp.get_size_bins()

    for i in bin_mids_um:
        ogheader += str(i) + ', '
        #print(str(i) + ', ')

    ogheader += 'd50, ProcessedParticles'

    return ogheader


def cat_data(timestamp, stats, settings):
    '''
    Possibly a redundant function....
    '''
    dias, vd = sc_pp.vd_from_stats(stats, settings.PostProcess)
    d50 = sc_pp.d50_from_vd(vd, dias)

    data = [[timestamp.year, timestamp.month, timestamp.day,
            timestamp.hour, timestamp.minute, timestamp.second + timestamp.microsecond /
            1e6],
            vd, [d50, len(stats)]]
    data = list(itertools.chain.from_iterable(data))

    return data


class PathLength():
    '''
    Class for interacting with the path length actuator unit via RS232
    
    See the technical manual for the actuator for details
    '''
    def __init__(self, com_port):
        self.ser = serial.Serial(com_port, 115200, timeout=1)
        print('actuator port open!')
        self.motoronoff(self.ser,1)


    def compute_crc8(self, packet, crc=0):
        table =  [0x00,0x07,0x0E,0x09,0x1C,0x1B,0x12,0x15,0x38,0x3F,0x36,0x31,0x24,0x23,0x2A,0x2D,0x70,0x77,0x7E,0x79,0x6C,0x6B,0x62,0x65,0x48,0x4F,0x46,0x41,0x54,0x53,0x5A,0x5D,0xE0,0xE7,0xEE,0xE9,0xFC,0xFB,0xF2,0xF5,0xD8,0xDF,0xD6,0xD1,0xC4,0xC3,0xCA,0xCD,0x90,0x97,0x9E,0x99,0x8C,0x8B,0x82,0x85,0xA8,0xAF,0xA6,0xA1,0xB4,0xB3,0xBA,0xBD,0xC7,0xC0,0xC9,0xCE,0xDB,0xDC,0xD5,0xD2,0xFF,0xF8,0xF1,0xF6,0xE3,0xE4,0xED,0xEA,0xB7,0xB0,0xB9,0xBE,0xAB,0xAC,0xA5,0xA2,0x8F,0x88,0x81,0x86,0x93,0x94,0x9D,0x9A,0x27,0x20,0x29,0x2E,0x3B,0x3C,0x35,0x32,0x1F,0x18,0x11,0x16,0x03,0x04,0x0D,0x0A,0x57,0x50,0x59,0x5E,0x4B,0x4C,0x45,0x42,0x6F,0x68,0x61,0x66,0x73,0x74,0x7D,0x7A,0x89,0x8E,0x87,0x80,0x95,0x92,0x9B,0x9C,0xB1,0xB6,0xBF,0xB8,0xAD,0xAA,0xA3,0xA4,0xF9,0xFE,0xF7,0xF0,0xE5,0xE2,0xEB,0xEC,0xC1,0xC6,0xCF,0xC8,0xDD,0xDA,0xD3,0xD4,0x69,0x6E,0x67,0x60,0x75,0x72,0x7B,0x7C,0x51,0x56,0x5F,0x58,0x4D,0x4A,0x43,0x44,0x19,0x1E,0x17,0x10,0x05,0x02,0x0B,0x0C,0x21,0x26,0x2F,0x28,0x3D,0x3A,0x33,0x34,0x4E,0x49,0x40,0x47,0x52,0x55,0x5C,0x5B,0x76,0x71,0x78,0x7F,0x6A,0x6D,0x64,0x63,0x3E,0x39,0x30,0x37,0x22,0x25,0x2C,0x2B,0x06,0x01,0x08,0x0F,0x1A,0x1D,0x14,0x13,0xAE,0xA9,0xA0,0xA7,0xB2,0xB5,0xBC,0xBB,0x96,0x91,0x98,0x9F,0x8A,0x8D,0x84,0x83,0xDE,0xD9,0xD0,0xD7,0xC2,0xC5,0xCC,0xCB,0xE6,0xE1, 0xE8,0xEF,0xFA,0xFD,0xF4,0xF3]
        for byte in packet:
            temp = struct.unpack('B',byte)
            crc = table[crc^temp[0]]
        return crc

    def makepacket(self, command,size,setpoint):
        packitem1 = '<'.encode('utf-8')[0]
        packitem2 = size
        packitem3 = command.encode('utf-8')[0]
        packets = [packitem2,packitem3]
        if size>1:
            packitem4 = setpoint.to_bytes(size-1, byteorder = 'big')
            for items in packitem4:
                packets.append(items)
        bytepacket = []
        for bytestr in packets:
            bytepacket.append((struct.pack('B',bytestr)))
        packitem5 = self.compute_crc8(bytepacket,crc=0)
        packitem6 = '>'.encode('utf-8')[0]
        packets.append(packitem5)
        packets.append(packitem6)
        packets.insert(0,packitem1)
        sendstring = bytearray(bytearray(packets)).decode('latin-1')
        return sendstring

    def motoronoff(self, ser,state):
        sendstring = self.makepacket('X',2,state)
        self.ser.write(bytes(sendstring,'latin-1'))
        time.sleep(0.1)
        readout1 = self.ser.read(1000)
        sendstring = self.makepacket('p',1,0)
        self.ser.write(bytes(sendstring,'latin-1'))
        time.sleep(0.1)
        readout2 = self.ser.read(1000)
        motorvalue = bin(readout2[3])[2]
        logger.info('readout3: %s', motorvalue)
        if int(motorvalue) == 0 :
            logger.info('motor is OFF')
        elif int(motorvalue) == 1 :
            logger.info('motor is ON')
        else :
            logger.info('Something fishy is going on')

    def move(self, ser,newpos):
        newpos = self.convert_pos(int(newpos))
        sendstring = self.makepacket('S',5,newpos)
        self.ser.write(bytes(sendstring,'latin-1'))
        time.sleep(0.1)
        readout1 = self.ser.read(1000)
        readpos = self.readpos()
        logger.info('Setpoint: %d', newpos)
        logger.info('Actual pos: %d', readpos)

    def readpos(self):
        sendstring = self.makepacket('p',1,0)
        self.ser.write(bytes(sendstring,'latin-1'))
        time.sleep(0.1)
        readout2 = self.ser.read(1000)
        readpos = int.from_bytes(bytearray(readout2[5:9]),byteorder='big')
        return readpos


    def convert_pos(self, pos):
        '''takes mm and converts to integer thousandths of an inch
        '''
        converted_pos = pos * 0.0384 # inches
        converted_pos *= 1000 # thousandths of inches
        converted_pos = int(converted_pos)
        return converted_pos

    def mingap(self):
        self.move(self.ser, 108.5)

    def maxgap(self):
        self.move(self.ser, 4)

    def gap_to_mm(self, mm):
        val = 108.5-mm
        self.move(self.ser, val)

    def finish(self):
        self.motoronoff(self.ser,0)
        self.ser.close()
        logger.info('actuator port closed!')


def cat_data_pj(timestamp, vd, d50, nparts):
    '''
    cat data into PJ-readable format (readable by the old matlab SummaryPlot exe)
    '''
    timestamp = pd.to_datetime(timestamp)

    data = [[timestamp.year, timestamp.month, timestamp.day,
            timestamp.hour, timestamp.minute, timestamp.second + timestamp.microsecond /
            1e6],
            vd, [d50, nparts]]
    data = list(itertools.chain.from_iterable(data))

    return data


def convert_to_pj_format(stats_csv_file, config_file):
    '''converts stats files into a total, and gas-only time-series csvfile which can be read by the old matlab
    SummaryPlot exe'''

    settings = PySilcamSettings(config_file)
    logger.info('Loading stats....')
    stats = pd.read_csv(stats_csv_file)

    base_name = stats_csv_file.replace('-STATS.csv', '-PJ.csv')
    gas_name = base_name.replace('-PJ.csv', '-PJ-GAS.csv')

    ogdatafile = DataLogger(base_name, ogdataheader())
    ogdatafile_gas = DataLogger(gas_name, ogdataheader())

    stats['timestamp'] = pd.to_datetime(stats['timestamp'])
    u = stats['timestamp'].unique()
    sample_volume = sc_pp.get_sample_volume(settings.PostProcess.pix_size, path_length=settings.PostProcess.path_length)

    logger.info('Analysing time-series')
    for s in tqdm(u):
        substats = stats[stats['timestamp'] == s]
        nims = sc_pp.count_images_in_stats(substats)
        sv = sample_volume * nims

        oil = extract_oil(substats)
        dias, vd_oil = sc_pp.vd_from_stats(oil, settings.PostProcess)
        vd_oil /= sv

        gas = extract_gas(substats)
        dias, vd_gas = sc_pp.vd_from_stats(gas, settings.PostProcess)
        vd_gas /= sv
        d50_gas = sc_pp.d50_from_vd(vd_gas, dias)

        vd_total = vd_oil + vd_gas
        d50_total = sc_pp.d50_from_vd(vd_total, dias)

        data_total = cat_data_pj(s, vd_total, d50_total, len(oil) + len(gas))
        ogdatafile.append_data(data_total)

        data_gas = cat_data_pj(s, vd_gas, d50_gas, len(gas))
        ogdatafile_gas.append_data(data_gas)

    logger.info('  OK.')

    logger.info('Deleting header!')
    with open(base_name, 'r') as fin:
        data = fin.read().splitlines(True)
    with open(base_name, 'w') as fout:
        fout.writelines(data[1:])
    with open(gas_name, 'r') as fin:
        data = fin.read().splitlines(True)
    with open(gas_name, 'w') as fout:
        fout.writelines(data[1:])
    logger.info('Conversion complete.')