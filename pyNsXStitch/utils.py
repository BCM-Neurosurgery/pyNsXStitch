import os
from datetime import datetime

import numpy as np
import pandas as pd
from brpylib import NevFile, NsxFile


def read_time_origin(filepath: str) -> datetime:
    """
    Open a NeV or NsX file and return its recording ``TimeOrigin`` as a datetime.

    ``TimeOrigin`` is the UTC start-of-recording timestamp stored in the file's basic
    header. brpylib already parses it into a ``datetime`` (see ``format_timeorigin`` in
    ``brpylib.brpylib``), so this just picks the right reader and hands that value back.

    :param filepath: path to a ``.nev`` or ``.ns1``-``.ns9`` file
    :return: {datetime} the file's TimeOrigin
    """
    ext = os.path.splitext(filepath)[1].lower()
    reader = NevFile if ext == '.nev' else NsxFile
    f = reader(filepath)
    try:
        return f.basic_header['TimeOrigin']
    finally:
        f.datafile.close()


def random_date_offset():
    """Create a random datetime offset +- 31 years"""
    return pd.Timedelta(np.random.uniform(-10**9, 10**9), unit='s')


def epoch_start_offset(*dates):
    """Creates a standard date offset that sets the earliest date in the dates to the epoch start"""
    timestamps = [pd.Timestamp(d) for d in dates]
    try:
        earliest = min(timestamps)
    except ValueError:
        raise ValueError("Could not find time anchor for epoch start offset. Consider random date offsets")
    epoch_start = pd.Timestamp('1970-01-01')
    offset = epoch_start - earliest
    return offset


BRK_DATE_RE = r'(\d{8}-\d{6})'
BRK_FILENAME_RE = r'NSP(\d)-(\d{8}-\d{6})-(\d{3})\.(nev|ns\d)'
