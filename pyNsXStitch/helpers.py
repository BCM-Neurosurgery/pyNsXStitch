"""
Utility and Helper functions to help with common stitching tasks
"""

import os
import re
import warnings
from collections import namedtuple

import numpy as np
from brpylib import NevFile, NsxFile
from brpylib.brpylib import NSX_BASIC_HEADER_BYTES_22, NSX_EXT_HEADER_BYTES_22, nsx_header_dict, \
    format_none, format_stripstring, format_freq, format_filter, format_timeorigin, format_filespec

from struct import pack, unpack, calcsize

import pandas as pd

from pyNsXStitch.periods import find_nsx_parts_in_range, file_timestamp_resolution, iter_file_periods
from pyNsXStitch.stitchers import StitchedNeVFile, StitchedNsXFile
from pyNsXStitch.streamers import RESET_TOL_S, ambiguous_window_error, stream_nev_packets, iter_nsx_timestamps, \
    iter_nsx_periods, stream_nsx_data, nsx_timestamp_fmt, periods_in_window, window_overlaps, iter_nev_pages, \
    iter_nev_periods

nsx_copy_headers = []
REC_EVENT_PACKET_ID = 65529

# A recording start event in a NeV file. period is the index of the file's clock period it is in (see
# streamers.iter_nev_periods)
RecStart = namedtuple('RecStart', ['period', 'timestamp'])

_NSX_FILTER_CODES = {'none': 0, 'butterworth': 1, None: 0}

# A clock period across all of a session's files. parts maps each file type (as keyed in get_all_streamed_files,
# e.g. 'NeV', 'Ns5') to the periods.PeriodParts of that type that make it up, in filename order
GlobalPeriod = namedtuple('GlobalPeriod', ['start_ts', 'end_ts', 'parts'])


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


def get_nsx_periods(nsx_filepath):
    """
    Split the NsX file into clock periods (see streamers.iter_nsx_periods).

    :param nsx_filepath: path of the NsX file
    :return: list of (start_ts, end_ts) tuples in the file's native timestamp units, in file order. end_ts is the
        end of the period's last packet (one sample period past its last sample)
    """
    nsx_file = NsxFile(nsx_filepath, verbose=False, interactive=False)
    try:
        return [(first_ts, end_ts) for _, first_ts, end_ts, _, _ in iter_nsx_periods(nsx_file)]
    finally:
        nsx_file.datafile.close()


def get_nsx_duration(nsx_filepath):
    """
    Get the duration of this data file in the file's native timestamp units.

    This is the sum of the lengths of each of the file's periods (see get_nsx_periods), so it is never negative,
    even if the clock was reset mid-file.
    """
    return sum(end_ts - start_ts for start_ts, end_ts in get_nsx_periods(nsx_filepath))


def get_nsx_end_timestamp(nsx_filepath):
    """
    Return the end of the NsX file in time elapsed (seconds) since the recording start

    Note: this is the end of the last packet in the file, i.e. the end of the file's last period. If the file has
    more than one period (see get_nsx_periods), it may be earlier than the start timestamp of the file, as given by
    get_nsx_start_timestamp, and a warning is issued.
    """
    periods = get_nsx_periods(nsx_filepath)
    if not periods:
        raise ValueError(f'Found no data packets in NsX file! \n  {nsx_filepath}')
    if len(periods) > 1:
        warnings.warn(f'NsX file has {len(periods)} periods (timestamps reset mid-file); returning the end of the '
                      f'last period. \n  {nsx_filepath}')
    return periods[-1][1]


def get_nsx_start_timestamp(nsx_filepath):
    """Get the start time (in seconds) of this data file from the header of the first data packet"""
    try:
        nsx = NsxFile(nsx_filepath, verbose=False, interactive=False)
        end_of_header = nsx.basic_header["BytesInHeader"]
        nsx.datafile.seek(end_of_header + 1, 0)  # Move to the start of data, also skipping the null byte
        ts_fmt = nsx_timestamp_fmt(nsx)
        timestamp = unpack(ts_fmt, nsx.datafile.read(calcsize(ts_fmt)))[0]
        return timestamp
    except Exception as e:
        raise e
    finally:
        del nsx


def find_nsx_in_range(nsx_filepaths, start_ts, end_ts, subtract_offset=False, period=None):
    """
    Find all nsx files that contain data in the given range (time elapsed in seconds)

    The files are treated as one session, and split into clock periods counted in filename order (see
    periods.get_session_nsx_periods). A file is in range if its share of the selected session period overlaps
    [start_ts, end_ts]. Files are returned in filename order.

    :param nsx_filepaths: paths of all the session's NsX files of one type
    :param period: [optional] session period index (e.g. -1 for the last period). If None, the range must match
        only one session period
    :raises AmbiguousWindowError: If period is None and the range matches more than one session period
    """
    parts = find_nsx_parts_in_range(nsx_filepaths, start_ts, end_ts, period=period)
    return [part.filepath for part in parts]


def get_session_periods(streamed_files, tol_s=RESET_TOL_S):
    """
    Split a session's NeV and NsX files into clock periods with one global index, so a period id refers to the
    same stretch of data in every file type.

    Files are grouped by recording chunk (filename without extension) and the chunks are walked in filename order.
    Within a chunk, every file type sees the same clock resets, so each file's periods are lined up in order with
    the stretches found so far, matching on time overlap (a type missing a stretch just skips it). The chunk's first
    stretch continues the previous global period if it starts no more than tol_s seconds before that period ended;
    every other stretch starts a new global period.

    :param streamed_files: one NSP's files, keyed by file type (as returned by get_all_streamed_files)
    :param tol_s: [optional] {float} how far back (in seconds) data can start and stay in the same period
    :return: list of GlobalPeriods in session order
    """
    chunks = {}
    for filetype, files in streamed_files.items():
        for fp in files:
            chunks.setdefault(os.path.splitext(os.path.basename(fp))[0], []).append((filetype, fp))

    periods = []
    for chunk in sorted(chunks):
        tol = tol_s * file_timestamp_resolution(chunks[chunk][0][1])

        # Line up this chunk's file periods across file types. Each stretch is [start_ts, end_ts, {filetype: parts}]
        stretches = []
        for filetype, fp in chunks[chunk]:
            last = -1  # Index of the stretch this file's previous period went into
            for part in iter_file_periods(fp, tol_s=tol_s):
                # A file's later periods come after its earlier ones, so only look at stretches after the last one
                overlaps = [
                    (min(end_ts, part.end_ts) - max(start_ts, part.start_ts), k)
                    for k, (start_ts, end_ts, _) in enumerate(stretches)
                    if k > last
                ]
                best = max(overlaps, default=None)
                if best is not None and best[0] >= -tol:
                    last = best[1]
                    stretches[last][0] = min(stretches[last][0], part.start_ts)
                    stretches[last][1] = max(stretches[last][1], part.end_ts)
                else:
                    last += 1  # No other file type has this stretch (yet)
                    stretches.insert(last, [part.start_ts, part.end_ts, {}])
                stretches[last][2].setdefault(filetype, []).append(part)

        for i, (start_ts, end_ts, parts) in enumerate(stretches):
            if i == 0 and periods and start_ts >= periods[-1].end_ts - tol:
                # This chunk picks up where the previous one left off
                prev = periods[-1]
                for filetype, type_parts in parts.items():
                    prev.parts.setdefault(filetype, []).extend(type_parts)
                periods[-1] = prev._replace(start_ts=min(prev.start_ts, start_ts), end_ts=max(prev.end_ts, end_ts))
            else:
                periods.append(GlobalPeriod(start_ts, end_ts, parts))

    return periods


def select_session_periods(periods, start_ts=None, end_ts=None, period=None):
    """
    Pick the parts of each file type that hold the session's data in the given window.

    :param periods: GlobalPeriods, as returned by get_session_periods
    :param start_ts: [optional] start of the window. None is an open bound
    :param end_ts: [optional] end of the window. None is an open bound
    :param period: [optional] global period index (e.g. -1 for the last period). If None, the window must match
        only one period. With no window and no period, every period is selected
    :return: dict mapping each file type to its PeriodParts that overlap the window, in session order
    :raises AmbiguousWindowError: If period is None and the window matches more than one period
    """
    if period is None:
        matches = periods_in_window(periods, start_ts, end_ts)
        if len(matches) > 1 and (start_ts is not None or end_ts is not None):
            raise ambiguous_window_error(periods, matches, start_ts, end_ts, 'this session')
        selected = [periods[i] for i in matches]
    else:
        try:
            selected = [periods[period]]
        except IndexError:
            selected = []  # The session doesn't have the requested period

    in_range = {}
    for session_period in selected:
        for filetype, parts in session_period.parts.items():
            in_range.setdefault(filetype, []).extend(
                part for part in parts if window_overlaps(part.start_ts, part.end_ts, start_ts, end_ts)
            )
    return in_range


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
        recording_start = None  # We didn't find any recording start packets

    return recording_start


def get_nev_rec_starts(nev_file):
    """
    Find every recording start event in the NeV file.

    When the NSP clock is reset the file can hold more than one recording start, each in its own clock period, so
    each period's timestamps should be measured from that period's start.

    :param nev_file: NevFile object (defined in brpylib.py)
    :return: list of RecStarts (period, timestamp) in file order, with int timestamps. Empty if the file has no
        recording start events
    """
    # Last packet index of each of the file's periods, to look up which period a packet is in
    period_ends = np.array([last_packet for _, _, _, _, last_packet in iter_nev_periods(nev_file)], dtype=np.int64)

    rec_starts = []
    for start_idx, raw_data in iter_nev_pages(nev_file):
        for i in np.flatnonzero(raw_data['packet_id'] == REC_EVENT_PACKET_ID):
            event_type = unpack("<H", raw_data['data'][i][:2].tobytes())[0]
            if event_type == 0:  # This is a recording start event
                period = int(np.searchsorted(period_ends, start_idx + i))
                rec_starts.append(RecStart(period, int(raw_data['timestamp'][i])))

    return rec_starts


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


def load_comments_in_folder(source_dir):
    """
    Load all comments from all NeV files in the given folder as a pandas dataframe
    """

    # With the new version of central, data from multiple NSPs can be in the same folder
    all_streamed_files = get_all_streamed_files(source_dir, full_paths=True)
    # Sort the NSPs for consistency
    all_nsps = sorted(all_streamed_files)

    if len(all_nsps) == 1:
        # Only 1 NSP here, so we can move forward
        nsp = all_nsps[0]
        streamed_files = all_streamed_files[nsp]
    else:
        raise ValueError(f'ERROR! Invalid NSP config: {source_dir}')

    first_nsp = list(streamed_files.keys())[0]
    print(f'Using comments from {first_nsp}')
    print(f'Found {len(streamed_files["NeV"])} NeV files')

    # Iter through all the comment packets in all files
    print('Loading comments from NeV...')
    timestamps, comments = [], []
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


def write_one_nev_file(nev_file: NevFile, output_path: str):
    """
    Write an in-memory NevFile object (from brpylib.py) out to disk as a standalone .nev file.

    Copies the header verbatim, then re-writes every data packet found by stream_nev_packets.

    :param nev_file: NevFile object (defined in brpylib.py) to write out
    :param output_path: Path of the .nev file to write
    """
    print('Saving...')
    with open(output_path, 'wb') as out_file:
        # Copy the header from the origin file
        nev_file.datafile.seek(0, 0)
        out_file.seek(0, 0)
        header_size = nev_file.basic_header['BytesInHeader']
        out_file.write(nev_file.datafile.read(header_size))

        # Write all the data packets in order
        for (timestamp, packet_id), packet in stream_nev_packets(nev_file):
            out_file.write(pack('<Q', timestamp))
            out_file.write(pack('<H', packet_id))
            out_file.write(packet)
    print(f'Saved anonymized file to {output_path}')

def _fixed_str(value: str, length: int) -> bytes:
    """Encode a string to a fixed-width, null-padded byte field (inverse of brpylib.format_stripstring)."""
    return (value or '').encode('latin-1')[:length].ljust(length, b'\x00')


def _freq_to_uint(value) -> int:
    """Inverse of brpylib.format_freq, which renders a milli-Hz uint as e.g. '300.0 Hz'."""
    if value is None:
        return 0
    return int(round(float(str(value).split(' ')[0]) * 1000))


def _timeorigin_bytes(dt) -> bytes:
    """
    Inverse of brpylib.format_timeorigin: 8 x uint16 Windows SYSTEMTIME
    (year, month, day-of-week, day, hour, minute, second, millisecond).
    SYSTEMTIME's wDayOfWeek is 0=Sunday..6=Saturday.
    """
    return pack('<8H', dt.year, dt.month, dt.isoweekday() % 7, dt.day,
                dt.hour, dt.minute, dt.second, dt.microsecond // 1000)


def _pack_filespec(value, fmt: str) -> bytes:
    """Inverse of brpylib.format_filespec, which renders 2 raw uint8 as e.g. '2.3'."""
    major, minor = (int(p) for p in str(value).split('.'))
    return pack('<' + fmt, major, minor)


# Maps each brpylib format_* function (as used in nsx_header_dict field defs) to its inverse,
# so header field layout/order/widths stay driven by brpylib's own field lists rather than
# being re-typed here. Each inverse takes (value, struct_fmt_for_this_field) -> bytes.
_INVERSE_FORMATTERS = {
    format_none: lambda value, fmt: pack('<' + fmt, value),
    format_stripstring: lambda value, fmt: _fixed_str(value, calcsize(fmt)),
    format_freq: lambda value, fmt: pack('<' + fmt, _freq_to_uint(value)),
    format_filter: lambda value, fmt: pack('<' + fmt, _NSX_FILTER_CODES[value]),
    format_timeorigin: lambda value, fmt: _timeorigin_bytes(value),
    format_filespec: _pack_filespec,
}


def pack_header(fields, values: dict) -> bytes:
    """
    Inverse of brpylib.processheaders: pack a header dict back into its on-disk binary form,
    using the same field-def list (e.g. ``nsx_header_dict['basic']``) that was used to read it.
    """
    return b''.join(_INVERSE_FORMATTERS[fun](values[name], fmt) for name, fmt, fun in fields)


def _nsx_header_bytes(nsx_file: NsxFile, keep_indices: list) -> bytes:
    """
    Serialise the NsX header block (basic + extended headers) for the channels at
    ``keep_indices``, entirely from the in-memory ``nsx_file.basic_header`` /
    ``nsx_file.extended_headers``. The source file is never re-read, so edits already
    applied to those dicts (e.g. a scrambled ``TimeOrigin``) are carried through. Only
    ``BytesInHeader`` and ``ChannelCount`` are recomputed for the reduced channel set.
    """
    bh = nsx_file.basic_header
    if bh['FileTypeID'] not in ('BRSMPGRP', 'NEURALCD'):
        raise TypeError(f'Only BRSMPGRP/NEURALCD type NsX files are supported (found {bh["FileTypeID"]})')

    kept_ext = [nsx_file.extended_headers[i] for i in keep_indices]
    n_keep = len(kept_ext)
    new_bytes_in_header = NSX_BASIC_HEADER_BYTES_22 + NSX_EXT_HEADER_BYTES_22 * n_keep

    basic_values = dict(bh, BytesInHeader=new_bytes_in_header, ChannelCount=n_keep)
    header = bytearray(_fixed_str(bh['FileTypeID'], 8))
    header += pack_header(nsx_header_dict['basic'], basic_values)
    for ext in kept_ext:
        header += pack_header(nsx_header_dict['extended'], ext)

    if len(header) != new_bytes_in_header:
        raise ValueError(f'Rebuilt NsX header is {len(header)} bytes, expected {new_bytes_in_header}')
    return bytes(header)


def write_one_nsx_file(nsx_file: NsxFile, output_path: str, keep_indices=None):
    """
    Write an in-memory NsxFile object (from brpylib.py) out to disk as a standalone NsX file.

    The header is re-serialised from ``nsx_file.basic_header`` / ``nsx_file.extended_headers``
    so any edits to those dicts are preserved. The data section is streamed packet-by-packet
    via ``stream_nsx_data``, so files of arbitrary size are written with bounded memory.
    ``stream_nsx_data`` parses the 64-bit packet timestamps of filespec >= 3.0 files, which
    ``NsxFile.savesubsetnsx`` does not.

    :param nsx_file: source NsxFile object (BRSMPGRP or NEURALCD, filespec >= 2.2)
    :param output_path: path of the NsX file to write
    :param keep_indices: [optional] channel indices (positions in
        ``nsx_file.extended_headers``) to retain; ``None`` keeps every channel
    """

    print('Saving...')
    if keep_indices is None:
        keep_indices = list(range(nsx_file.basic_header['ChannelCount']))

    ts_fmt = nsx_timestamp_fmt(nsx_file)

    with open(output_path, 'wb') as out_file:
        out_file.write(_nsx_header_bytes(nsx_file, keep_indices))

        # Stream the (potentially tens of GB) data section, slicing out kept channel columns
        for meta, data_block in stream_nsx_data(nsx_file):
            if meta is not None:
                start_ts, n_points = meta
                out_file.write(b'\x01')
                out_file.write(pack(ts_fmt, start_ts))
                out_file.write(pack('<I', n_points))
            out_file.write(np.ascontiguousarray(data_block[:, keep_indices]).tobytes())

    print(f'Saved anonymized file to {output_path}')


def stitch_one_task(streamed_files, output_dir, task_name, start, end, aggressive=False, period=None):
    """
    Stitch the window [start, end] out of a session's streamed files (as returned by get_all_streamed_files)

    :param period: [optional] global period index (see get_session_periods), shared by the NeV and NsX files. If
        None, the window must match only one period
    :raises AmbiguousWindowError: If period is None and the window matches more than one period
    """
    # Find the stretches to stitch before writing anything, so an ambiguous window fails early
    session_periods = get_session_periods(streamed_files)
    if len(session_periods) > 1:
        print(f'The NSP clock was reset during this session: found {len(session_periods)} clock periods')
    in_range = select_session_periods(session_periods, start, end, period=period)
    nsx_files = {filetype: files for filetype, files in streamed_files.items() if 'ns' in filetype.lower()}
    for filetype, files in nsx_files.items():
        n_in_range = len({part.filepath for part in in_range.get(filetype, [])})
        print(f'Found {n_in_range} of {len(files)} {filetype} files in the selected time range')
        if not n_in_range:
            raise IndexError('Could not find enough files to stitch!')

    os.makedirs(output_dir, exist_ok=True)

    # Stitch the NeV files first
    print('Stitching NeV files...')
    nev_parts = [(part.filepath, part.period) for part in in_range.get('NeV', [])]
    nev_stitch = StitchedNeVFile(streamed_files['NeV'], start, end, parts=nev_parts)
    with open(os.path.join(output_dir, f'{task_name}.nev'), 'wb') as nev_out:
        nev_stitch.write(nev_out)
    print('Stitched NeV file complete')

    # Stitch each of the NsX filetypes
    print('Beginning NsX stitching...')
    for filetype, files in nsx_files.items():
        nsx_parts = [(part.filepath, part.period) for part in in_range[filetype]]
        print(f'Stitching from {len(nsx_parts)} {filetype} file periods')
        nsx_stitch = StitchedNsXFile(files, start, end, aggressive_concat=aggressive, parts=nsx_parts)
        with open(os.path.join(output_dir, f'{task_name}.{filetype.lower()}'), 'wb+') as nsx_out:
            nsx_stitch.write(nsx_out)

    print(f'Finished {task_name}')
