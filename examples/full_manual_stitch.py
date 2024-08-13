import os
import re
from brpylib import NsxFile
from pyNsXStitch.stitchers import StitchedNsXFile, StitchedNeVFile
from pyNsXStitch.helpers import get_nsx_start_timestamp

#: Path to the folder that the TOC mode recording was recorded to
TOC_FOLDER = "/path/to/folder"

#: ID of the NSP to stitch for (1 or 2)
NSP = 1

#: ID of chunk at which to start stitching
START_CHUNK = 9
START_OFFSET = 1.5

#: ID of the nsp chunk to end stitching
END_CHUNK = 12
END_OFFSET = 153.0

#: Path to place the stitched outputs
OUT_PATH = "/path/to/output"

#: Base filename to use for the stitched output files
FILENAME = "stitched"

# Get lists of all the files for the appropriate chunks to stitch
files_here = os.listdir(TOC_FOLDER)
to_stitch = {}
for file_name in files_here:
    chunk_data = re.search(r'NSP([12])-[0-9-]*-([0-9]{3})\.([nsev0-9]){3}', file_name)
    nsp_id = chunk_data.group(1)
    chunk_id = chunk_data.group(2)
    file_type = chunk_data.group(3)

    if nsp_id == NSP and (START_CHUNK <= int(chunk_id) <= END_CHUNK):
        to_stitch.setdefault(file_type, []).append(os.path.join(file_name))

# Get the start of the first and last chunks as NSP timestamps
nsx_files = [to_stitch[file_type] for file_type in to_stitch.keys() if 's' in file_type][0]
first_chunk_start = get_nsx_start_timestamp(nsx_files[0])
last_chunk_start = get_nsx_start_timestamp(nsx_files[-1])

# Convert interval start/end offsets into NSP timestamps
interval_start = first_chunk_start + (30000 * START_OFFSET)
interval_end = last_chunk_start + (30000 * END_OFFSET)

# Stitch the desired interval for each file type
for filetype, files in to_stitch.items():
    if filetype == 'NeV':
        combo = StitchedNeVFile(files, start=interval_start, end=interval_end)
    else:
        combo = StitchedNsXFile(files, start=interval_start, end=interval_end)

    full_out_path = os.path.join(OUT_PATH, f'{FILENAME}.{filetype.lower()}')
    with open(full_out_path, 'wb') as f:
        combo.write(f)




