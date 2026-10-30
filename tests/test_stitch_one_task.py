"""
End-to-end test of helpers.stitch_one_task on a session where the NSP clock was reset.

The session is two recording chunks written as real NeV and NsX files (read back with brpylib):

    chunk 001: period 0 (ticks 30000..330000), then the clock resets and period 1 starts (ticks 3000..303000)
    chunk 002: period 1 carries on (ticks 303000..603000)

Every sample and NeV packet carries a marker for the period it was recorded in, so the stitched output can be
checked for data from the wrong period.
"""

import os
import warnings
from struct import pack

import numpy as np
import pytest
from brpylib import NevFile, NsxFile

from pyNsXStitch import AmbiguousWindowError, get_all_streamed_files, stitch_one_task
from pyNsXStitch.streamers import iter_nsx_timestamps, stream_nev_packets, stream_nsx_data

TS_RES = 30000  # Ticks per second
NEV_PACKET_SIZE = 32
COMMENT_PACKET_ID = 65535
NSX_PERIODS = {'ns5': 30, 'ns3': 60}  # NsX sample period in ticks (1 kHz and 500 Hz)
N_CHANNELS = 2

# (chunk, period, first tick, seconds of data)
STRETCHES = [
    ('001', 0, 30000, 10),
    ('001', 1, 3000, 10),
    ('002', 1, 303000, 10),
]
PERIOD_TICKS = {0: (30000, 330000), 1: (3000, 603000)}

# Overlaps both clock periods, and period 1's part of it spans both chunks
START, END = 250000, 400000


def time_origin():
    return pack('<8H', 2024, 1, 1, 1, 12, 0, 0, 0)


def write_nev(path, stretches):
    header = b'BREVENTS' + pack('<2BHIIII', 3, 0, 0, 336, NEV_PACKET_SIZE, TS_RES, TS_RES) + time_origin()
    header += b'test'.ljust(32, b'\x00') + b''.ljust(256, b'\x00') + pack('<I', 0)
    assert len(header) == 336
    with open(path, 'wb') as f:
        f.write(header)
        for _, period, first_ts, seconds in stretches:
            for ts in range(first_ts, first_ts + seconds * TS_RES + 1, 3000):
                f.write(pack('<QH', ts, COMMENT_PACKET_ID) + bytes([period]).ljust(NEV_PACKET_SIZE - 10, b'\x00'))


def write_nsx(path, stretches, sample_period):
    header = b'BRSMPGRP' + pack('<2BI', 3, 0, 314 + 66 * N_CHANNELS) + b'test'.ljust(16, b'\x00')
    header += b''.ljust(256, b'\x00') + pack('<II', sample_period, TS_RES) + time_origin() + pack('<I', N_CHANNELS)
    for ch in range(N_CHANNELS):
        header += pack('<2sH16sBBhhhh16sIIHIIH', b'CC', ch + 1, f'ch{ch + 1}'.encode(), 0, 0,
                       -32768, 32767, -8191, 8191, b'uV', 0, 0, 0, 0, 0, 0)
    pts_per_packet = TS_RES // sample_period  # One packet per second
    with open(path, 'wb') as f:
        f.write(header)
        for _, period, first_ts, seconds in stretches:
            for s in range(seconds):
                data = np.zeros((pts_per_packet, N_CHANNELS), dtype=np.int16)
                data[:, 0] = period
                data[:, 1] = np.arange(pts_per_packet) + s * pts_per_packet
                f.write(b'\x01' + pack('<QI', first_ts + s * TS_RES, pts_per_packet) + data.tobytes())


@pytest.fixture
def session(tmp_path):
    src = tmp_path / 'session'
    src.mkdir()
    for chunk in sorted({c for c, *_ in STRETCHES}):
        stretches = [s for s in STRETCHES if s[0] == chunk]
        base = src / f'NSP1-20240101-120000-{chunk}'
        write_nev(f'{base}.nev', stretches)
        for ext, sample_period in NSX_PERIODS.items():
            write_nsx(f'{base}.{ext}', stretches, sample_period)
    return get_all_streamed_files(str(src), full_paths=True)['NSP1']


def stitch(session, out_dir, period):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')  # The estimated TimeOrigin warning for a period that starts mid-file
        stitch_one_task(session, str(out_dir), 'task', START, END, period=period)


def read_nev(path):
    nev = NevFile(path, verbose=False, interactive=False)
    try:
        return [(int(ts), packet[0]) for (ts, _), packet in stream_nev_packets(nev)]
    finally:
        nev.datafile.close()


def read_nsx(path):
    nsx = NsxFile(path, verbose=False, interactive=False)
    try:
        packet_ts = [ts for ts, n in iter_nsx_timestamps(nsx) if n]
        data = np.concatenate([np.array(block) for _, block in stream_nsx_data(nsx)])
        return packet_ts, data
    finally:
        nsx.datafile.close()


def test_ambiguous_window_needs_a_period(session, tmp_path):
    out_dir = tmp_path / 'out'
    with pytest.raises(AmbiguousWindowError):
        stitch(session, out_dir, period=None)
    assert not out_dir.exists()  # Nothing is written before the window is resolved


@pytest.mark.parametrize('period', [0, 1, -1])
def test_stitched_files_hold_one_period(session, tmp_path, period):
    expected = period % len(PERIOD_TICKS)
    lo, hi = max(START, PERIOD_TICKS[expected][0]), min(END, PERIOD_TICKS[expected][1])
    out_dir = tmp_path / 'out'
    stitch(session, out_dir, period)

    nev_packets = read_nev(os.path.join(out_dir, 'task.nev'))
    assert nev_packets
    timestamps = [ts for ts, _ in nev_packets]
    assert all(a <= b for a, b in zip(timestamps, timestamps[1:])), 'stitched NeV goes backwards in time'
    assert {marker for _, marker in nev_packets} == {expected}
    assert lo <= timestamps[0] and timestamps[-1] <= hi

    for ext, sample_period in NSX_PERIODS.items():
        packet_ts, data = read_nsx(os.path.join(out_dir, f'task.{ext}'))
        assert all(a < b for a, b in zip(packet_ts, packet_ts[1:])), f'stitched {ext} goes backwards in time'
        assert lo <= packet_ts[0] and packet_ts[-1] <= hi
        assert set(np.unique(data[:, 0])) == {expected}, f'stitched {ext} mixes clock periods'
        # Every sample of the period in the window, and nothing else
        sample_ts = [first_ts + i * sample_period
                     for _, p, first_ts, seconds in STRETCHES if p == expected
                     for i in range(seconds * TS_RES // sample_period)]
        assert len(data) == sum(START <= ts <= END for ts in sample_ts)
