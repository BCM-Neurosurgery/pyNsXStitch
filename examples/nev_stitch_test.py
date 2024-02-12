import os
import numpy as np
import pandas as pd
from pyNsXStitch.stiching import StitchedNeVFile, NevFile
from pyNsXStitch.helpers import get_nev_rec_start

source_dir = r'D:\Work\DataNet\TestData\sources\blackrock\20240125-144340'
out_path = r'D:\Work\DataNet\TestData\sources\blackrock\test.nev'

files = os.listdir(source_dir)
nev_filenames = [os.path.join(source_dir, f) for f in files if '.nev' in f]

stitch = StitchedNeVFile(nev_filenames)
with open(out_path, 'wb') as out_file:
    stitch.write_data(out_file)

test_out = NevFile(out_path)
rec_start = get_nev_rec_start(NevFile(nev_filenames[0]))
packets = test_out.getdata()
comment_table = pd.DataFrame.from_dict(packets['comments'])
time_elapsed = (comment_table['TimeStamps'] - rec_start) / test_out.basic_header['TimeStampResolution']
comment_table['TimeElapsed'] = np.round(time_elapsed, 4)
print(test_out)
