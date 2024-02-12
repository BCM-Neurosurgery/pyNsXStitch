import os
from brpylib.brpylib import NevFile
from pyNsXStitch.helpers import search_nev_comments, find_files_in_range
from pyNsXStitch.stiching import StitchedNsXFile

file_path = r'D:\Work\DataNet\TestData\sources\blackrock\20240125-144340'

files = os.listdir(file_path)
nev_filenames = [os.path.join(file_path, f) for f in files if '.nev' in f]

nev_files = [NevFile(fp) for fp in nev_filenames]
start, stop = search_nev_comments(nev_filenames, 'EBBQ')
print(start, stop)

nsx_files = [os.path.join(file_path, f) for f in files if '.ns5' in f]
relevant_nsx = find_files_in_range(nsx_files, start, stop)
stitch = StitchedNsXFile(relevant_nsx, start, stop)

out_path = r'D:\Work\DataNet\TestData\sources\blackrock\20240125-144340_test.ns5'
with open(out_path, 'wb') as out_file:
    stitch.write_data(out_file)
