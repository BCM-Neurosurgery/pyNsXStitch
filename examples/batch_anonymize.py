import os
import re

from brpylib import NsxFile, NevFile

from pyNsXStitch.anonymizers import nsx_anonymize, nev_anonymize, clean_filename, clean_dirname
from pyNsXStitch.utils import epoch_start_offset, BRK_DATE_RE, read_time_origin

BRK_FILE_RE = r'\.(nev|ns[1-9])$'


def make_outpath(full_path, base_dir=None, out_dir=None, clean=True, date_offset=None):
    if base_dir and out_dir:
        raw_out_file = os.path.join(out_dir, os.path.relpath(full_path, base_dir))
        out_dir = os.path.dirname(raw_out_file)
        out_name = os.path.basename(raw_out_file)
        if clean:
            out_dir = clean_dirname(out_dir, date_offset)
            out_name = clean_filename(out_name, date_offset)
        out_file = os.path.join(out_dir, out_name)
        os.makedirs(out_dir, exist_ok=True)
    else:
        out_file = None
    return out_file


def anonymize_one_file(file_path, out_file, date_offset=None, audio_channels=None):
    """Anonymize a single .nev or .nsX file, writing the result to out_file."""
    date_offset = epoch_start_offset(find_dates(file_path)) if date_offset is None else date_offset
    if re.search(r'\.ns[1-9]$', file_path):
        return nsx_anonymize(
            NsxFile(file_path),
            output_filename=out_file,
            date_offset=date_offset,
            audio_channels=audio_channels
        )
    elif re.search(r'\.nev$', file_path):
        return nev_anonymize(
            NevFile(file_path),
            output_filename=out_file,
            date_offset=date_offset
        )
    raise ValueError(f'Unsupported file type (expected .nev or .ns1-9): {file_path}')


def find_dates(file_path, fallback_nsx_start=True):
    """Recurse through a directory finding BRK-formatted dates in the filenames"""
    dates_found = []
    for thing_here in os.listdir(file_path):
        full_path = os.path.join(file_path, thing_here)
        if os.path.isdir(full_path):
            dates_found.extend(find_dates(full_path))
        else:
            date_match = re.search(BRK_DATE_RE, thing_here)
            if date_match:
                dates_found.append(date_match.group(1))
            elif fallback_nsx_start:
                if re.search(BRK_FILE_RE, thing_here):
                    file_time_origin = read_time_origin(full_path)
                    dates_found.append(file_time_origin.strftime("%Y%m%d-%H%M%S"))

    unique_dates = list(set(dates_found))
    return unique_dates

def recurse_anonymize(file_path, base_dir=None, out_dir=None, clean_names=True, date_offset=None, audio_channels=None, relative_time=True):
    """
    Recurse through a directory, anonymizing every .nev/.nsX file via anonymize_one_file
    and preserving the directory structure under out_dir.
    """

    if relative_time:
        date_offset = epoch_start_offset(*find_dates(file_path)) if date_offset is None else date_offset
    else:
        print('Ignoring relative file times. All files times will be obfuscated individually')
        date_offset = None

    results = {}
    for thing_here in os.listdir(file_path):

        full_path = os.path.join(file_path, thing_here)
        if os.path.isdir(full_path):
            results[thing_here] = recurse_anonymize(
                full_path,
                base_dir=base_dir,
                out_dir=out_dir,
                clean_names=clean_names,
                date_offset=date_offset,
                audio_channels=audio_channels,
                relative_time=relative_time
            )
        elif re.search(BRK_FILE_RE, thing_here):
            out_file = make_outpath(
                full_path,
                base_dir=base_dir,
                out_dir=out_dir,
                clean=clean_names,
                date_offset=date_offset
            )
            one_result = anonymize_one_file(
                full_path, out_file,
                date_offset=date_offset,
                audio_channels=audio_channels
            )
            results[thing_here] = {'status': one_result}
    return results


if __name__ == '__main__':
    import argparse
    arg_parser = argparse.ArgumentParser(
        description='Anonymize a single NeV/NsX file or recurse through a directory of them'
    )
    arg_parser.add_argument('input_path', type=str,
                            help='Path to a single .nev/.nsX file, or a directory to recurse through')
    arg_parser.add_argument('out_path', type=str,
                            help='Output file (for a single input file) or output directory '
                                 '(for a directory input, preserving structure)')
    arg_parser.add_argument('--keep-paths', action='store_true',
                            help='Do not obfuscate dates in output file/directory names')
    arg_parser.add_argument('--no-relative-time', action='store_true',
                            help='Reset all files to start at 1970-01-01. Destroys time relationship between files but no dependency on file structure.')
    arg_parser.add_argument('--bcm-defaults', action='store_true',
                            help='Use less aggressive audio channel removal based on BCM naming convention')
    args = arg_parser.parse_args()


    if args.bcm_defaults:
        from pyNsXStitch import anonymizers
        anonymizers.DEFAULT_AUDIO_CHAN_FRAG = ["RoomMic"]

    if os.path.isdir(args.input_path):
        recurse_anonymize(
            args.input_path,
            base_dir=args.input_path,
            out_dir=args.out_path,
            clean_names=not args.keep_paths,
            reset_all_times=not args.no_relative_time
        )
    else:
        anonymize_one_file(args.input_path, args.out_path)