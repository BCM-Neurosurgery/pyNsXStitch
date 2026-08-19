"""
Collection of functions to help with anonymizing files (aka stripping PHI)

None of these are a guarantee that all PHI has been removed! It is the responsibility of the user to ensure that no
 elements of PHI remain in the NeV or NsX files before sharing the data.
"""


import numpy as np
import pandas as pd
from brpylib import NsxFile, NevFile
from helpers import write_one_nev_file, write_one_nsx_file

AUDIO_CHAN_NAMES = [
    'mic',
    'audio'
]

def random_date_offset():
    """Create a random datetime offset +- 31 years"""
    return pd.Timedelta(np.random.uniform(-10**9, 10**9), unit='s')

def scramble_date(date, offset=None):
    """
    Offset the date by a random amount of time.

    Using a consistent random offset for a whole visit would preserver order of files, but scramble the PHI
    """
    if offset is None:
        offset = random_date_offset()
    new_date = pd.Timestamp(date) + offset
    return new_date.to_pydatetime()


def remove_audio_nsx(nsx_file: NsxFile, output_filename: str):
    """Room audio can contain snippets of conversation that make it PHI"""
    non_audio_channels = []
    for i, metadata in enumerate(nsx_file.extended_headers):
        for forbidden in AUDIO_CHAN_NAMES:
            if forbidden in metadata['ElectrodeLabel']:
                print(f'Removing channel {metadata["ElectrodeLabel"]}')
                break
        else:
            non_audio_channels.append(i)

    return nsx_file.savesubsetnsx(non_audio_channels, out_file=output_filename)


def remove_dates_nev(nev_file: NevFile, output_filename: str|None = None, date_offset: pd.Timedelta|None =None):
    """UTC dates in the NeV file are PHI"""
    date_offset = random_date_offset() if date_offset is None else date_offset
    nev_file.basic_header['TimeOrigin'] = scramble_date(nev_file.basic_header['TimeOrigin'], date_offset)
    if output_filename:
        write_one_nev_file(nev_file, output_filename)
    return nev_file


def remove_dates_nsx(nsx_file: NsxFile, output_filename: str|None = None, date_offset: pd.Timedelta|None =None):
    """UTC dates in the NsX files are PHI since they imply admission/clinical visit dates"""

    date_offset = random_date_offset() if date_offset is None else date_offset
    nsx_file.basic_header['TimeOrigin'] = scramble_date(nsx_file.basic_header['TimeOrigin'], date_offset)

    if output_filename:
        write_one_nsx_file(nsx_file, output_filename)
    return nsx_file


def nev_anonymize(nev_file: NevFile, output_filename: str):
    """
    Wrapper to apply several of the commonly used anonymization functions to an NeV file

    Currently, this focuses on:
        - Obfuscating UTC date in the TimeOrigin header

    This is not a guarantee that all PHI is removed, and you should review the data yourself
    In particular, comments in the NeV file could contain PHI!
    """

    no_dates_nev = remove_dates_nev(nev_file)
    write_one_nev_file(no_dates_nev, output_filename)


def nsx_anonymize(nsx_file: NsxFile, output_filename: str):
    """
    Wrapper to apply several of the commonly used anonymization functions to an NeV file

    Currently, this focuses on:
        - Obfuscating UTC date in the TimeOrigin header
        - Removing (zero-ing out) the room audio/mic

    This is not a guarantee that all PHI is removed, and you should review the data yourself
    """
    no_dates_nsx = remove_dates_nsx(nsx_file)
    remove_audio_nsx(no_dates_nsx, output_filename) # This also writes the file



