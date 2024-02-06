import os
import numpy as np
from datetime import datetime
from brpylib.brpylib import NsxFile, NevFile
from stiching import StitchedNsXFile

file_path = r'D:\Work\DataNet\TestData\sources\blackrock\20240125-144340'

files = os.listdir(file_path)
ns5_filenames = [os.path.join(file_path, f) for f in files if '.ns5' in f]
nev_filenames = [os.path.join(file_path, f) for f in files if '.nev' in f]

nev_files = [NevFile(fp) for fp in nev_filenames]

combo = StitchedNsXFile(ns5_filenames)
with open(r'D:\Work\DataNet\TestData\sources\blackrock\test.ns5', 'wb') as f:
    combo.write_data(f)

pass


