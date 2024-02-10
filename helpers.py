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
    in_range = False
    files = []
    for nsx_fp in nsx_filepaths:
        file_start = get_nsx_start_time(nsx_fp)
        file_end = get_nsx_end_time(nsx_fp)
        if file_start <= start < file_end:
            in_range = True
        elif file_start < end <= file_end:
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
    start_s, end_s = round(start/ts_per_sec, 6), round(end/ts_per_sec, 6)
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


def stream_nsx_data(nsx_file, elec_ids=ELEC_ID_DEF, read_start_ts=None, read_end_ts=None):
    """
    This function is used to save a subset of data based on electrode IDs, file sizing, or file data time.  If
    both file_time_s and file_size are passed, it will default to file_time_s and determine sizing accordingly.

    Note: data is stored in the NsX file in 'packets'. These can be of various sizes. To maintain speed and avoid
    out-of-memory constraints we do not copy the entire packet at once, but rather stream packet data out section by
    section. These sections are of fixe maximum size, and the size is set by DATA_PAGING_SIZE

    :param nsx_file:
    :param elec_ids:   [optional] {list}  List of elec_ids to extract (e.g., [13])
    :param read_start_ts:  [optional]
    :param read_end_ts:    [optional]
    :yield:
    """

    # Initializations
    elec_id_indices = []
    data_point_size = nsx_file.basic_header["ChannelCount"] * DATA_BYTE_SIZE
    nsx_file.datafile.seek(0, 0)
    section_size = (DATA_PAGING_SIZE // data_point_size) * data_point_size

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
    nsx_file.datafile.seek(end_of_header, 0)

    # For all file types, loop through all data packets, extracting data based on page sizing
    file_size = os.path.getsize(nsx_file.datafile.name)
    while nsx_file.datafile.tell() <= file_size:

        # Get the time and length of this data packet
        nsx_file.datafile.seek(1, 1)
        timestamp = unpack("<Q", nsx_file.datafile.read(8))[0]
        packet_pts = unpack("<I", nsx_file.datafile.read(4))[0]
        if packet_pts == 0:
            continue  # This packet is empty
        meta = (timestamp, packet_pts)

        # Determine whether we should read this packet from the file
        packet_end_ts = timestamp + packet_pts
        if read_start_ts and packet_end_ts < read_start_ts:
            continue  # This entire packet is before the read start timestamp. Move to the next packet
        if read_end_ts and read_end_ts < timestamp:
            break  # This packet is past the end of the requested interval. Finish

        # Determine the altered start of the read if the start timestamp is within this packet
        start_ts = max(read_start_ts, timestamp) if read_start_ts else timestamp
        read_start = abs(start_ts - timestamp) * data_point_size
        nsx_file.datafile.seek(read_start, 1)

        # Determine the altered end of the read in this packet if the end timestamp is in this packet
        end_ts = min(read_end_ts, packet_end_ts) if read_end_ts else packet_end_ts
        read_end = abs(end_ts - timestamp) * data_point_size

        read_size = read_end - read_start
        num_loops = int(ceil(read_size / section_size))

        # Extract the data in the packet section by section to avoid memory constraints
        for loop in range(num_loops):
            location = nsx_file.datafile.tell()

            # This is the last section we will be reading in this packet. Adjust the size appropriately
            if location + section_size > read_end:
                section_size = read_end - location
            else:
                # Otherwise read the full section
                section_size = section_size

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
            meta = None  # We only return the packet metadata with the first section of the packet

            # Move the file pointer explicitly since np.memmap is unreliable
            nsx_file.datafile.seek(location + section_size, 0)


