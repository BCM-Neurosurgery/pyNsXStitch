import os
from math import ceil
from struct import unpack
import shutil
import numpy as np
from brpylib.brpylib import ELEC_ID_DEF, check_elecid, DATA_BYTE_SIZE, DATA_PAGING_SIZE


def stream_nev_packets(nev_file, start_ts=0, end_ts=None):
    """
    Iterator that sequentially yields all the packets saved in the NeV files

    :param nev_file: NeVFile object from which to stream packets
    :param start_ts:
    :param end_ts:
    :return:
    """

    end_of_header = nev_file.basic_header['BytesInHeader']
    whole_packet_size = nev_file.basic_header['BytesInDataPackets']
    ts_size = 8
    id_size = 2
    packet_data_size = whole_packet_size - ts_size

    nev_file.datafile.seek(end_of_header, 0)

    while nev_file.datafile.tell() < os.path.getsize(nev_file.datafile.name):

        timestamp = unpack("<Q", nev_file.datafile.read(ts_size))[0]

        if end_ts is not None and timestamp > end_ts:
            # This packet was recorded after the end of our interval. We can finish looping
            break
        elif start_ts is not None and timestamp < start_ts:
            # This packet was recorded before the start of our interval. Step to the next packet
            nev_file.datafile.seek(packet_data_size, 1)
        else:
            # This data packet is within our interval. Return the contents
            packet_id = unpack("<H", nev_file.datafile.read(id_size))[0]
            raw_data = nev_file.datafile.read(packet_data_size - id_size)
            yield (timestamp, packet_id), raw_data


def stream_nsx_data(nsx_file, read_start_ts=None, read_end_ts=None):
    """
    This function is used to save a subset of data based on electrode IDs, file sizing, or file data time.  If
    both file_time_s and file_size are passed, it will default to file_time_s and determine sizing accordingly.

    Note: data is stored in the NsX file in 'packets'. These can be of various sizes. To maintain speed and avoid
    out-of-memory constraints we do not copy the entire packet at once, but rather stream packet data out section by
    section. These sections are of fixe maximum size, and the size is set by DATA_PAGING_SIZE

    :param nsx_file:
    :param read_start_ts:  [optional]
    :param read_end_ts:    [optional]
    :yield:
    """

    # Initializations
    n_channels = nsx_file.basic_header["ChannelCount"]
    data_point_size = n_channels * DATA_BYTE_SIZE
    nsx_file.datafile.seek(0, 0)
    section_size = (DATA_PAGING_SIZE // data_point_size) * data_point_size

    # Navigating headers to make sure we end up at the start of the data in the file
    end_of_header = nsx_file.basic_header["BytesInHeader"]
    nsx_file.datafile.seek(end_of_header, 0)

    # For all file types, loop through all data packets, extracting data based on page sizing
    file_size = os.path.getsize(nsx_file.datafile.name)
    while nsx_file.datafile.tell() < file_size:

        # Get the time and length of this data packet
        nsx_file.datafile.seek(1, 1)
        timestamp = unpack("<Q", nsx_file.datafile.read(8))[0]
        packet_pts = unpack("<I", nsx_file.datafile.read(4))[0]
        packet_start = nsx_file.datafile.tell()
        if packet_pts == 0:
            continue  # This packet is empty

        # Determine whether we should read this packet from the file
        packet_end_ts = timestamp + packet_pts
        if read_start_ts and packet_end_ts < read_start_ts:
            continue  # This entire packet is before the read start timestamp. Move to the next packet
        if read_end_ts and read_end_ts < timestamp:
            break  # This packet is past the end of the requested interval. Finish

        # Determine the altered start of the read if the start timestamp is within this packet
        start_ts = max(read_start_ts, timestamp) if read_start_ts else timestamp
        read_start = packet_start + abs(start_ts - timestamp) * data_point_size
        nsx_file.datafile.seek(read_start, 0)

        # Determine the altered end of the read in this packet if the end timestamp is in this packet
        end_ts = min(read_end_ts, packet_end_ts) if read_end_ts else packet_end_ts
        read_end = packet_start + abs(end_ts - timestamp) * data_point_size
        if end_ts != packet_end_ts:
            pass

        # Determine the number of sections that will be needed to read all the data in this packet
        read_size = read_end - read_start
        num_loops = int(ceil(read_size / section_size))

        # Save the header for this packet after taking into account any potential slicing
        n_points = int(round(read_size / data_point_size))  # We're just rounding floating point errors here
        meta = (start_ts, n_points)

        # Extract the data in the packet section by section to avoid memory constraints
        for loop in range(num_loops):
            location = nsx_file.datafile.tell()

            # This is the last section we will be reading in this packet. Adjust the size appropriately
            if location == read_end:
                print(f'Hit the end of the packet with {num_loops-loop-1} out of {num_loops} section loops left')
                break
            elif location > read_end:
                raise IndexError("We've read past the end of the packet in an NsX file!?")
            elif location + section_size > read_end:
                this_section_size = read_end - location
            else:
                # Otherwise read the full section
                this_section_size = section_size

            num_pts = this_section_size // data_point_size
            shape = (int(num_pts), n_channels)
            memory_map = np.memmap(
                nsx_file.datafile,
                dtype=np.int16,
                mode="r",
                offset=location,
                shape=shape,
            )

            yield meta, memory_map

            del memory_map
            meta = None  # We only return the packet metadata with the first section of the packet

            # Move the file pointer explicitly since np.memmap is unreliable
            nsx_file.datafile.seek(location + this_section_size, 0)


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
