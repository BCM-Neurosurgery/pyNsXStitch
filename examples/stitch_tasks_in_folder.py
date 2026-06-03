"""Rough draft (untested) script to stitch all tasks from all NeVs and NsX files in a folder"""


import os
import re

import numpy as np
import pandas as pd

from pyNsXStitch.helpers import load_comments_in_folder, stitch_one_task, find_nsx_in_range, get_all_streamed_files

BASE_SOURCE_DIR = r"Z:\trd\DBSTRD011\NEURAL"
BASE_OUTPUT_DIR = r"D:\Work\DataNet\TestData\temp\for Kat"

AGGRESIVE_STITCH = True

TASK_KEY = '$TASK'
START_KEYS = ['$TASKSTART',]
ID_KEY = '$TASKID'
END_KEYS = ['$TASKSTOP', '$TASKERR', '$TASKERROR', '$TASKKILL']


def select_comment_type(comments, key_list):
    matches = np.zeros_like(comments).astype(bool)
    for key in key_list:
        this_match = task_comments[task_comments['Comment'].str.contains(key)]
        matches = np.logical_or(matches, this_match)
    return comments[matches]

_, all_comments = load_comments_in_folder(BASE_SOURCE_DIR)
all_streamed_files = get_all_streamed_files(BASE_OUTPUT_DIR, full_paths=True)

task_comments = all_comments[all_comments['Comment'].str.contains(TASK_KEY)]
taskid_comments = task_comments[task_comments['Comment'].str.contains(ID_KEY)]

start_comments = select_comment_type(task_comments, START_KEYS)
end_comments = select_comment_type(task_comments, END_KEYS)

for i, task_start in start_comments.iterrows():

    comment = task_start['Comment'].str
    emu_id = re.search(r'(EMU-[0-9]*)', comment).group(1)

    taskid = taskid_comments[taskid_comments['Comment'].str.contains(emu_id)][0]
    task_end = end_comments[taskid_comments['Comment'].str.contains(emu_id)][-1]

    task_name = taskid['Comment']

    start_t = task_start['Timestamp'].str
    end_t = task_end['Timestamp'].str

    # TODO: filter down all the streamed files in the folder to just the ones that intersect this task time range
    filtered_files = all_streamed_files

    output_dir = os.path.join(BASE_OUTPUT_DIR, taskid['Comment'])
    stitch_one_task(filtered_files, output_dir, task_name, start_t, end_t)

