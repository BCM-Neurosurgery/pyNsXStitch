"""
Based on
"""

import os
import re
import warnings

from brpylib.brpylib import *
from struct import unpack

import pandas as pd

from pyNsXStitch.streamers import stream_nev_packets, iter_nsx_timestamps

nsx_copy_headers = []
REC_EVENT_PACKET_ID = 65529


def get_all_streamed_files(directory, full_paths=False):
    """
    Find all the streamed Blackrock TOC mode files in a directory.

    This includes all NsX and NeV files. No other metadata files are included.

    :param directory:
    :param full_paths:
    :return: dictionary of file names keyed by blackrock file type
    """
    all_files = os.listdir(directory)
    streamed_files = {}

    for file_name in all_files:
        if file_name.endswith(".nev") or re.search(r'\.ns[0-9]$', file_name):
            nsp_id, timestamp = file_name.split('-', 1)
            # Need to use full timestamp string for sorting, like "20240314-143445-001"
            timestamp = timestamp.split('.')[0]
            file_path = os.path.join(directory, file_name) if full_paths else file_name

            if nsp_id not in streamed_files:
                streamed_files[nsp_id] = {"NeV": []}

            if file_name.endswith(".nev"):
                streamed_files[nsp_id]['NeV'].append((timestamp, file_path))
            else:
                nsx_match = re.search(r'\.ns([0-9])$', file_name)
                if nsx_match:
                    nsx_num = int(nsx_match.group(1))
                    file_type = f'Ns{nsx_num}'
                    streamed_files[nsp_id].setdefault(file_type, []).append((timestamp, file_path))

    # Sort files based on full timestamp string
    for nsp_id in streamed_files:
        for file_type in streamed_files[nsp_id]:
            streamed_files[nsp_id][file_type].sort(key=lambda x: x[0])
            streamed_files[nsp_id][file_type] = [file_path for _, file_path in streamed_files[nsp_id][file_type]]

    # Keep only files with NeV file present
    streamed_files = {nsp_id: files for nsp_id, files in streamed_files.items() if files['NeV']}

    return streamed_files


def get_support_files(directory, full_paths=False):
    """Get a list of all the support files in a directory"""
    support_file_types = ['csr', 'ccf', 'sif', 'toc']
    all_files = os.listdir(directory)
    support_files = []
    for file_path in all_files:
        if file_path.split('.')[-1] in support_file_types:
            support_files.append(file_path)
    if full_paths:
        support_files = [os.path.join(directory, f) for f in support_files]
    return support_files


def get_nsx_duration(nsx_filepath):
    """Get the duration of this data file in the file's native timestamp units"""
    return get_nsx_end_timestamp(nsx_filepath) - get_nsx_start_timestamp(nsx_filepath)


def get_nsx_end_timestamp(nsx_filepath):
    """Return the end of the NsX file in time elapsed (seconds) since the recording start"""
    nsx_file = NsxFile(nsx_filepath, verbose=False, interactive=False)
    last_ts, packet_size = None, None
    for timestamp, packet_points in iter_nsx_timestamps(nsx_file):
        last_ts = timestamp
        packet_size = packet_points

    sample_freq = int(nsx_file.basic_header['SampleResolution'] / nsx_file.basic_header['Period'])
    ts_freq = nsx_file.basic_header['TimeStampResolution']
    end_ts = last_ts + int(packet_size * ts_freq / sample_freq)

    del nsx_file
    return end_ts


def get_nsx_start_timestamp(nsx_filepath):
    """Get the start time (in seconds) of this data file from the header of the first data packet"""
    try:
        nsx = NsxFile(nsx_filepath, verbose=False, interactive=False)
        end_of_header = nsx.basic_header["BytesInHeader"]
        nsx.datafile.seek(end_of_header + 1, 0)  # Move to the start of data, also skipping the null byte
        timestamp = unpack("<Q", nsx.datafile.read(8))[0]
        return timestamp
    except Exception as e:
        raise e
    finally:
        del nsx


def find_nsx_in_range(nsx_filepaths, start_ts, end_ts, subtract_offset=False):
    """Find all nsx files that contain data in the given range (time elapsed in seconds)"""
    files = []
    # Sort files by starting timestamps in ascending order
    sorted_filepaths = sorted(nsx_filepaths, key=get_nsx_start_timestamp)
    
    # Files are now sorted by file_start
    for nsx_fp in sorted_filepaths:
        file_start = get_nsx_start_timestamp(nsx_fp)

        #                  |                                 |
        #                  start_ts                          end_ts 
        #  |                   | 
        #  file_start          file_end
        
        # If current file starts AFTER desired end timestamp, we can stop looking,
        # remaining files will also be outside of desired range
        if file_start > end_ts:
            break
        
        file_end = get_nsx_end_timestamp(nsx_fp)
        
        # If current file ends after or at the desired start timestamp,
        # it means this file contains data within our desired range
        if file_end >= start_ts:
            files.append(nsx_fp)
    
    return files


def get_time_in_file(nsx_file, timestamp):
    """Get the location of the given timestamp in the given NsX file as a file pointer"""
    for start_ts, packet_len in iter_nsx_timestamps(nsx_file):
        if start_ts <= timestamp < start_ts + packet_len:
            # The time is in this packet, find it's exact location in the packet
            packet_start = nsx_file.datafile.tell()
            pos_in_packet = timestamp - start_ts
            time_in_file = packet_start + pos_in_packet
            break
    else:
        time_in_file = None  # The given time is not in this file

    return time_in_file


def get_all_nev_comments(nev_filenames, gui_updater=None):
    """Get a data frame of all the comments in the listed NeV files"""
    nev_files = [NevFile(fp, verbose=False, interactive=False) for fp in nev_filenames]

    # Read in all the comments from all the files
    all_easy_read = []
    for i, nev_file in enumerate(nev_files):
        if gui_updater is not None:
            gui_updater(100 * i/len(nev_files))
        try:
            nev_data = nev_file.getdata()
        except (ValueError, IndexError):
            warnings.warn(f'Could not read NeV file! Is it empty? \n  {nev_filenames[i]}')
            continue
        try:
            easy_read = pd.DataFrame.from_dict(nev_data['comments'])
        except KeyError:
            warnings.warn(f'Found no comments in NeV file! \n  {nev_filenames[i]}')
            continue
        all_easy_read.append(easy_read)
    if all_easy_read:
        easy_read = pd.concat(all_easy_read)
    else:
        easy_read = pd.DataFrame.from_dict({'CharSet': [], 'Flag': [], 'Data': [], 'Comment': []})
    return easy_read


def search_nev_comments(nev_filenames, task_name):
    """Helper function to search for the start and end of a task in a NeV file"""
    easy_read = get_all_nev_comments(nev_filenames)

    # Select our the timestamps of the relevant start and end comment
    match = easy_read[[task_name in desc for desc in easy_read['Data']]]
    # TODO: Make a smarter selection method, this is temp for testing
    start, end = match['TimeStamps'].iloc[1], match['TimeStamps'].iloc[2]

    return start, end


def get_nev_rec_start(nev_file):
    for meta, packet in stream_nev_packets(nev_file):
        packet_id = meta[1]
        if packet_id == REC_EVENT_PACKET_ID:  # Only try parsing recording event type packets
            event_type = unpack("<H", packet[:2])[0]
            if event_type == 0:  # This is a recording start event
                recording_start = meta[0]
                break  # We got our start time, no need to keep looking
        else:
            continue  # Keep looking for the recording event packer
    else:
        recording_start = 0  # We didn't find any recording start packets

    return recording_start


def read_at(filepath, read_loc, n_bytes=10):
    """
    Naively read a few bytes from a file at the given location.

    This function is mainly here for debugging and spot/sanity checking purposes. Not an efficient way to read data
    """
    read = None
    with open(filepath, 'rb') as f:
        f.seek(read_loc, 0)
        read = f.read(n_bytes)
    return read


