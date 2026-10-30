import warnings
from datetime import datetime, timedelta
from itertools import chain
from struct import calcsize, unpack, pack

import numpy as np
from brpylib import NsxFile, NevFile
from brpylib.brpylib import ELEC_ID_DEF, check_elecid, check_dataelecid, NSX_BASIC_HEADER_BYTES_22, \
    NSX_EXT_HEADER_BYTES_22, nev_header_dict

from pyNsXStitch.periods import find_nsx_parts_in_range
from pyNsXStitch.streamers import (
    iter_nsx_periods,
    iter_nsx_timestamps,
    stream_nev_packets,
    stream_nsx_data,
    nsx_timestamp_fmt,
)

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
            nev_file = NevFile(filename, verbose=False, interactive=False)
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
        origin = NevFile(self.files[0], verbose=False, interactive=False)
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
    # NSx 2.2+ basic-header fields before TimeOrigin: FileTypeID, FileSpec,
    # BytesInHeader, Label, Comment, Period, and TimeStampResolution.
    time_origin_loc = calcsize('<8s2BI16s256sII')
    time_origin_size = calcsize('<8H')

    def __init__(self, files_to_stitch, start=None, end=None, aggressive_concat=False, period=None):
        """
        :param files_to_stitch: NsX files of one type. With period=, these must be all of the session's files of
            that type, since the session period index counts over them
        :param start: [optional] start of the window to stitch
        :param end: [optional] end of the window to stitch
        :param aggressive_concat: merge adjacent packets with no sample gap
        :param period: [optional] session period index (see periods.get_session_nsx_periods). If None and a window
            is given, the window must match only one session period, or AmbiguousWindowError is raised
        """
        self.files = files_to_stitch
        self.start_timestamp = start
        self.end_timestamp = end
        self.concat_packets = aggressive_concat
        self.period = period
        self._parts = None

    def get_parts(self):
        """List of (filepath, file period index) to stitch, in order. A period index of None reads the whole file"""
        if self._parts is None:
            if self.period is None and self.start_timestamp is None and self.end_timestamp is None:
                self._parts = [(filename, None) for filename in self.files]  # No window, stitch everything
            else:
                parts = find_nsx_parts_in_range(self.files, self.start_timestamp, self.end_timestamp, self.period)
                self._parts = [(part.filepath, part.period) for part in parts]
        return self._parts

    def iter_data(self, gui_updater=None):
        """
        Iterator that will loop over all the data packets in all the NsX files

        See helpers.stream_nsx_data for details about how the data is streamed out from each individual file
        """
        duration = self.end_timestamp - self.start_timestamp \
            if self.end_timestamp is not None and self.start_timestamp is not None \
            else None
        for filename, file_period in self.get_parts():
            nsx_file = NsxFile(filename, verbose=False, interactive=False)
            try:
                streamer = stream_nsx_data(
                    nsx_file,
                    read_start_ts=self.start_timestamp,
                    read_end_ts=self.end_timestamp,
                    period=file_period,
                )
                for meta, data_block in streamer:
                    if gui_updater is not None and meta is not None and duration is not None:
                        elapsed = meta[0] - self.start_timestamp
                        gui_updater(100 * elapsed / duration)
                    yield meta, data_block
            finally:
                nsx_file.datafile.close()

    def write_headers(self, out_file, first_timestamp=None):

        # Load an NsX file to pull headers from: the first one we stitch data from
        parts = self.get_parts()
        origin_file, origin_period = parts[0] if parts else (self.files[0], None)
        origin = NsxFile(origin_file, verbose=False, interactive=False)
        try:
            # Verify that the NsX file is written in the supported format
            if origin.basic_header['FileTypeID'] != 'BRSMPGRP':
                type_here = origin.basic_header['FileTypeID']
                raise TypeError(f'Only BRSMPGRP type NsX files are currently supported! (found {type_here})')

            # Packet timestamps are re-packed in the origin file's format, so mixing
            # 2.x (uint32) and 3.x (uint64) files would corrupt the output
            self.ts_fmt = nsx_timestamp_fmt(origin)
            for filename in self.files:
                if filename == origin_file:
                    continue
                nsx_file = NsxFile(filename, verbose=False, interactive=False)
                try:
                    file_ts_fmt = nsx_timestamp_fmt(nsx_file)
                finally:
                    nsx_file.datafile.close()
                if file_ts_fmt != self.ts_fmt:
                    raise ValueError(
                        f'Cannot stitch NsX files with different timestamp formats: {origin_file} uses '
                        f'{self.ts_fmt!r} but {filename} uses {file_ts_fmt!r}'
                    )

            bytes_in_headers = origin.basic_header['BytesInHeader']
            origin.datafile.seek(0, 0)
            headers = bytearray(origin.datafile.read(bytes_in_headers))

            if first_timestamp is not None:
                time_origin_end = self.time_origin_loc + self.time_origin_size
                if len(headers) < time_origin_end:
                    raise ValueError(
                        'NSx header is too short to contain the TimeOrigin field '
                        f'(expected at least {time_origin_end} bytes, found {len(headers)})'
                    )

                origin_timestamp = next(
                    (
                        timestamp
                        for timestamp, packet_points in iter_nsx_timestamps(origin)
                        if packet_points > 0
                    ),
                    None,
                )
                if origin_timestamp is None:
                    raise ValueError(
                        'Cannot adjust TimeOrigin because the origin NSx file '
                        'contains no non-empty data packets'
                    )

                # TimeOrigin is the wall time of the file's first packet. If we stitch from a later clock period
                # in the file, the clock reset in between, so count the earlier periods' durations instead
                elapsed_before = 0
                if origin_period:
                    origin_periods = list(iter_nsx_periods(origin))[:origin_period + 1]
                    elapsed_before = sum(p_end - p_start for _, p_start, p_end, _, _ in origin_periods[:-1])
                    origin_timestamp = origin_periods[-1][1]
                    warnings.warn(
                        f'Stitching from clock period {origin_period} of {origin_file}; TimeOrigin is estimated '
                        f'assuming no time passed at the clock reset(s) before it'
                    )

                timestamp_resolution = origin.basic_header['TimeStampResolution']
                if timestamp_resolution <= 0:
                    raise ValueError('NSx TimeStampResolution must be greater than zero')

                # Keep packet timestamps on the global NSP clock while moving the
                # copied file origin to the first sample in the stitched output.
                timestamp_offset = elapsed_before + first_timestamp - origin_timestamp
                # Avoid float rounding; on-disk TimeOrigin precision is milliseconds.
                offset_microseconds = (
                    timestamp_offset * 1_000_000 // timestamp_resolution
                )
                time_origin = origin.basic_header['TimeOrigin'] + timedelta(
                    microseconds=offset_microseconds
                )
                headers[self.time_origin_loc:time_origin_end] = pack(
                    '<8H',
                    time_origin.year,
                    time_origin.month,
                    (time_origin.weekday() + 1) % 7,
                    time_origin.day,
                    time_origin.hour,
                    time_origin.minute,
                    time_origin.second,
                    time_origin.microsecond // 1000,
                )

            out_file.seek(0, 0)
            out_file.write(headers)

            sample_rate = (origin.basic_header['SampleResolution'] / origin.basic_header['Period'])
            ts_freq = origin.basic_header['TimeStampResolution']
            return ts_freq / sample_rate
        finally:
            origin.datafile.close()

    def write(self, out_file, gui_updater=None):

        data = iter(self.iter_data(gui_updater=gui_updater))
        try:
            first_item = next(data)
        except StopIteration:
            first_item = None

        first_timestamp = (
            first_item[0][0]
            if first_item is not None and first_item[0] is not None
            else None
        )
        ts_per_sample = self.write_headers(out_file, first_timestamp=first_timestamp)

        prev_loop_t = datetime.now()
        durations = []
        last_ts = None
        prev_n_points_loc = None
        items = chain((first_item,), data) if first_item is not None else ()
        for meta, data_block in items:

            # Data blocks at the start of a packet have timestamps. Write them back at start
            if meta is not None:

                start_ts, n_points = meta
                print(f'Processing new packet Timestamp: {start_ts}  NPoints:{n_points}')

                stitch_w_prev = False
                if last_ts is not None:
                    # last_ts already points at the next expected tick, so a seamless join has a gap of about 0
                    packet_gap_ts = start_ts - last_ts
                    print(f'  Packet gap: {packet_gap_ts}')
                    if self.concat_packets and abs(packet_gap_ts) < 0.5 * ts_per_sample:
                        # We're running in agressive stitching mode and no samples were missed between packets
                        print(f'  Concatenating packets')
                        stitch_w_prev = True
                    elif packet_gap_ts <= -0.5 * ts_per_sample:
                        # Packets overlap; start a new packet so every sample keeps its true tick. The overlapping
                        # samples are written twice and are not checked for matching data
                        n_overlap = -packet_gap_ts / ts_per_sample
                        warnings.warn(
                            f'NSx packet at timestamp {start_ts} overlaps the previous packet by {-packet_gap_ts} '
                            f'ticks (~{n_overlap:.1f} samples). Writing it as a new packet; the overlapping '
                            f'samples will appear twice in the output'
                        )

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
            if last_ts is not None:
                # Increment ts counter to the expected timestamp of the next point
                last_ts += len(data_block) * ts_per_sample

            loop_end = datetime.now()
            loop_duration = loop_end - prev_loop_t
            durations.append(loop_duration)
            prev_loop_t = datetime.now()

        print(f'Avg block write time {np.mean(durations)}')
