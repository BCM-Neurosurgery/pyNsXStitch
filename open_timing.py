import datetime
import os
import numpy as np
from datetime import datetime

from brpylib.brpylib import NevFile, NsxFile

file_path = r'D:\Work\DataNet\TestData\sources\blackrock\20231129-161156'

files = os.listdir(file_path)
nev_filenames = [f for f in files if '.nev' in f]
ns3_filenames = [f for f in files if '.ns3' in f]
ns5_filenames = [f for f in files if '.ns5' in f]


# Time the opening of each of the files
nev_time, ns3_time, ns5_time = [], [], []
for i in range(len(nev_filenames)):
    nev_start = datetime.now()
    nev = NevFile(os.path.join(file_path, nev_filenames[i]))
    nev_end = datetime.now()
    nev_time.append(nev_end - nev_start)

    ns3_start = datetime.now()
    ns3 = NsxFile(os.path.join(file_path, ns3_filenames[i]))
    ns3_end = datetime.now()
    ns3_time.append(ns3_end - ns3_start)

    ns5_start = datetime.now()
    ns5 = NsxFile(os.path.join(file_path, ns5_filenames[i]))
    ns5_end = datetime.now()
    ns5_time.append(ns5_end - ns5_start)


print(f'NEV avg opening time: {np.mean(nev_time)}')
print(f'Ns3 avg opening time: {np.mean(ns3_time)}')
print(f'Ns5 avg opening time: {np.mean(ns5_time)}')
pass


