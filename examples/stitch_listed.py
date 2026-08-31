import os
import pandas as pd

from pyNsXStitch.helpers import load_comments_in_folder, stitch_one_task

# Directory which contains one or more TOC-mode recordings to stitch data from
BASE_SOURCE_DIR = r"/path/to/source/data"

# Directory into which to output the stitched files
BASE_OUTPUT_DIR = r"/output/destination"

# Path to a csv with a list of tasks to stitch. The csv must have 3 columns: Date folder, EMU ID,  Task Name
TASK_LIST_CSV = r'/path/to/csv/with/task/list'

AGGRESIVE_STITCH = True

tasks = pd.read_csv(TASK_LIST_CSV)

for i, task_data in tasks.iterrows():

    source_dir = os.path.join(BASE_SOURCE_DIR, task_data.iloc[0])
    streamed_file_list, all_comments = load_comments_in_folder(source_dir)

    matched_comments = all_comments[all_comments['Comment'].str.contains(f'EMU-0{task_data.iloc[1]}')]
    start_timestamp = matched_comments['Timestamp'].min()
    end_timestamp = matched_comments['Timestamp'].max()

    output_dir = os.path.join(BASE_OUTPUT_DIR, task_data.iloc[2])
    stitch_one_task(streamed_file_list, output_dir, task_data.iloc[2], start_timestamp, end_timestamp)





