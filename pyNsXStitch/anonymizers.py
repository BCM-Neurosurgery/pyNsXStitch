"""
Collection of functions to help with anonymizing files (aka stripping PHI)

None of these are a guarantee that all PHI has been removed! It is the responsibility of the user to ensure that no
 elements of PHI remain in the NeV or NsX files before sharing the data.
"""
import warnings

import os
import re
import pathlib
import pandas as pd
from brpylib import NsxFile, NevFile
from pyNsXStitch.helpers import write_one_nev_file, write_one_nsx_file
from pyNsXStitch.utils import random_date_offset, epoch_start_offset, BRK_DATE_RE, BRK_FILENAME_RE

DEFAULT_AUDIO_CHAN_FRAG = [
    'mic',
    'audio',
    'room'
]
OFFSET_DEFAULT = epoch_start_offset


def scramble_date(date, offset=None):
    """
    Offset the date by a random amount of time.

    Using a consistent random offset for a whole visit would preserver order of files, but scramble the PHI
    """
    if offset is None:
        offset = OFFSET_DEFAULT()
    new_date = pd.Timestamp(date) + offset
    return new_date.to_pydatetime()


def clean_dirname(full_dirname: str, date_offset: pd.Timedelta|None =None) -> str:
    """
    Scramble any ``YYYYMMDD-HHMMSS`` date stamp found in each component of a directory path.

    :param full_dirname: directory path to clean
    :param date_offset: shared offset to apply (see scramble_date); random if None
    :return: the path with every dated component rewritten
    """
    parts = pathlib.Path(full_dirname).parts
    clean_parts = []
    for part in parts:
        date_match = re.search(BRK_DATE_RE, part)
        if date_match is not None:
            date_str = date_match.group(1)
            new_date_str = scramble_date(date_str, date_offset).strftime('%Y%m%d-%H%M%S')
            clean_parts.append(part.replace(date_str, new_date_str))
        else:
            clean_parts.append(part)
    return os.path.join(*clean_parts)


def clean_filename(full_filename: str, date_offset: pd.Timedelta|None =None) -> str:
    """
    Remove the datetime from the BRK file filename, assuming the default format
    """
    filename = os.path.basename(full_filename)
    match = re.search(BRK_FILENAME_RE, filename)
    if match is None:
        warnings.warn(f'Could not parse filename {full_filename}. Assuming no date info is contained')
        return full_filename
    nsp, date_str, chunk, ext = match.groups()

    new_date_str = scramble_date(date_str, date_offset).strftime('%Y%m%d-%H%M%S')
    new_filename = f'NSP{nsp}-{new_date_str}-{chunk}.{ext}'
    return os.path.join(os.path.dirname(full_filename), new_filename)


def remove_audio_nsx(nsx_file: NsxFile, output_filename: str, audio_channel_keys: list|None=None):
    """
    Room audio can contain snippets of conversation that make it PHI

    :param nsx_file: NsxFile object pointing to the particular file
    :param output_filename: full path to the destination of where we want to place the anonymized file
    :param audio_channel_keys: list of audio channel name fragments to search for in channel names
    """
    non_audio_channels = []
    if audio_channel_keys is None:
        audio_channel_keys = DEFAULT_AUDIO_CHAN_FRAG
    for i, metadata in enumerate(nsx_file.extended_headers):
        for forbidden in audio_channel_keys:
            if forbidden.lower() in metadata['ElectrodeLabel'].lower():
                print(f'Removing channel {metadata["ElectrodeLabel"]}')
                break
        else:
            non_audio_channels.append(i)

    return write_one_nsx_file(nsx_file, output_filename, keep_indices=non_audio_channels)


def remove_dates_nev(nev_file: NevFile, output_filename: str|None = None, date_offset: pd.Timedelta|None =None):
    """UTC dates in the NeV file are PHI"""
    print('Removing dates from headers')
    date_offset = random_date_offset() if date_offset is None else date_offset
    nev_file.basic_header['TimeOrigin'] = scramble_date(nev_file.basic_header['TimeOrigin'], date_offset)
    if output_filename:
        write_one_nev_file(nev_file, output_filename)
    return nev_file


def remove_dates_nsx(nsx_file: NsxFile, output_filename: str|None = None, date_offset: pd.Timedelta|None =None):
    """UTC dates in the NsX files are PHI since they imply admission/clinical visit dates"""
    print('Removing dates from headers')
    date_offset = random_date_offset() if date_offset is None else date_offset
    nsx_file.basic_header['TimeOrigin'] = scramble_date(nsx_file.basic_header['TimeOrigin'], date_offset)
    if output_filename:
        write_one_nsx_file(nsx_file, output_filename)
    return nsx_file


def nev_anonymize(nev_file: NevFile, output_filename: str, date_offset: pd.Timedelta|None =None):
    """
    Wrapper to apply several of the commonly used anonymization functions to an NeV file

    Currently, this focuses on:
        - Obfuscating UTC date in the TimeOrigin header

    This is not a guarantee that all PHI is removed, and you should review the data yourself
    In particular, comments in the NeV file could contain PHI!

    :param nev_file: NeV file object pointing to the particualr NeV file we want to anonymize
    :param output_filename: full path to the destination of where we want to place the anonymized file
    :param date_offset, optional: time offset to apply to the NeV file, otherwise a random offset will be chosen
    """

    no_dates_nev = remove_dates_nev(nev_file, date_offset=date_offset)
    write_one_nev_file(no_dates_nev, output_filename)


def nsx_anonymize(nsx_file: NsxFile, output_filename: str, date_offset: pd.Timedelta|None =None):
    """
    Wrapper to apply several of the commonly used anonymization functions to an NeV file

    Currently, this focuses on:
        - Obfuscating UTC date in the TimeOrigin header
        - Removing (zero-ing out) the room audio/mic

    This is not a guarantee that all PHI is removed, and you should review the data yourself

    :param nsx_file: NSX file object pointing to the particualr NeV file we want to anonymize
    :param output_filename: full path to the destination of where we want to place the anonymized file
    :param date_offset, optional: time offset to apply to the NSX file, otherwise a random offset will be chosen
    """
    no_dates_nsx = remove_dates_nsx(nsx_file, date_offset=date_offset)
    remove_audio_nsx(no_dates_nsx, output_filename) # This also writes the file



