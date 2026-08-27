import os
import re

from brpylib import NsxFile, NevFile

from pyNsXStitch.anonymizers import nsx_anonymize, nev_anonymize, clean_filename, clean_dirname, random_date_offset

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


def anonymize_one_file(file_path, out_file, date_offset=None):
    """Anonymize a single .nev or .nsX file, writing the result to out_file."""
    date_offset = random_date_offset() if date_offset is None else date_offset
    if re.search(r'\.ns[1-9]$', file_path):
        return nsx_anonymize(NsxFile(file_path), output_filename=out_file, date_offset=date_offset)
    elif re.search(r'\.nev$', file_path):
        return nev_anonymize(NevFile(file_path), output_filename=out_file, date_offset=date_offset)
    raise ValueError(f'Unsupported file type (expected .nev or .ns1-9): {file_path}')


def recurse_anonymize(file_path, base_dir=None, out_dir=None, clean_names=True, date_offset=None):
    """
    Recurse through a directory, anonymizing every .nev/.nsX file via anonymize_one_file
    and preserving the directory structure under out_dir.
    """

    date_offset = random_date_offset() if date_offset is None else date_offset

    results = {}
    for thing_here in os.listdir(file_path):

        full_path = os.path.join(file_path, thing_here)
        if os.path.isdir(full_path):
            results[thing_here] = recurse_anonymize(
                full_path,
                base_dir=base_dir,
                out_dir=out_dir,
                clean_names=clean_names,
                date_offset=date_offset
            )
        elif re.search(BRK_FILE_RE, thing_here):
            out_file = make_outpath(
                full_path,
                base_dir=base_dir,
                out_dir=out_dir,
                clean=clean_names,
                date_offset=date_offset
            )
            one_result = anonymize_one_file(full_path, out_file, date_offset=date_offset)
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
    arg_parser.add_argument('--keep-names', action='store_true',
                            help='Do not scramble dates in output file/directory names')
    args = arg_parser.parse_args()

    if os.path.isdir(args.input_path):
        recurse_anonymize(
            args.input_path,
            base_dir=args.input_path,
            out_dir=args.out_path,
            clean_names=not args.keep_names,
        )
    else:
        anonymize_one_file(args.input_path, args.out_path)