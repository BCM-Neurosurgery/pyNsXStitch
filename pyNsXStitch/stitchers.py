from struct import unpack, pack, calcsize

import numpy as np
from datetime import datetime
from brpylib import NsxFile, NevFile
from brpylib.brpylib import ELEC_ID_DEF, check_elecid, check_dataelecid, NSX_BASIC_HEADER_BYTES_22, \
    NSX_EXT_HEADER_BYTES_22, nev_header_dict

from pyNsXStitch.streamers import stream_nev_packets, stream_nsx_data, nsx_timestamp_fmt


class StitchedNeVFile(object):

    meta_size = 8 + 2
    # On-disk size (bytes) of the NEV basic header, derived from brpylib's own field layout
    basic_header_size = calcsize('<' + ''.join(fmt for _, fmt, _ in nev_header_dict['basic']))

    def __init__(self, files_to_stitch, start=None, end=None):
        self.files = files_to_stitch
        self.start_timestamp = start
        self.end_timestamp = end
        self.skip_packet_ids = None

    def get_max_packet_size(self):
        packet_sizes = [NevFile(filename).basic_header['BytesInDataPackets'] for filename in self.files]
        print(f'Found {len(packet_sizes)} packets with sizes: {packet_sizes}')
        return max(packet_sizes)

    def iter_data(self, gui_updater=None, skip_duplicates=True):
        """Iterate through all the data packets in a file"""
        max_packet = self.get_max_packet_size()
        if self.start_timestamp is not None and self.end_timestamp is not None:
            duration = self.end_timestamp - self.start_timestamp
        else:
            duration = None

        prev_meta, prev_data = [None, None], None

        for file_i, filename in enumerate(self.files):
            nev_file = NevFile(filename)
            streamer = stream_nev_packets(nev_file, start_ts=self.start_timestamp, end_ts=self.end_timestamp)
            for meta, packet_data in streamer:
                if gui_updater is not None and duration is not None:
                    elapsed = meta[0] - self.start_timestamp
                    gui_updater(100 * elapsed / duration)

                # Detect and skip some packets if we were asked to skip packets of this type
                if self.skip_packet_ids is not None and meta[1] in self.skip_packet_ids:
                    continue

                # Check if this packet is a duplicate of a previous packet right before yielding it
                if skip_duplicates and np.all([prev_meta[i] == meta[i] for i in [0, 1]]) and packet_data == prev_data:
                    continue  # Timestamp, packet type, and payload were all the same, skip this packet

                # Make sure that all packets from all files are the same size
                n_bytes_to_pad = (max_packet - self.meta_size - len(packet_data))
                padded_packet = packet_data + (b'\x00' * n_bytes_to_pad)
                yield meta, padded_packet
                prev_meta, prev_data = meta, packet_data

    def write_headers(self, out_file):
        """"""

        # Copy all the headers from the origin file
        origin = NevFile(self.files[0])
        origin.datafile.seek(0, 0)
        out_file.seek(0, 0)

        header_size = origin.basic_header['BytesInHeader']
        out_file.write(origin.datafile.read(header_size))

    def write(self, out_file, gui_updater=None):

        self.write_headers(out_file)

        # Write all the data packets in order
        for meta, packet in self.iter_data(gui_updater=gui_updater):
            out_file.write(pack('<Q', meta[0]))
            out_file.write(pack('<H', meta[1]))

            out_file.write(packet)


class StitchedNsXFile(object):

    max_packet_len = 2**32-1

    def __init__(self, files_to_stitch, start=None, end=None, aggressive_concat=False):

        self.files = files_to_stitch
        self.start_timestamp = start
        self.end_timestamp = end
        self.concat_packets = aggressive_concat

    def iter_data(self, gui_updater=None):
        """
        Iterator that will loop over all the data packets in all the NsX files

        See helpers.stream_nsx_data for details about how the data is streamed out from each individual file
        """
        duration = self.end_timestamp - self.start_timestamp \
            if self.end_timestamp is not None and self.start_timestamp is not None \
            else None
        for file_i, filename in enumerate(self.files):
            nsx_file = NsxFile(filename)
            streamer = stream_nsx_data(
                nsx_file,
                read_start_ts=self.start_timestamp,
                read_end_ts=self.end_timestamp
            )
            for meta, data_block in streamer:
                if gui_updater is not None and meta is not None and duration is not None:
                    elapsed = meta[0] - self.start_timestamp
                    gui_updater(100 * elapsed / duration)
                if meta is not None:
                    pass
                yield meta, data_block

    def write_headers(self, out_file):

        # Load an NsX file to pull headers from
        origin = NsxFile(self.files[0])
        origin.datafile.seek(0, 0)

        # Verify that the NsX file is written in a supported format
        if origin.basic_header['FileTypeID'] not in ('BRSMPGRP', 'NEURALCD'):
            type_here = origin.basic_header['FileTypeID']
            raise TypeError(f'Only BRSMPGRP/NEURALCD type NsX files are currently supported! (found {type_here})')

        # Make sure we're writing to hte very start of the new file
        out_file.seek(0, 0)

        # Copy over the headers
        bytes_in_headers = origin.basic_header['BytesInHeader']
        out_file.write(origin.datafile.read(bytes_in_headers))

        # New packets we write out use the same per-packet timestamp width as the source file
        self.ts_fmt = nsx_timestamp_fmt(origin)

        sample_rate = (origin.basic_header['SampleResolution'] / origin.basic_header['Period'])
        ts_freq = origin.basic_header['TimeStampResolution']
        return ts_freq / sample_rate

    def write(self, out_file, gui_updater=None):

        ts_per_sample = self.write_headers(out_file)

        prev_loop_t = datetime.now()
        durations = []
        last_ts = None
        prev_n_points_loc = None
        for meta, data_block in self.iter_data(gui_updater=gui_updater):

            # Data blocks at the start of a packet have timestamps. Write them back at start
            if meta is not None:

                start_ts, n_points = meta
                print(f'Processing new packet Timestamp: {start_ts}  NPoints:{n_points}')

                stitch_w_prev = False
                if self.concat_packets and last_ts is not None:
                    # We're running in agressive stitching mode, so check for data drops
                    packet_gap_ts = start_ts - last_ts
                    print(f'  Packet gap: {packet_gap_ts}')
                    if packet_gap_ts <= ts_per_sample:
                        print(f'  Concatenating packets')
                        stitch_w_prev = True  # No samples were missed between packets

                if stitch_w_prev:
                    # We write this packet as part of the previous packet, update the previous packet header with
                    # the number of additional data points that will be written here
                    continue_loc = out_file.tell()
                    out_file.seek(prev_n_points_loc, 0)
                    prev_n_points = unpack('<I', out_file.read(4))[0]
                    new_n_points = prev_n_points + n_points
                    if new_n_points > self.max_packet_len:
                        raise OverflowError('Max packet length exceeded!\n'
                                            '  Choose a shorter time range or disable aggressive concatenation!')
                    out_file.seek(prev_n_points_loc, 0)
                    out_file.write(pack('<I', new_n_points))

                    # Reset the write head back to where we were to continue writing data
                    out_file.seek(continue_loc, 0)

                else:
                    # Write this packet as a new packets
                    out_file.write(b'\x01')
                    out_file.write(pack(self.ts_fmt, start_ts))
                    prev_n_points_loc = out_file.tell()  # Save this data location for future reference
                    out_file.write(pack('<I', n_points))
                    last_ts = start_ts  # Reset the ts counter to the start of this packet

            out_file.write(data_block)
            last_ts += len(data_block) * ts_per_sample  # Increment ts counter to timestamp of the last written point

            loop_end = datetime.now()
            loop_duration = loop_end - prev_loop_t
            durations.append(loop_duration)
            prev_loop_t = datetime.now()

        print(f'Avg block write time {np.mean(durations)}')
