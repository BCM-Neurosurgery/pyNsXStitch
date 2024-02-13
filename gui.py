import tkinter as tk
from tkinter import filedialog

import numpy as np
import pandas as pd
from brpylib import NevFile
from pyNsXStitch.helpers import get_all_nev_comments, get_all_streamed_files, get_nev_rec_start


class StitcherGUI(object):

    def __init__(self):

        # Top level window elements
        self.root = self.init_window()

        # Variables used for tracking the GUI state
        self.source_dir = tk.StringVar(self.root, value=r'D:\Work\DataNet\TestData\sources\blackrock\20240125-144340')
        self.output_dir = tk.StringVar(self.root, value=None)
        self.search_text = tk.StringVar(self.root, value='')
        self.file_name = tk.StringVar(self.root, value='stitched')
        self.start_time = tk.DoubleVar(master=self.root, value=None)
        self.end_time = tk.DoubleVar(master=self.root, value=None)

        # Additional important values to keep track of
        self.full_comment_df = self.init_comments()
        self.comment_df = self.init_comments()
        self.streamed_files = None

        # Additional GUI elements
        self.time_frame = None
        self.comment_frame = None

        self.build_gui()
        self.root.mainloop()

    def init_window(self):
        root = tk.Tk()
        try:
            root.attributes('-zoomed', True)
        except tk.TclError:
            root.state('zoomed')
        root.title('Manual Time Alignment')
        root.geometry("500x500")
        # tk.Tk.report_callback_exception = self.show_error
        return root

    def init_comments(self):
        """Initialize an empty comment dataframe with just headers"""
        return pd.DataFrame.from_dict({
            'Timestamp': [], 'TimeElapsed': [], 'Comment': []
        })

    def build_gui(self):
        """Initialize all the GUI elements and arrange everything"""
        top_row = self.build_top_row()
        top_row.pack(side=tk.TOP)
        mid_row = self.build_mid_row()
        mid_row.pack(side=tk.TOP)
        # bot_row = self.build_bot_row()

    def build_top_row(self):
        top_row_frame = tk.Frame(master=self.root)

        # Build the inputs for loading the source data in
        source_frame = tk.Frame(master=top_row_frame)
        self.build_directory_select(source_frame, 'Source Directory', self.source_dir)
        load_btn = tk.Button(master=source_frame, text='Load', width=20, command=self.load_dir)
        load_btn.pack(side=tk.LEFT)
        source_frame.pack(side=tk.TOP, anchor=tk.W)

        # Build the inputs for selecting the output directory
        output_frame = tk.Frame(master=top_row_frame)
        self.build_directory_select(output_frame, 'Output Directory', self.output_dir)
        output_frame.pack(side=tk.TOP, anchor=tk.W)

        return top_row_frame

    @staticmethod
    def build_directory_select(parent, label, variable, label_width=20, button_width=15, box_width=100):
        """Build a little widget to select a directory on the filesystem"""
        def browse_cmd():
            selected = filedialog.askdirectory(initialdir="/", mustexist=True)
            variable.set(selected)

        source_label = tk.Label(master=parent, text=label, width=label_width)
        source_label.pack(side=tk.LEFT)
        source_in_box = tk.Entry(master=parent, textvariable=variable, width=box_width)
        source_in_box.pack(side=tk.LEFT)
        browse = tk.Button(master=parent, text='Browse', width=button_width, command=browse_cmd)
        browse.pack(side=tk.LEFT)

    def build_mid_row(self):
        middle_row = tk.Frame(master=self.root)

        time_select = self.build_time_select(middle_row)
        time_select.pack(side=tk.LEFT, anchor=tk.N)
        # info_column = self.build_info_column(middle_row)
        # info_column.pack(side=tk.LEFT, anchor=tk.N)

        return middle_row

    def build_time_select(self, parent):
        """Build the section of the GUI that helps with selecting the time limits of the NsX Stitching"""
        self.time_frame = tk.Frame(master=parent)

        # Build all the controls on the left side of the time select frame
        inputs = tk.Frame(master=self.time_frame, width=50)
        tk.Label(master=inputs, text="Comment Search", ).pack(side=tk.TOP, anchor=tk.W, pady=(20, 0))
        tk.Entry(master=inputs, textvariable=self.search_text).pack(side=tk.TOP)
        buttons = tk.Frame(master=inputs)
        tk.Button(master=buttons, text='Search', command=self.search_comments).pack(side=tk.RIGHT, anchor=tk.N)
        tk.Button(master=buttons, text='Reset', command=self.reset_comments).pack(side=tk.RIGHT, anchor=tk.N)
        buttons.pack(side=tk.TOP, anchor=tk.E)

        tk.Label(master=inputs, text="Start Time").pack(side=tk.TOP, anchor=tk.W, pady=(20, 0))
        tk.Entry(master=inputs, textvariable=self.start_time).pack(side=tk.TOP)
        tk.Label(master=inputs, text="End Time").pack(side=tk.TOP, anchor=tk.W)
        tk.Entry(master=inputs, textvariable=self.start_time).pack(side=tk.TOP)
        buttons = tk.Frame(master=inputs)
        tk.Button(master=buttons, text='Update', command=self.update_tlims).pack(side=tk.RIGHT, anchor=tk.N)
        tk.Button(master=buttons, text='Reset', command=self.reset_tlims).pack(side=tk.RIGHT, anchor=tk.N)
        buttons.pack(side=tk.TOP, anchor=tk.E)

        tk.Label(master=inputs, text="Output Name").pack(side=tk.TOP, anchor=tk.W, pady=(20, 0))
        tk.Entry(master=inputs, textvariable=self.file_name).pack(side=tk.TOP)

        inputs.pack(side=tk.LEFT, anchor=tk.N)

        self.reset_comments()

        return self.time_frame

    def build_comment_table(self):
        table_frame = tk.Frame(master=self.comment_frame)
        col_widths = [15, 15, 30]
        # Build the headers:
        header = tk.Frame(master=table_frame)
        for i, col in enumerate(self.comment_df.columns):
            tk.Label(header, text=col, width=col_widths[i]).pack(side=tk.LEFT)
        header.pack(side=tk.TOP, anchor=tk.W)

        # For each entry in the comments table, add an entry, and build the appropriate selectors
        for i, row_data in enumerate(self.comment_df.iterrows()):
            row_frame = tk.Frame(master=table_frame)
            for j, value in enumerate(row_data[1]):
                text = self.comment_df.iloc[i, j]
                tk.Label(master=row_frame, text=text, width=col_widths[j]).pack(side=tk.LEFT, anchor=tk.W)
            row_frame.pack(side=tk.TOP, anchor=tk.W)
        table_frame.pack(side=tk.LEFT)

    def update_tlims(self):
        pass

    def reset_tlims(self):
        pass

    def search_comments(self):
        # TODO: implement the search over self.full_comment_df and put result into self.comment_df
        self.build_comment_table()

    def reset_comments(self):
        self.comment_df = self.full_comment_df

        if self.comment_frame:
            self.comment_frame.destroy()

        self.comment_frame = tk.Frame(master=self.time_frame, padx=10, height=300, borderwidth=1)
        self.scroll = tk.Scrollbar(self.comment_frame, orient=tk.VERTICAL)
        self.scroll.pack(side=tk.RIGHT, fill='y')
        self.build_comment_table()

        self.comment_frame.pack(side=tk.LEFT, anchor=tk.N)

    def load_dir(self):
        """Load all the NeV comments into memory, trigger populating the comment frame"""
        self.streamed_files = get_all_streamed_files(self.source_dir.get(), full_paths=True)
        raw_df = get_all_nev_comments(self.streamed_files['NeV'])
        first_nev = NevFile(self.streamed_files['NeV'][0])
        nev_start = get_nev_rec_start(first_nev)
        ts_freq = first_nev.basic_header['TimeStampResolution']
        cleaned_df = pd.DataFrame.from_dict({
            'Timestamp': raw_df['TimeStamps'],
            'Time Elapsed': np.round((raw_df['TimeStamps'] - nev_start) / ts_freq, 2),
            'Comment': raw_df['Data']
        })
        self.full_comment_df = cleaned_df
        self.reset_comments()


if __name__ == '__main__':
    gui = StitcherGUI()
