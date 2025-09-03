import os

import numpy as np
import pandas as pd
from brpylib import NevFile

from pyNsXStitch.stitchers import StitchedNsXFile, StitchedNeVFile
from pyNsXStitch.helpers import get_all_nev_comments, get_all_streamed_files, get_nev_rec_start, \
    find_nsx_in_range, get_support_files
from pyNsXStitch.streamers import stream_nev_packets

BASE_SOURCE_DIR = r"Z:\trd\DBSTRD011\NEURAL"
BASE_OUTPUT_DIR = r"D:\Work\DataNet\TestData\temp\for Kat"

# Task list csv must have 3 columns: Date folder, EMU ID,  Task Name
TASK_LIST_CSV = r'D:\Work\BCM\pyNsXStitch\examples\TRD011_log_file_Doors.csv'

AGGRESIVE_STITCH = True

tasks = pd.read_csv(TASK_LIST_CSV)

def load_comments(task_folder):
    source_dir = os.path.join(BASE_SOURCE_DIR, task_folder)

    # With the new version of central, data from multiple NSPs can be in the same folder
    all_streamed_files = get_all_streamed_files(source_dir, full_paths=True)
    # Sort the NSPs for consistency
    all_nsps = sorted(all_streamed_files)

    if len(all_nsps) == 1:
        # Only 1 NSP here, so we can move forward
        nsp = all_nsps[0]
        streamed_files = all_streamed_files[nsp]
    else:
        raise ValueError(f'ERROR! Invalid NSP config: {task_folder}')

    first_nsp = list(streamed_files.keys())[0]
    print(f'Using comments from {first_nsp}')
    print(f'Found {len(streamed_files["NeV"])} NeV files')

    # Iter through all the comment packets in all files
    print(f'Loading comments from NeV...')
    timestamps, comments, file_names = [], [], []
    n_files = len(streamed_files["NeV"])
    for i, file in enumerate(streamed_files["NeV"]):
        nev = NevFile(file)
        for (ts, packet_id), raw_data in stream_nev_packets(nev, packet_type=65535):
            timestamps.append(ts)
            text_data = raw_data[6:]
            comment = text_data.decode('ASCII').rstrip('\x00')  # TODO: handle other charsets
            comments.append(comment)

    print(f'Found {len(timestamps)} comments...')

    # Convert to a dataframe for drawing to the GUI
    timestamps = np.array(timestamps)
    cleaned_df = pd.DataFrame.from_dict({
        'Timestamp': timestamps,
        'Comment': comments
    })
    return streamed_files, cleaned_df


def do_stitch(streamed_files, task_name, start, end):

    output_dir = os.path.join(BASE_OUTPUT_DIR, task_name)
    os.makedirs(output_dir, exist_ok=True)

    # Stitch the NeV files first
    print('Stitching NeV files...')
    nev_stitch = StitchedNeVFile(streamed_files['NeV'], start, end)
    with open(os.path.join(output_dir, f'{task_name}.nev'), 'wb') as nev_out:
        nev_stitch.write(nev_out)
    print('Stitched NeV file complete')

    # Stitch each of the NsX filetypes
    print('Beginning NsX stitching...')
    nsx_files = {filetype: files for filetype, files in streamed_files.items() if 'ns' in filetype.lower()}
    for filetype, files in nsx_files.items():
        print(f'Stitching from {len(files)} {filetype} files')
        in_range = find_nsx_in_range(files, start, end)
        print(f'Found {len(in_range)} files in the selected time range')
        if in_range:
            nsx_stitch = StitchedNsXFile(in_range, start, end, aggressive_concat=AGGRESIVE_STITCH)
            with open(os.path.join(output_dir, f'{task_name}.{filetype.lower()}'), 'wb+') as nsx_out:
                nsx_stitch.write(nsx_out)
        else:
            raise IndexError('Could not find enough files to stitch!')

    print(f'Finished {task_name}')


for i, task_data in tasks.iterrows():

    streamed_file_list, all_comments = load_comments(task_data.iloc[0])

    matched_comments = all_comments[all_comments['Comment'].str.contains(f'EMU-0{task_data.iloc[1]}')]
    start_timestamp = matched_comments['Timestamp'].min()
    end_timestamp = matched_comments['Timestamp'].max()

    do_stitch(streamed_file_list, task_data.iloc[2], start_timestamp, end_timestamp)





