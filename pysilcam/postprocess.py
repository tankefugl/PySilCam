import pandas as pd
import numpy as np

# PIX_SIZE = 35.2 / 2448 * 1000 # pixel size in microns (Med. mag)

def stats_from_csv(filename):
    stats = pd.read_csv(filename,index_col=0)
    return stats

def filter_stats(stats, settings):
    iniparts = len(stats)
    mmr = stats['minor_axis_length'] / stats['major_axis_length']
    stats = stats[mmr > settings.min_deformation]

    stats = stats[stats['solidity'] > settings.min_solidity]

    endparts = len(stats)
    print(iniparts - endparts,' particles removed.')
    print(endparts,' particles measured.')
    return stats

def d50_from_stats(stats, settings):

    dias, vd = vd_from_stats(stats, settings)

    d50 = d50_from_vd(vd,dias)
    return d50

def d50_from_vd(vd,dias):
    csvd = np.cumsum(vd/np.sum(vd))
    d50 = np.interp(0.5,csvd,dias)
    return d50

def get_size_bins():
    bin_limits_um = np.zeros((53),dtype=np.float64)
    bin_limits_um[0] = 2.72 * 0.91

    for I in np.arange(1,53,1):
        bin_limits_um[I] = bin_limits_um[I-1] * 1.180

    bin_mids_um = np.zeros((52),dtype=np.float64)
    bin_mids_um[0] = 2.72

    for I in np.arange(1,52,1):
        bin_mids_um[I]=bin_mids_um[I-1]*1.180

    return bin_mids_um, bin_limits_um

def vc_from_nd(count,psize,sv=1):
    ''' calculate volume concentration from particle count
    
    sv = sample volume size (litres)
     
    e.g:
    sample_vol_size=25*1e-3*(1200*4.4e-6*1600*4.4e-6); %size of sample volume in m^3
    sv=sample_vol_size*1e3; %size of sample volume in litres
    '''

    psize = psize *1e-6  # convert to m

    pvol = 4/3 *np.pi * (psize/2)**3  # volume in m^3
    
    tpvol = pvol * count * 1e9  # volume in micro-litres

    vc = tpvol / sv  # micro-litres / litre
    
    return vc

def vd_from_stats(stats, settings):
    ecd = stats['equivalent_diameter'] * settings.pix_size

    dias, bin_limits_um = get_size_bins()

    necd, edges = np.histogram(ecd,bin_limits_um)

    vd = vc_from_nd(necd,dias)

    return dias, vd


class TimeIntegratedVolumeDist:
    def __init__(self, settings):
        self.settings = settings
        self.window_size = settings.window_size
        self.times = []
        self.vdlist = []

        self.vd_mean = None
        self.dias = None

    def update_from_stats(self, stats, timestamp):
        '''Update size distribution from stats'''
        dias, vd = vd_from_stats(stats, self.settings)
        self.dias = dias

        #Add the new data
        self.times.append(timestamp)
        self.vdlist.append(vd)

        #Remove data until we are within window size
        while (timestamp - self.times[0]).seconds > self.window_size:
            self.times.pop(0)
            self.vdlist.pop(0)

        #Calculate time-integrated volume distribution
        if len(self.vdlist)>1:
            self.vd_mean = np.mean(self.vdlist, axis=0)
        else:
            self.vd_mean = self.vdlist[0]
