import os
import re
from pyNsXStitch.stitchers import StitchedNsXFile, StitchedNeVFile

#: Path to the folder that the TOC mode recording was recorded to
TOC_FOLDER = "/path/to/folder"

#: ID of the NSP to stitch for (1 or 2)
NSP = 1

#: ID of chunk at which to start stitching
START_CHUNK = 9

#: ID of the nsp chunk to end stitching
END_CHUNK = 12

#: Path to place the stitched outputs
OUT_PATH = "/path/to/output"

#: Base filename to use for the stitched output files
FILENAME = "stitched"

files_here = os.listdir(TOC_FOLDER)
to_stitch = {}
for file_name in files_here:
    chunk_data = re.search(r'NSP([12])-[0-9-]*-([0-9]{3})\.([nsev0-9]){3}', file_name)
    nsp_id = chunk_data.group(1)
    chunk_id = chunk_data.group(2)
    file_type = chunk_data.group(3)

    if nsp_id == NSP and (START_CHUNK <= int(chunk_id) <= END_CHUNK):
        to_stitch.setdefault(file_type, []).append(os.path.join(file_name))


for filetype, files in to_stitch.items():
    if filetype == 'NeV':
        combo = StitchedNeVFile(files)
    else:
        combo = StitchedNsXFile(files)

    full_out_path = os.path.join(OUT_PATH, f'{FILENAME}.{filetype.lower()}')
    with open(full_out_path, 'wb') as f:
        combo.write(f)




