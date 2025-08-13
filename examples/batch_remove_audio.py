import os
import re

from brpylib import NsxFile

from examples.nev_search_test import out_file
from pyNsXStitch.anonymizers import remove_audio_nsx

def recurse_remove_audio(file_path, base_dir=None, out_dir=None):
    """
    Recurse through a directory, and save subset files for all
    :param file_path:
    :return:
    """
    results = {}
    for thing_here in os.listdir(file_path):

        full_path = os.path.join(file_path, thing_here)
        if os.path.isdir(full_path):
            results_inside = recurse_remove_audio(full_path, base_dir=base_dir)
            results[thing_here] = results_inside
        elif re.search('\.ns[1-9]$', thing_here):
            nsx_file = NsxFile(full_path)
            if base_dir and out_dir:
                out_file = os.path.join(out_dir, os.path.relpath(full_path, base_dir))
            else:
                out_file = None
            one_result = remove_audio_nsx(nsx_file, output_filename=out_file)
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

    recurse_remove_audio(args.data_dir, args.data_dir, args.out_dir)