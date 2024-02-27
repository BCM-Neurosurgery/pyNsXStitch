"""
Simple script to stitch together all the files in a directory
"""
import os
import shutil
from pyNsXStitch.stitchers import StitchedNsXFile, StitchedNeVFile
from pyNsXStitch.helpers import get_all_streamed_files

# Replace this with the absolute path to the directory that contains your TOC-mode recorded files
FILE_SOURCE = r"\path\to\folder\with\toc\recording"

# Replace this with the absolute path to the directory that you want to output your stitched files to
OUT_PATH = r'\path\to\output\folder'

# This will be the name of all the stitched files
FILE_NAME = 'stitched'


os.makedirs(OUT_PATH, exist_ok=True)
copied_files = []

# For each type of streamed file (NeV and NsX) create the appropriate stitcher and write the stitched file
streamed_files = get_all_streamed_files(FILE_SOURCE, full_paths=True)
for filetype, files in streamed_files.items():
    if filetype == 'NeV':
        combo = StitchedNeVFile(files)
    else:
        combo = StitchedNsXFile(files)

    full_out_path = os.path.join(OUT_PATH, f'{FILE_NAME}.{filetype.lower()}')
    with open(full_out_path, 'wb') as f:
        combo.write(f)

    filenames = [os.path.basename(f) for f in files]
    copied_files.extend(filenames)

# Copy any other files that have not been copied yet. This will include all metadata, configuration, and helper files
all_files = os.listdir(FILE_SOURCE)
leftovers = [f for f in all_files if f not in copied_files]
for filename in leftovers:
    filetype = filename.split('.')[-1]
    shutil.copy(
        os.path.join(FILE_SOURCE, filename),
        os.path.join(OUT_PATH, f'{FILE_NAME}.{filetype}')
    )

