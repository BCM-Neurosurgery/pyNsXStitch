import os
from math import ceil
from struct import unpack

import numpy as np
from brpylib.brpylib import ELEC_ID_DEF, check_elecid, DATA_BYTE_SIZE, DATA_PAGING_SIZE


def stream_nev_packets(nev_file, start=0, end=None):
    """
    Iterator that sequentially yields all the packets saved in the NeV files

    :param nev_file: NeVFile object from which to stream packets
    :param start:
    :param end:
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


def stream_nsx_data(nsx_file, elec_ids=ELEC_ID_DEF, read_start_time=None, read_end_time=None):
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
    elec_names = check_elecid(elec_ids)
    all_elecs = [elec_info['ElectrodeID'] for elec_info in nsx_file.extended_headers]
    elec_id_indices = None  # TODO: implement better electrode selection

    ts_freq = nsx_file.basic_header['TimeStampResolution']
    n_channels = nsx_file.basic_header["ChannelCount"]
    data_point_size = n_channels * DATA_BYTE_SIZE
    nsx_file.datafile.seek(0, 0)
    section_size = (DATA_PAGING_SIZE // data_point_size) * data_point_size

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
        read_start_ts = round(read_start_time * ts_freq) if read_start_time else None
        read_end_ts = round(read_end_time * ts_freq) if read_end_time else None
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
            shape = (int(num_pts), n_channels)
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
