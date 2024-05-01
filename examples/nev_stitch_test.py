import sys
import os
import numpy as np
import pandas as pd

# Get the absolute path of `pyNsXStitch` module
abs_module_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(abs_module_path)

from pyNsXStitch.stitchers import StitchedNeVFile, NevFile
from pyNsXStitch.helpers import get_nev_rec_start

source_dir = r'../../nev-only-dual-nsp/'
out_path = r'../../test/test.nev'

files = os.listdir(source_dir)
nev_filenames = [os.path.join(source_dir, f) for f in files if '.nev' in f]

stitch = StitchedNeVFile(nev_filenames)
with open(out_path, 'wb') as out_file:
    stitch.write(out_file)

test_out = NevFile(out_path)
rec_start = get_nev_rec_start(NevFile(nev_filenames[0]))
packets = test_out.getdata()
comment_table = pd.DataFrame.from_dict(packets['comments'])
time_elapsed = (comment_table['TimeStamps'] - rec_start) / test_out.basic_header['TimeStampResolution']
comment_table['TimeElapsed'] = np.round(time_elapsed, 4)
print(test_out)