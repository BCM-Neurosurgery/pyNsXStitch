import numpy as np
import pandas as pd


def random_date_offset():
    """Create a random datetime offset +- 31 years"""
    return pd.Timedelta(np.random.uniform(-10**9, 10**9), unit='s')


def epoch_start_offset(*dates):
    """Creates a standard date offset that sets the earliest date in the dates to the epoch start"""
    timestamps = [pd.Timestamp(d) for d in dates]
    earliest = min(timestamps)
    epoch_start = pd.Timestamp('1970-01-01')
    offset = epoch_start - earliest
    return offset


BRK_DATE_RE = r'(\d{8}-\d{6})'
BRK_FILENAME_RE = r'NSP(\d)-(\d{8}-\d{6})-(\d{3})\.(nev|ns\d)'
