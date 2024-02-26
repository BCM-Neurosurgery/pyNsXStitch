"""
Based on
"""

import os
import re
import warnings

from brpylib.brpylib import *
from struct import unpack

import pandas as pd

from pyNsXStitch.streamers import stream_nev_packets

nsx_copy_headers = []
REC_EVENT_PACKET_ID = 65529


def get_all_streamed_files(directory, full_paths=False):
    """
    Find all the streamed blackrock toc mode files in a directory

    This includes all NsX and NeV files. No other metadata files are included.

    :param directory:
    :param full_paths:
    :return: dictionary of file names keyed by blackrock file type
    """
    files = {
        "NeV": [],
    }
    all_files = os.listdir(directory)
    for file_path in all_files:
        file_path = os.path.join(directory, file_path) if full_paths else file_path
        if file_path.endswith(".nev"):
            files['NeV'].append(file_path)
        nsx_match = re.search(r'\.ns([0-9])$', file_path)
        if nsx_match:
            nsx_num = int(nsx_match.group(1))
            file_type = f'Ns{nsx_num}'
            if file_type not in files:
                files[file_type] = []
            files[file_type].append(file_path)
    return files


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
    """Get the duration of this data file in seconds"""
    return get_nsx_end_time(nsx_filepath) - get_nsx_start_time(nsx_filepath)


def iter_nsx_timestamps(nsx_file):
    """Loop through and quickly read off all the packet headers in an NsX file"""
    data_point_size = nsx_file.basic_header['ChannelCount'] * DATA_BYTE_SIZE

    file_size = os.path.getsize(nsx_file.datafile.name)
    ts_pointer = nsx_file.basic_header['BytesInHeader'] + 1
    while ts_pointer < file_size:
        nsx_file.datafile.seek(ts_pointer, 0)
        timestamp = unpack('<Q', nsx_file.datafile.read(8))[0]
        packet_points = unpack('<I', nsx_file.datafile.read(4))[0]

        yield timestamp, packet_points

        ts_pointer = nsx_file.datafile.tell() + (packet_points * data_point_size) + 1


def get_nsx_end_time(nsx_filepath):
    """Return the end of the NsX file in time elapsed (seconds) since the recording start"""
    nsx_file = NsxFile(nsx_filepath)
    last_ts, packet_size = None, None
    for timestamp, packet_points in iter_nsx_timestamps(nsx_file):
        last_ts = timestamp
        packet_size = packet_points

    sample_freq = int(nsx_file.basic_header['SampleResolution'] / nsx_file.basic_header['Period'])
    ts_freq = nsx_file.basic_header['TimeStampResolution']
    end_ts = last_ts + int(packet_size * ts_freq / sample_freq)

    del nsx_file
    return end_ts / ts_freq


def get_nsx_start_time(nsx_filepath):
    """Get the start time (in seconds) of this data file from the header of the first data packet"""
    try:
        nsx = NsxFile(nsx_filepath)
        end_of_header = nsx.basic_header["BytesInHeader"]
        nsx.datafile.seek(end_of_header + 1, 0)  # Move to the start of data, also skipping the null byte
        timestamp = unpack("<Q", nsx.datafile.read(8))[0]
        return timestamp / nsx.basic_header['TimeStampResolution']
    except Exception as e:
        raise e
    finally:
        del nsx


def find_nsx_in_range(nsx_filepaths, start, end, subtract_offset=False):
    """Find all nsx files that contain data in the given range (time elapsed in seconds)"""
    in_range = False
    files = []
    for nsx_fp in nsx_filepaths:
        file_start = get_nsx_start_time(nsx_fp)
        file_end = get_nsx_end_time(nsx_fp)
        if file_start <= start < file_end:
            in_range = True
        elif end <= file_end:
            # We've found the end of the range, we can quit looping (but still include this file)
            files.append(nsx_fp)
            break

        if in_range:
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
    nev_files = [NevFile(fp) for fp in nev_filenames]

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
    easy_read = pd.concat(all_easy_read)
    return easy_read


def search_nev_comments(nev_filenames, task_name):
    """Helper function to search for the start and end of a task in a NeV file"""
    easy_read = get_all_nev_comments(nev_filenames)

    # Select our the timestamps of the relevant start and end comment
    match = easy_read[[task_name in desc for desc in easy_read['Data']]]
    # TODO: Make a smarter selection method, this is temp for testing
    start, end = match['TimeStamps'].iloc[1], match['TimeStamps'].iloc[2]

    # Convert the timestamps to seconds since the start of the recording
    nev_file = NevFile(nev_filenames[0])
    rec_origin = get_nev_rec_start(nev_file)
    ts_per_sec = nev_file.basic_header['TimeStampResolution']
    start_s, end_s = round(start/ts_per_sec, 6), round(end/ts_per_sec, 6)
    return start_s, end_s


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
        recording_start = None  # We didn't find any recording start packets

    return recording_start


