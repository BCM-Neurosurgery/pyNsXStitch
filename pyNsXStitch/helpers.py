"""
Utility and Helper functions to help with common stitching tasks
"""

import os
import re
import warnings

import numpy as np
from brpylib import NevFile, NsxFile

from struct import pack, unpack

import pandas as pd

from pyNsXStitch.stitchers import StitchedNeVFile, StitchedNsXFile
from pyNsXStitch.streamers import stream_nev_packets, iter_nsx_timestamps, stream_nsx_data

nsx_copy_headers = []
REC_EVENT_PACKET_ID = 65529

# On-disk sizes (bytes) of the NsX 2.2+ / 3.x headers, matching brpylib's layout
NSX_BASIC_HEADER_BYTES = 314
NSX_EXT_HEADER_BYTES = 66
_NSX_FILTER_CODES = {'none': 0, 'butterworth': 1, None: 0}


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
        recording_start = None  # We didn't find any recording start packets

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
    print(f'Loading comments from NeV...')
    timestamps, comments, file_names = [], [], []
    n_files = len(streamed_files["NeV"])
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


def _nsx_header_bytes(nsx_file: NsxFile, keep_indices: list) -> bytes:
    """
    Serialise the NsX header block (basic + extended headers) for the channels at
    ``keep_indices``, entirely from the in-memory ``nsx_file.basic_header`` /
    ``nsx_file.extended_headers``. The source file is never re-read, so edits already
    applied to those dicts (e.g. a scrambled ``TimeOrigin``) are carried through. Only
    ``BytesInHeader`` and ``ChannelCount`` are recomputed for the reduced channel set.
    """
    bh = nsx_file.basic_header
    if bh['FileTypeID'] != 'BRSMPGRP':
        raise TypeError(f'Only BRSMPGRP type NsX files are supported (found {bh["FileTypeID"]})')

    kept_ext = [nsx_file.extended_headers[i] for i in keep_indices]
    n_keep = len(kept_ext)
    new_bytes_in_header = NSX_BASIC_HEADER_BYTES + NSX_EXT_HEADER_BYTES * n_keep

    major, minor = (int(p) for p in str(bh['FileSpec']).split('.'))
    header = bytearray(
        _fixed_str(bh['FileTypeID'], 8)
        + pack('<BB', major, minor)
        + pack('<I', new_bytes_in_header)
        + _fixed_str(bh['Label'], 16)
        + _fixed_str(bh['Comment'], 256)
        + pack('<I', bh['Period'])
        + pack('<I', int(bh['TimeStampResolution']))
        + _timeorigin_bytes(bh['TimeOrigin'])
        + pack('<I', n_keep)
    )
    for ext in kept_ext:
        header += (
            _fixed_str(ext['Type'], 2)
            + pack('<H', ext['ElectrodeID'])
            + _fixed_str(ext['ElectrodeLabel'], 16)
            + pack('<BB', ext['PhysicalConnector'], ext['ConnectorPin'])
            + pack('<hhhh', ext['MinDigitalValue'], ext['MaxDigitalValue'],
                   ext['MinAnalogValue'], ext['MaxAnalogValue'])
            + _fixed_str(ext['Units'], 16)
            + pack('<IIH', _freq_to_uint(ext['HighFreqCorner']), ext['HighFreqOrder'],
                   _NSX_FILTER_CODES[ext['HighFreqType']])
            + pack('<IIH', _freq_to_uint(ext['LowFreqCorner']), ext['LowFreqOrder'],
                   _NSX_FILTER_CODES[ext['LowFreqType']])
        )

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

    :param nsx_file: source NsxFile object (BRSMPGRP / filespec >= 2.2)
    :param output_path: path of the NsX file to write
    :param keep_indices: [optional] channel indices (positions in
        ``nsx_file.extended_headers``) to retain; ``None`` keeps every channel
    """
    if keep_indices is None:
        keep_indices = list(range(nsx_file.basic_header['ChannelCount']))

    with open(output_path, 'wb') as out_file:
        out_file.write(_nsx_header_bytes(nsx_file, keep_indices))

        # Stream the (potentially tens of GB) data section, slicing out kept channel columns
        for meta, data_block in stream_nsx_data(nsx_file):
            if meta is not None:
                start_ts, n_points = meta
                out_file.write(b'\x01')
                out_file.write(pack('<Q', start_ts))
                out_file.write(pack('<I', n_points))
            out_file.write(np.ascontiguousarray(data_block[:, keep_indices]).tobytes())

    print(f'Saved anonymized file to {output_path}')


def stitch_one_task(streamed_files, output_dir, task_name, start, end, aggressive=False):

    os.makedirs(output_dir, exist_ok=True)

    # Stitch the NeV files first
    print('Stitching NeV files...')
    nev_stitch = StitchedNeVFile(streamed_files['NeV'], start, end)
    with open(os.path.join(output_dir, f'{task_name}.nev'), 'wb') as nev_out:
        nev_stitch.write(nev_out)
    print('Stitched NeV file complete')

    # Stitch each of the NsX filetypes
    print('Beginning NsX stitching...')
    nsx_files = {filetype: files for filetype, files in streamed_files.items() if 'ns' in filetype.lower()}
    for filetype, files in nsx_files.items():
        print(f'Stitching from {len(files)} {filetype} files')
        in_range = find_nsx_in_range(files, start, end)
        print(f'Found {len(in_range)} files in the selected time range')
        if in_range:
            nsx_stitch = StitchedNsXFile(in_range, start, end, aggressive_concat=aggressive)
            with open(os.path.join(output_dir, f'{task_name}.{filetype.lower()}'), 'wb+') as nsx_out:
                nsx_stitch.write(nsx_out)
        else:
            raise IndexError('Could not find enough files to stitch!')

    print(f'Finished {task_name}')

