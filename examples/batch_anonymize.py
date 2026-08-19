import os
import re

from brpylib import NsxFile, NevFile

from pyNsXStitch.anonymizers import nsx_anonymize, nev_anonymize

def make_outpath(full_path, base_dir=None, out_dir=None):
    if base_dir and out_dir:
        out_file = os.path.join(out_dir, os.path.relpath(full_path, base_dir))
        out_dir = os.path.dirname(out_file)
        os.makedirs(out_dir, exist_ok=True)
    else:
        out_file = None
    return out_file

def recurse_anonymize(file_path, base_dir=None, out_dir=None):
    """
    Recurse through a directory, and save subset files for all
    :param file_path:
    :return:
    """
    results = {}
    for thing_here in os.listdir(file_path):

        full_path = os.path.join(file_path, thing_here)
        if os.path.isdir(full_path):
            results_inside = recurse_anonymize(full_path, base_dir=base_dir)
            results[thing_here] = results_inside
        elif re.search(r'\.ns[1-9]$', thing_here):
            nsx_file = NsxFile(full_path)
            out_file = make_outpath(nsx_file, base_dir=base_dir, out_dir=out_dir)
            one_result = nsx_anonymize(nsx_file, output_filename=out_file)
            results[thing_here] = {'status': one_result}
        elif re.search(r'\.nev$', thing_here):
            nev_file = NevFile(full_path)
            out_file = make_outpath(nev_file, base_dir=base_dir, out_dir=out_dir)
            one_result = nev_anonymize(nev_file, output_filename=out_file)
            results[thing_here] = {'status': one_result}
    return results


if __name__ == '__main__':
    import argparse
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('data_dir', type=str,
                            help='Path to search for NsX files to remove audio from')
    arg_parser.add_argument('out_dir', type=str,
                            help='Path to put audio removed files in (preserving directory structure)')
    args = arg_parser.parse_args()

    recurse_anonymize(args.data_dir, args.data_dir, args.out_dir)