"""
Stitch every TOC-mode file in a directory into a single combined output file.
Treats the whole folder as one unit -- it does not detect or split out tasks.

This is a simplified stub. For anything beyond a straight whole-folder merge
(task windows, time ranges, comment-based selection) build your own script on
top of the pyNsXStitch package. Run with --help for invocation details.
"""
import os
import shutil

from pyNsXStitch.stitchers import StitchedNsXFile, StitchedNeVFile
from pyNsXStitch.helpers import get_all_streamed_files


def stitch_whole_folder(source_dir, out_dir, file_name='stitched'):
    """Stitch all NeV/NsX files in source_dir into out_dir/<file_name>.<ext>.

    Non-stitched files in source_dir (metadata, config, helper files) are copied
    across as out_dir/<file_name>.<ext>.
    """
    os.makedirs(out_dir, exist_ok=True)
    copied_files = []

    # For each streamed file type (NeV and NsX) create the matching stitcher and write it out
    all_streamed_files = get_all_streamed_files(source_dir, full_paths=True)
    for nsp_id, streamed_files in all_streamed_files.items():
        for filetype, files in streamed_files.items():
            if filetype == 'NeV':
                combo = StitchedNeVFile(files)
            else:
                combo = StitchedNsXFile(files)

            full_out_path = os.path.join(out_dir, f'{file_name}.{filetype.lower()}')
            with open(full_out_path, 'wb') as f:
                combo.write(f)

            copied_files.extend(os.path.basename(f) for f in files)

    # Copy across anything not stitched: metadata, configuration, and helper files
    leftovers = [f for f in os.listdir(source_dir) if f not in copied_files]
    for filename in leftovers:
        ext = filename.split('.')[-1]
        shutil.copy(
            os.path.join(source_dir, filename),
            os.path.join(out_dir, f'{file_name}.{ext}')
        )


if __name__ == '__main__':
    import argparse
    arg_parser = argparse.ArgumentParser(
        description='Stitch every TOC-mode NeV/NsX file in a directory into a single '
                    'combined output file. Treats the whole folder as one unit; does '
                    'not detect or separate tasks.'
    )
    arg_parser.add_argument('source_dir', type=str,
                            help='Directory containing the TOC-mode recorded files')
    arg_parser.add_argument('out_dir', type=str,
                            help='Directory to write the stitched files to (created if missing)')
    arg_parser.add_argument('--name', type=str, default='stitched',
                            help='Base name for the stitched output files (default: stitched)')
    args = arg_parser.parse_args()

    stitch_whole_folder(args.source_dir, args.out_dir, args.name)