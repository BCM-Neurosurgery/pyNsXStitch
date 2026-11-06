"""
Stitch out individual task windows from a set of TOC-mode recordings, driven by a
CSV list of tasks.

Each CSV row names a recording folder, an EMU ID, and a task name. The task's time
window is taken from the span of NeV comments matching that EMU ID, and the stitched
NeV/NsX files are written to their own per-task output folder.

This is a simplified stub -- customise the comment matching / windowing logic by
building your own script on the pyNsXStitch package. Run with --help for details.

CSV format: 3 columns, no header assumptions beyond order --
    1. Date folder  (subfolder of source_dir containing that recording)
    2. EMU ID       (matched against comments as 'EMU-0<id>')
    3. Task Name    (used as the output subfolder and stitched file name)
"""
import os

import pandas as pd

from pyNsXStitch.helpers import load_comments_in_folder, stitch_one_task


def stitch_listed_tasks(source_dir, output_dir, task_csv, aggressive=False):
    """Stitch every task listed in task_csv. See module docstring for the CSV format."""
    tasks = pd.read_csv(task_csv)

    for _, task_data in tasks.iterrows():
        date_folder, emu_id, task_name = task_data.iloc[0], task_data.iloc[1], task_data.iloc[2]

        task_source_dir = os.path.join(source_dir, date_folder)
        streamed_file_list, all_comments = load_comments_in_folder(task_source_dir)

        matched_comments = all_comments[all_comments['Comment'].str.contains(f'EMU-0{emu_id}')]
        start_timestamp = matched_comments['Timestamp'].min()
        end_timestamp = matched_comments['Timestamp'].max()

        task_output_dir = os.path.join(output_dir, task_name)
        stitch_one_task(
            streamed_file_list, task_output_dir, task_name,
            start_timestamp, end_timestamp, aggressive=aggressive
        )


if __name__ == '__main__':
    import argparse
    arg_parser = argparse.ArgumentParser(
        description='Stitch out individual task windows from a set of TOC-mode recordings, '
                    'driven by a CSV list of tasks. Each task window is bounded by matching '
                    'NeV comments and written to its own output folder.'
    )
    arg_parser.add_argument('source_dir', type=str,
                            help='Base directory whose subfolders (named in the CSV) hold the recordings')
    arg_parser.add_argument('output_dir', type=str,
                            help='Base directory to write per-task output folders into')
    arg_parser.add_argument('task_csv', type=str,
                            help='CSV listing tasks: columns "Date folder", "EMU ID", "Task Name"')
    arg_parser.add_argument('--aggressive', action='store_true',
                            help='Merge adjacent packets with no sample gap (fewer packet boundaries)')
    args = arg_parser.parse_args()

    stitch_listed_tasks(args.source_dir, args.output_dir, args.task_csv, aggressive=args.aggressive)