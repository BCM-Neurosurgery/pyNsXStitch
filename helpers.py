"""
Based on
"""

import os
from brpylib.brpylib import *
from math import ceil
from struct import unpack

import numpy as np
import pandas as pd


nsx_copy_headers = []
REC_EVENT_PACKET_ID = 65529


def get_nsx_duration(nsx_filepath):
    """Get the duration of this data file in seconds"""
    return get_nsx_end_time(nsx_filepath) - get_nsx_start_time(nsx_filepath)


def iter_nsx_timestamps(nsx_file):
    """Loop through and quickly read off all the packet headers in an NsX file"""
    data_point_size = nsx_file.basic_header["ChannelCount"] * DATA_BYTE_SIZE

    ts_pointer = nsx_file.basic_header['BytesInHeader'] + 1
    file_size = os.path.getsize(nsx_file.datafile.name)
    while ts_pointer < file_size:
        nsx_file.datafile.seek(ts_pointer, 1)
        timestamp = unpack("<Q", nsx_file.datafile.read(8))[0]
        packet_points = unpack("<I", nsx_file.datafile.read(4))[0]

        yield timestamp, packet_points

        ts_pointer = nsx_file.datafile.tell() + packet_points * data_point_size + 1


def get_nsx_end_time(nsx_filepath):
    """Return the end of the NsX file in time elapsed (seconds) since the recording start"""
    nsx_file = NsxFile(nsx_filepath)
    last_ts, packet_size = None, None
    for timestamp, packet_points in iter_nsx_timestamps(nsx_filepath):
        last_ts = timestamp
        packet_size = packet_points

    end_ts = last_ts + packet_size
    sample_freq = nsx_file.basic_header['SampleResolution']

    del nsx_file
    return end_ts / sample_freq


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


def find_files_in_range(nsx_filepaths, start, end):
    """Find all nsx files that contain data in the given range (time elapsed in seconds)"""
    file_start = get_nsx_start_time(nsx_filepaths[0])
    in_range = False
    files = []
    for nsx_fp in nsx_filepaths:
        nsx = NsxFile(nsx_fp)
        duration = get_nsx_duration(nsx)
        if file_start <= start < file_start + duration:
            in_range = True
        elif file_start < end <= file_start + duration:
            # We've found the end of the range, we can quit looping (but still include this file)
            files.append(nsx_fp)
            break

        if in_range:
            files.append(nsx_fp)

        # Prepare to look at the next file
        file_start += duration
        del nsx

    return files


def get_time_in_file(nsx_file, time):
    """Get the location of the given timestamp in the given NsX file as a file pointer"""
    return 0    # TODO: actually implement this


def search_nev_comments(nev_filenames, task_name):
    """Helper function to search for the start and end of a task in a NeV file"""
    nev_files = [NevFile(fp) for fp in nev_filenames]

    # Read in all the comments from all the files
    all_easy_read = []
    for nev_file in nev_files:
        nev_data = nev_file.getdata()
        easy_read = pd.DataFrame.from_dict(nev_data['comments'])
        all_easy_read.append(easy_read)
    easy_read = pd.concat(all_easy_read)

    # Select our the timestamps of the relevant start and end comment
    match = easy_read[[task_name in desc for desc in easy_read['Data']]]
    # TODO: Make a smarter selection method, this is temp for testing
    start, end = match['TimeStamps'].iloc[1], match['TimeStamps'].iloc[2]

    # Convert the timestamps to seconds since the start of the recording
    rec_origin = get_nev_rec_start(nev_files[0])
    ts_per_sec = nev_files[0].basic_header['TimeStampResolution']
    start_s, end_s = round((start-rec_origin)/ts_per_sec, 6), round((end-rec_origin)/ts_per_sec, 6)
    return start_s, end_s


def stream_nev_packets(nev_file, start=0, end=None):

    end_of_header = nev_file.basic_header['BytesInHeader']
    whole_packet_size = nev_file.basic_header['BytesInDataPackets']
    ts_size = 8
    id_size = 2
    packet_data_size = whole_packet_size - ts_size

    nev_file.datafile.seek(end_of_header, 0)

    while nev_file.datafile.tell() < os.path.getsize(nev_file.datafile.name):

        timestamp = unpack("<Q", nev_file.datafile.read(ts_size))[0]

        if end is not None and timestamp > end:
            # This packet was recorded after the end of our interval. We can finish looping
            break
        elif start is not None and timestamp < start:
            # This packet was recorded before the start of our interval. Step to the next packet
            nev_file.datafile.seek(packet_data_size, 1)
        else:
            # This data packet is within our interval. Return the contents
            packet_id = unpack("<H", nev_file.datafile.read(id_size))[0]
            raw_data = nev_file.datafile.read(packet_data_size - id_size)
            yield (timestamp, packet_id), raw_data


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


def stream_nsx_data(nsx_file, elec_ids=ELEC_ID_DEF, start_loc=0, end_loc=-1):
    """
    This function is used to save a subset of data based on electrode IDs, file sizing, or file data time.  If
    both file_time_s and file_size are passed, it will default to file_time_s and determine sizing accordingly.

    :param nsx_file:
    :param elec_ids:   [optional] {list}  List of elec_ids to extract (e.g., [13])
    :param start_loc:  [optional]
    :param end_loc:    [optional]
    :yield:
    """

    # Initializations
    elec_id_indices = []
    data_point_size = nsx_file.basic_header["ChannelCount"] * DATA_BYTE_SIZE
    nsx_file.datafile.seek(0, 0)

    # Run electrode id checks and set num_elecs
    elec_ids = check_elecid(elec_ids)
    if nsx_file.basic_header["FileSpec"] == "2.1":
        all_elec_ids = nsx_file.basic_header["ChannelID"]
    else:
        all_elec_ids = [x["ElectrodeID"] for x in nsx_file.extended_headers]

    if elec_ids == ELEC_ID_DEF:
        elec_ids = all_elec_ids
    else:
        elec_ids = check_dataelecid(elec_ids, all_elec_ids)
        if not elec_ids:
            return None
        else:
            elec_id_indices = [all_elec_ids.index(x) for x in elec_ids]

    # Navigating headers to make sure we end up at the start of the data in the file
    end_of_header = nsx_file.basic_header["BytesInHeader"]

    # If we have a start location, move the cursor sufficiently far forward

    read_start = end_of_header + start_loc
    nsx_file.datafile.seek(read_start, 0)

    file_size = os.path.getsize(nsx_file.datafile.name)
    end_pointer = file_size if end_loc < 0 else end_loc

    # For all file types, loop through all data packets, extracting data based on page sizing
    while nsx_file.datafile.tell() < end_pointer:

        # Skip the 0 byte at the start of each packet
        nsx_file.datafile.seek(1, 1)
        timestamp = unpack("<Q", nsx_file.datafile.read(8))[0]
        packet_pts = unpack("<I", nsx_file.datafile.read(4))[0]
        if packet_pts == 0:
            continue  # This packet is empty

        meta = (timestamp, packet_pts)

        # get current file position and set loop parameters
        mem_map_length = (DATA_PAGING_SIZE // data_point_size) * data_point_size
        num_loops = int(ceil(packet_pts * data_point_size / mem_map_length))

        packet_start = nsx_file.datafile.tell()
        packet_size = packet_pts * data_point_size
        packet_end = min(packet_start + packet_size, end_pointer)

        # Extract the packet section by section to avoid memory constraints
        for loop in range(num_loops):
            location = nsx_file.datafile.tell()

            # This is the last packet we will be reading in this file. Adjust the size appropriately
            if location + mem_map_length > packet_end:
                section_size = packet_end - location
            else:
                # Otherwise read the full section
                section_size = mem_map_length

            num_pts = section_size // data_point_size
            shape = (int(num_pts), nsx_file.basic_header["ChannelCount"])
            memory_map = np.memmap(
                nsx_file.datafile,
                dtype=np.int16,
                mode="r",
                offset=location,
                shape=shape,
            )
            if elec_id_indices:
                memory_map = memory_map[:, elec_id_indices]

            yield meta, memory_map

            del memory_map
            meta = None

            # Move the file pointer explicitly since np.memmap is unreliable
            nsx_file.datafile.seek(location + section_size, 0)


