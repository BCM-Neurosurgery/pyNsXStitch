"""
Compare an anonymized Blackrock file against its original and check that
anonymization changed only what it should:

  - the basic-header TimeOrigin MUST differ
  - packet timestamps (NSP clock ticks) MUST be unchanged
  - sample data for the retained channels MUST be byte-for-byte identical
  - the anonymized channel set MUST be a subset of the original (audio dropped),
    in the same order, with identical extended headers for the retained channels

Usage:
    python examples/check_anonymized.py ORIGINAL.ns3 ANONYMIZED.ns3
    python examples/check_anonymized.py ORIGINAL.nev ANONYMIZED.nev
"""
import sys
import hashlib

import numpy as np
from brpylib import NsxFile, NevFile

from pyNsXStitch.streamers import stream_nsx_data, stream_nev_packets, iter_nsx_timestamps

# Header fields that anonymization is allowed to change
NSX_EXPECTED_DIFFS = {'TimeOrigin', 'ChannelCount', 'BytesInHeader'}
NEV_EXPECTED_DIFFS = {'TimeOrigin'}


def _hash_stream(chunks):
    """sha256 over an iterable of bytes-like chunks."""
    h = hashlib.sha256()
    for chunk in chunks:
        h.update(chunk)
    return h.hexdigest()


def _diff_headers(orig, anon):
    """Return {key: (orig_value, anon_value)} for every basic-header field that differs."""
    diffs = {}
    for key in sorted(set(orig) | set(anon)):
        o, a = orig.get(key, '<missing>'), anon.get(key, '<missing>')
        if not np.array_equal(o, a):
            diffs[key] = (o, a)
    return diffs


def check_nsx(orig_path, anon_path):
    orig, anon = NsxFile(orig_path), NsxFile(anon_path)
    results = []

    # --- basic header ---
    header_diffs = _diff_headers(orig.basic_header, anon.basic_header)
    print('Basic header:')
    for key, (o, a) in header_diffs.items():
        tag = '' if key in NSX_EXPECTED_DIFFS else '  [UNEXPECTED]'
        print(f'  {key}: {o!r} -> {a!r}{tag}')
    if not header_diffs:
        print('  (no differences)')
    unexpected = set(header_diffs) - NSX_EXPECTED_DIFFS
    results.append(('TimeOrigin changed', 'TimeOrigin' in header_diffs))
    results.append(('no unexpected header changes', not unexpected))

    # --- channels ---
    orig_labels = [e['ElectrodeLabel'] for e in orig.extended_headers]
    anon_labels = [e['ElectrodeLabel'] for e in anon.extended_headers]
    keep_cols = [i for i, lbl in enumerate(orig_labels) if lbl in set(anon_labels)]
    dropped = [lbl for lbl in orig_labels if lbl not in set(anon_labels)]

    print('\nChannels:')
    print(f'  original  : {len(orig_labels)}')
    print(f'  anonymized: {len(anon_labels)}')
    print(f'  dropped   : {dropped}')

    order_ok = [orig_labels[i] for i in keep_cols] == anon_labels
    ext_ok = order_ok and all(
        orig.extended_headers[i] == anon.extended_headers[j]
        for j, i in enumerate(keep_cols)
    )
    print(f'  retained channels same order  : {order_ok}')
    print(f'  retained extended headers same: {ext_ok}')
    results.append(('anonymized channels are a subset', len(anon_labels) == len(keep_cols)))
    results.append(('retained channel headers identical', ext_ok))

    # --- packet timestamps (header-only scan) ---
    orig_ts = list(iter_nsx_timestamps(orig))
    anon_ts = list(iter_nsx_timestamps(anon))
    ts_ok = orig_ts == anon_ts
    print('\nPacket timestamps:')
    print(f'  packets: original={len(orig_ts)}  anonymized={len(anon_ts)}')
    print(f'  timestamps + packet sizes identical: {ts_ok}')
    results.append(('packet timestamps unchanged', ts_ok))

    # --- sample data for retained channels ---
    orig_hash = _hash_stream(
        np.ascontiguousarray(block[:, keep_cols]).tobytes()
        for _, block in stream_nsx_data(orig)
    )
    anon_hash = _hash_stream(
        np.ascontiguousarray(block).tobytes()
        for _, block in stream_nsx_data(anon)
    )
    print('\nSample data (retained channels):')
    print(f'  sha256 original  : {orig_hash}')
    print(f'  sha256 anonymized: {anon_hash}')
    data_ok = orig_hash == anon_hash
    print(f'  identical: {data_ok}')
    results.append(('retained sample data unchanged', data_ok))

    return orig, anon, results


def check_nev(orig_path, anon_path):
    orig, anon = NevFile(orig_path), NevFile(anon_path)
    results = []

    header_diffs = _diff_headers(orig.basic_header, anon.basic_header)
    print('Basic header:')
    for key, (o, a) in header_diffs.items():
        tag = '' if key in NEV_EXPECTED_DIFFS else '  [UNEXPECTED]'
        print(f'  {key}: {o!r} -> {a!r}{tag}')
    if not header_diffs:
        print('  (no differences)')
    unexpected = set(header_diffs) - NEV_EXPECTED_DIFFS
    results.append(('TimeOrigin changed', 'TimeOrigin' in header_diffs))
    results.append(('no unexpected header changes', not unexpected))

    orig_packets = list(stream_nev_packets(orig))
    anon_packets = list(stream_nev_packets(anon))
    print('\nData packets:')
    print(f'  packets: original={len(orig_packets)}  anonymized={len(anon_packets)}')

    orig_meta = [m for m, _ in orig_packets]
    anon_meta = [m for m, _ in anon_packets]
    meta_ok = orig_meta == anon_meta
    payload_ok = _hash_stream(d for _, d in orig_packets) == _hash_stream(d for _, d in anon_packets)
    print(f'  (timestamp, packet_id) sequence identical: {meta_ok}')
    print(f'  payload bytes identical: {payload_ok}')
    results.append(('packet timestamps + ids unchanged', meta_ok))
    results.append(('packet payloads unchanged', payload_ok))

    return orig, anon, results


def run(orig_path, anon_path):
    """Run the comparison and return (orig_file, anon_file, all_ok). Both files stay open."""
    print(f'=== ORIGINAL: {orig_path}\n=== ANONYMIZED: {anon_path}\n')
    if orig_path.lower().endswith('.nev'):
        orig, anon, results = check_nev(orig_path, anon_path)
    else:
        orig, anon, results = check_nsx(orig_path, anon_path)

    print('\nVERDICT:')
    all_ok = True
    for label, ok in results:
        print(f'  [{"PASS" if ok else "FAIL"}] {label}')
        all_ok &= ok
    return orig, anon, all_ok


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)

    # `orig` and `anon` are left open in module scope below so you can set a
    # breakpoint on the `pass` line and inspect both files in memory.
    orig, anon, all_ok = run(sys.argv[1], sys.argv[2])

    pass  # <-- breakpoint here: inspect `orig` / `anon` (basic_header, extended_headers, ...)

    sys.exit(0 if all_ok else 1)