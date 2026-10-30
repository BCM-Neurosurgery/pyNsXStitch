"""
Clock periods across a whole recording session.

When the NSP clock is reset, timestamps start over, so the same timestamp can occur more than once in a session.
A clock period is a run of packets whose timestamps don't go back by more than RESET_TOL_S (see
streamers.iter_nsx_periods), and within a single file periods are indexed as it yields them. Across a session's files, periods are counted in filename order, and a period can
span several files.
"""

import os
from collections import namedtuple

from brpylib import NsxFile

from pyNsXStitch.streamers import RESET_TOL_S, ambiguous_window_error, iter_nsx_periods, periods_in_window, \
    window_overlaps

# One file's share of a session period. period is the index of that clock period within the file
NsxPeriodPart = namedtuple('NsxPeriodPart', ['filepath', 'period', 'start_ts', 'end_ts'])

# A clock period across the session. parts are the NsxPeriodParts that make it up, in filename order
SessionPeriod = namedtuple('SessionPeriod', ['start_ts', 'end_ts', 'parts'])


def get_session_nsx_periods(nsx_filepaths, tol_s=RESET_TOL_S):
    """
    Split a session's NsX files into clock periods, counted in filename order.

    Each file is split into periods by iter_nsx_periods. Going through the files in filename order, a file's
    period starts a new session period if it starts more than tol_s seconds before the previous one ended (the
    same rule as within a file). Otherwise it continues the previous session period.

    :param nsx_filepaths: paths of all the session's NsX files of one type (e.g. all its .ns5 files)
    :param tol_s: [optional] {float} how far back (in seconds) data can start and stay in the same period
    :return: list of SessionPeriods in session order
    """
    sessions = []
    prev_end_ts = None
    for nsx_fp in sorted(nsx_filepaths, key=os.path.basename):
        nsx_file = NsxFile(nsx_fp, verbose=False, interactive=False)
        try:
            tol = tol_s * nsx_file.basic_header['TimeStampResolution']
            for file_period, first_ts, end_ts, _, _ in iter_nsx_periods(nsx_file, tol_s=tol_s):
                part = NsxPeriodPart(nsx_fp, file_period, first_ts, end_ts)
                if prev_end_ts is None or first_ts < prev_end_ts - tol:
                    sessions.append(SessionPeriod(first_ts, end_ts, [part]))
                else:
                    sessions[-1].parts.append(part)
                    sessions[-1] = sessions[-1]._replace(start_ts=min(sessions[-1].start_ts, first_ts),
                                                         end_ts=max(sessions[-1].end_ts, end_ts))
                prev_end_ts = end_ts
        finally:
            nsx_file.datafile.close()

    return sessions


def find_nsx_parts_in_range(nsx_filepaths, start_ts=None, end_ts=None, period=None):
    """
    Find the file periods that hold a session's data in the given window.

    :param nsx_filepaths: paths of all the session's NsX files of one type. With period=, this must be the whole
        session (not a subset of its files), since that is what the session period index counts over
    :param start_ts: [optional] start of the window. None is an open bound
    :param end_ts: [optional] end of the window. None is an open bound
    :param period: [optional] session period index (see get_session_nsx_periods, e.g. -1 for the last period). If
        None, the window must match only one session period
    :return: list of NsxPeriodParts that overlap the window, in filename order
    :raises AmbiguousWindowError: If period is None and the window matches more than one session period
    """
    return select_session_parts(get_session_nsx_periods(nsx_filepaths), start_ts, end_ts, period)


def select_session_parts(sessions, start_ts=None, end_ts=None, period=None):
    """Like find_nsx_parts_in_range, but for SessionPeriods already found by get_session_nsx_periods"""
    if period is None:
        matches = periods_in_window(sessions, start_ts, end_ts)
        if len(matches) > 1:
            raise ambiguous_window_error(sessions, matches, start_ts, end_ts, 'this session')
        selected = [sessions[i] for i in matches]
    else:
        try:
            selected = [sessions[period]]
        except IndexError:
            selected = []  # The session doesn't have the requested period

    return [
        part
        for session in selected
        for part in session.parts
        if window_overlaps(part.start_ts, part.end_ts, start_ts, end_ts)
    ]
