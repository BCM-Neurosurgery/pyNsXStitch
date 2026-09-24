import os
from math import ceil
from struct import unpack, calcsize
import numpy as np
from brpylib.brpylib import DATA_BYTE_SIZE

TIMESTAMP_BYTE_SIZE = 8
DATA_PAGING_SIZE = 1024**2

# Per-packet timestamp width in the NsX data section. FileSpec >= 3.0 (BRSMPGRP) packets carry
# a 64-bit PTP timestamp; FileSpec 2.2/2.3 (NEURALCD) packets carry a 32-bit timestamp (see
# brpylib.nsx_header_dict['data']). FileSpec 2.1 (NEURALSG) has no per-packet framing at all
# and is not covered here.
NSX_PTP_TS_FMT = '<Q'
NSX_LEGACY_TS_FMT = '<I'


def nsx_timestamp_fmt(nsx_file) -> str:
    """Struct format for this NsX file's per-packet timestamp field, based on its FileSpec major version."""
    major = int(str(nsx_file.basic_header['FileSpec']).split('.')[0])
    return NSX_PTP_TS_FMT if major >= 3 else NSX_LEGACY_TS_FMT

def stream_nev_packets(nev_file, start_ts=0, end_ts=None, packet_type=None):
    """
    Iterator that sequentially yields all the packets saved in the NeV files.
    
    This function uses np.memmap to efficiently load the data packets from the file in a memory-mapped way. 
    The data is processed in sections defined by DATA_PAGING_SIZE to avoid memory issues.

    :param nev_file:       NevFile object (defined in brpylib.py) from which to stream packets
    :param start_ts:       [optional] {float} Starting time in seconds on NSP clock to filter for. Default: 0.0
    :param end_ts:         [optional] {float} Ending time in seconds on NSP clock to filter for. Default: None
    :param packet_type:    [optional] {int}   Packet ID to filter for. Default: None
    :yield:                {tuple}: ((timestamp, packet_id), data) A tuple containing the packet information 
                                        - timestamp: {int} Timestamp of the packet
                                        - packet_id: {int} Packet ID of the packet
                                        - data: {bytes} Raw data of the packet as bytes
    :raises OSError:       If there is an issue while accessing the file using np.memmap.
    """

    # Total number of bytes in both headers and a 0-indexed pointer to the first data packet
    end_of_header = nev_file.basic_header['BytesInHeader']

    # Length (in bytes) of the fixed width data packets in the data section of the file
    data_packet_size = nev_file.basic_header['BytesInDataPackets']

    nev_file.datafile.seek(0, 2)  # Move fp to end of file
    end_of_file = nev_file.datafile.tell()

    n_packets = int((end_of_file - end_of_header) / data_packet_size)

    # Move fp to start of first data packet
    nev_file.datafile.seek(end_of_header, 0)

    # Define the structured data type for each packet
    packet_dtype = np.dtype([
        ('timestamp', '<u8'),  # np.uint64
        ('packet_id', '<u2'),  # np.uint16
        ('data', 'u1', data_packet_size - 10)
    ])
    
    # Process data in the packet section by section to avoid memory issues
    for start_idx in range(0, n_packets, DATA_PAGING_SIZE):
        end_idx = min(start_idx + DATA_PAGING_SIZE, n_packets)
        try:
            raw_data = np.memmap(
                nev_file.datafile,
                dtype=packet_dtype,
                mode="r",
                shape=(end_idx - start_idx,),
                offset=end_of_header + start_idx * data_packet_size)
                # [!] By default, memmap will start at the beginning of the file, 
                # even if filename is a file pointer fp and fp.tell() != 0
                # So we still need to explicitly set the offset to the start of the data packets
        except OSError as e:
            raise e

        # Boolean masks to filter packet type and timestamp
        mask_packet_type = raw_data['packet_id'] == packet_type if packet_type is not None else True
        mask_start = raw_data['timestamp'] >= start_ts if start_ts is not None else True
        mask_end = raw_data['timestamp'] <= end_ts if end_ts is not None else True

        mask_combined = mask_start & mask_end & mask_packet_type

        filtered_data = raw_data[mask_combined]

        for timestamp, packet_id, data in filtered_data:
            yield (timestamp, packet_id), data.tobytes()


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
    sample_freq = int(nsx_file.basic_header['SampleResolution'] / nsx_file.basic_header['Period'])
    ts_freq = nsx_file.basic_header['TimeStampResolution']
    ts_ratio = ts_freq / sample_freq
    n_channels = nsx_file.basic_header["ChannelCount"]
    data_point_size = n_channels * DATA_BYTE_SIZE
    ts_fmt = nsx_timestamp_fmt(nsx_file)
    ts_size = calcsize(ts_fmt)
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
        timestamp = unpack(ts_fmt, nsx_file.datafile.read(ts_size))[0]
        packet_pts = unpack("<I", nsx_file.datafile.read(4))[0]
        packet_start = nsx_file.datafile.tell()
        if packet_pts == 0:
            continue  # This packet is empty

        # Determine whether we should read this packet from the file
        packet_end_ts = timestamp + int(round(packet_pts * ts_ratio))
        if read_start_ts and packet_end_ts < read_start_ts:
            packet_size = packet_pts*data_point_size
            nsx_file.datafile.seek(packet_size, 1)
            continue  # This entire packet is before the read start timestamp. Move to the next packet
        if read_end_ts and read_end_ts < timestamp:
            break  # This packet is past the end of the requested interval. Finish

        # Determine the altered start of the read if the start timestamp is within this packet
        start_ts = max(read_start_ts, timestamp) if read_start_ts else timestamp
        n_points_to_skip = int(np.floor(abs(start_ts - timestamp) / ts_ratio))
        read_start = packet_start + n_points_to_skip * data_point_size
        nsx_file.datafile.seek(read_start, 0)

        # Determine the altered end of the read in this packet if the end timestamp is in this packet
        end_ts = min(read_end_ts, packet_end_ts) if read_end_ts else packet_end_ts
        read_end = packet_start + int(np.ceil(abs(end_ts - timestamp)/ts_ratio)) * data_point_size

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
            loc = nsx_file.datafile.tell()
            try:
                memory_map = np.memmap(
                    nsx_file.datafile,
                    dtype=np.int16,
                    mode="r",
                    offset=location,
                    shape=shape,
                )
            except OSError as e:
                raise e

            yield meta, memory_map

            del memory_map
            meta = None  # We only return the packet metadata with the first section of the packet

            # Move the file pointer explicitly since np.memmap is unreliable
            nsx_file.datafile.seek(location + this_section_size, 0)


def iter_nsx_timestamps(nsx_file):
    """Loop through and quickly read off all the packet headers in an NsX file"""
    data_point_size = nsx_file.basic_header['ChannelCount'] * DATA_BYTE_SIZE
    ts_fmt = nsx_timestamp_fmt(nsx_file)
    ts_size = calcsize(ts_fmt)

    file_size = os.path.getsize(nsx_file.datafile.name)
    ts_pointer = nsx_file.basic_header['BytesInHeader'] + 1
    while ts_pointer < file_size:
        nsx_file.datafile.seek(ts_pointer, 0)
        timestamp = unpack(ts_fmt, nsx_file.datafile.read(ts_size))[0]
        packet_points = unpack('<I', nsx_file.datafile.read(4))[0]

        yield timestamp, packet_points

        ts_pointer = nsx_file.datafile.tell() + (packet_points * data_point_size) + 1
