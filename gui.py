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
        self.start_timestamp = tk.IntVar(master=self.root, value=None)
        self.end_timestamp = tk.IntVar(master=self.root, value=None)

        # Additional important values to keep track of
        self.full_comment_df = self.init_comments()
        self.comment_df = self.init_comments()
        self.streamed_files = None
        self.ts_freq = None
        self.nev_start = None

        # Additional GUI elements
        self.time_frame = None
        self.comment_frame = None
        self.table_elements = []
        self.table_area = None

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
        top_row.pack(side=tk.TOP, anchor=tk.W)
        mid_row = self.build_mid_row()
        mid_row.pack(side=tk.TOP, anchor=tk.W)
        bot_row = self.build_bot_row()
        mid_row.pack(side=tk.TOP, anchor=tk.W)

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
        middle_row = tk.Frame(master=self.root, pady=20)

        time_select = self.build_time_select(middle_row)
        time_select.pack(side=tk.LEFT, anchor=tk.N,)
        # info_column = self.build_info_column(middle_row)
        # info_column.pack(side=tk.LEFT, anchor=tk.N)

        return middle_row

    def build_time_select(self, parent):
        """Build the section of the GUI that helps with selecting the time limits of the NsX Stitching"""
        self.time_frame = tk.Frame(master=parent)

        # Build all the controls on the left side of the time select frame
        inputs = tk.Frame(master=self.time_frame, width=50, padx=10)
        tk.Label(master=inputs, text="Comment Search", ).pack(side=tk.TOP, anchor=tk.W, pady=(20, 0))
        tk.Entry(master=inputs, textvariable=self.search_text).pack(side=tk.TOP)
        buttons = tk.Frame(master=inputs)
        tk.Button(master=buttons, text='Search', command=self.search_comments).pack(side=tk.RIGHT, anchor=tk.N)
        tk.Button(master=buttons, text='Reset', command=self.reset_comments).pack(side=tk.RIGHT, anchor=tk.N)
        buttons.pack(side=tk.TOP, anchor=tk.E)

        tk.Label(master=inputs, text="Start Time").pack(side=tk.TOP, anchor=tk.W, pady=(20, 0))
        tk.Entry(master=inputs, textvariable=self.start_time).pack(side=tk.TOP)
        tk.Label(master=inputs, text="End Time").pack(side=tk.TOP, anchor=tk.W)
        tk.Entry(master=inputs, textvariable=self.end_time).pack(side=tk.TOP)
        buttons = tk.Frame(master=inputs)
        tk.Button(master=buttons, text='Update', command=self.update_tlims).pack(side=tk.RIGHT, anchor=tk.N)
        tk.Button(master=buttons, text='Reset', command=self.reset_tlims).pack(side=tk.RIGHT, anchor=tk.N)
        buttons.pack(side=tk.TOP, anchor=tk.E)

        tk.Label(master=inputs, text="Output Name").pack(side=tk.TOP, anchor=tk.W, pady=(20, 0))
        tk.Entry(master=inputs, textvariable=self.file_name).pack(side=tk.TOP)

        inputs.pack(side=tk.LEFT, anchor=tk.N)

        self.reset_comments()

        return self.time_frame

    def get_row_color(self, row_idx, row_ts):
        row_color = ['gray85', 'gray90'][row_idx % 2]
        if self.start_timestamp.get() == row_ts:
            row_color = 'palegreen'
        elif self.end_timestamp.get() == row_ts:
            row_color = 'lightcoral'
        elif self.start_timestamp.get() < row_ts < self.end_timestamp.get():
            row_color = ['SkyBlue1', 'SteelBlue1'][row_idx % 2]
        return row_color

    def build_comment_table(self):

        col_widths = [100, 100, 250, 30, 30]
        col_starts = [10, 110, 210, 460, 490]
        col_height = 25
        y_offset = 10
        bttn_offset = 7
        canvas_width = sum(col_widths)
        canvas_height = col_height * (1+len(self.comment_df))

        self.table_area = tk.Canvas(
            self.comment_frame,
            scrollregion=(0, 0, canvas_width, canvas_height),
            width=canvas_width, height=500,
            yscrollcommand=self.scroll.set
        )

        # Build the headers:
        for i, col in enumerate(self.comment_df.columns):
            self.table_area.create_text(col_starts[i], y_offset,  text=col, width=col_widths[i], anchor=tk.NW)
        self.table_area.create_text(
            col_starts[3]-15, y_offset,
            text=r'Start\Stop',
            width=sum(col_widths[3:]),
            anchor=tk.NW)

        # For each entry in the comments table, add an entry, and build the appropriate selectors
        for i, row_data in enumerate(self.comment_df.iterrows()):
            row_items = []
            row_ts = row_data[1]['Timestamp']
            row_color = self.get_row_color(i, row_ts)
            row_yloc = y_offset + col_height * (1+i)

            bg_rectange = self.table_area.create_rectangle(
                0, row_yloc-5, canvas_width, row_yloc+col_height-5, fill=row_color, outline=''
            )
            row_items.append(bg_rectange)

            for j, value in enumerate(row_data[1]):
                text = self.comment_df.iloc[i, j]
                self.table_area.create_text(col_starts[j], row_yloc,  text=text, width=col_widths[j], anchor=tk.NW)

            buttn_y = row_yloc + bttn_offset
            start = tk.Radiobutton(
                self.table_area,
                variable=self.start_timestamp,
                value=row_ts,
                command=self.update_ts_lims,
                background=row_color
            )
            self.table_area.create_window(col_starts[3], buttn_y, window=start)
            stop = tk.Radiobutton(
                self.table_area,
                variable=self.end_timestamp,
                value=row_ts,
                command=self.update_ts_lims,
                background=row_color
            )
            self.table_area.create_window(col_starts[4], buttn_y, window=stop)
            row_items.append(start)
            row_items.append(stop)
            self.table_elements.append(row_items)
        self.table_area.pack(side=tk.LEFT)
        self.scroll.config(command=self.table_area.yview)

    def recolor_table(self):
        for rox_idx, row_elements in enumerate(self.table_elements):
            row_ts = self.comment_df.iloc[rox_idx, 0]
            row_color = self.get_row_color(rox_idx, row_ts)
            self.table_area.itemconfigure(row_elements[0], fill=row_color)
            for button in row_elements[1:]:
                button.configure(background=row_color)

    def update_ts_lims(self):
        """Update the displayed values in the time range entry based on comment selection"""
        ts_lims = np.array([self.start_timestamp.get(), self.end_timestamp.get()])
        time_lims = (ts_lims - self.nev_start) / self.ts_freq
        self.start_time.set(np.round(time_lims[0], 4))
        self.end_time.set(np.round(time_lims[1], 4))
        self.recolor_table()

    def update_tlims(self):
        """Find the narrowest pair of timestamps that contain the time limits in seconds"""
        time_lims = np.array([self.start_time.get(), self.end_time.get()])
        approx_ts_lims = (time_lims * self.ts_freq) + self.nev_start
        self.start_timestamp.set(np.floor(approx_ts_lims[0]))
        self.end_timestamp.set(np.ceil(approx_ts_lims[1]))

        self.recolor_table()

    def reset_tlims(self):
        self.start_timestamp.set(0)
        self.end_timestamp.set(0)
        self.start_time.set(0.0)
        self.end_time.set(0.0)
        self.recolor_table()

    def search_comments(self):
        search_text = self.search_text.get()
        have_match = np.array([
            search_text in comment
            for comment in self.full_comment_df['Comment']
        ])
        self.comment_df = self.full_comment_df.iloc[have_match, :]
        self.rebuild_comments()

    def reset_comments(self):
        self.comment_df = self.full_comment_df
        self.rebuild_comments()

    def rebuild_comments(self):
        if self.comment_frame:
            self.table_elements = []
            self.comment_frame.destroy()

        self.comment_frame = tk.Frame(master=self.time_frame, pady=10, padx=20, height=300, borderwidth=1)
        self.scroll = tk.Scrollbar(self.comment_frame, orient=tk.VERTICAL)
        self.scroll.pack(side=tk.RIGHT, fill='y')
        self.build_comment_table()

        self.comment_frame.pack(side=tk.LEFT, anchor=tk.N)

    def load_dir(self):
        """Load all the NeV comments into memory, trigger populating the comment frame"""
        self.streamed_files = get_all_streamed_files(self.source_dir.get(), full_paths=True)
        raw_df = get_all_nev_comments(self.streamed_files['NeV'])
        first_nev = NevFile(self.streamed_files['NeV'][0])
        self.nev_start = get_nev_rec_start(first_nev)
        self.ts_freq = first_nev.basic_header['TimeStampResolution']
        cleaned_df = pd.DataFrame.from_dict({
            'Timestamp': raw_df['TimeStamps'],
            'Time Elapsed': np.round((raw_df['TimeStamps'] - self.nev_start) / self.ts_freq, 2),
            'Comment': raw_df['Data']
        })
        self.full_comment_df = cleaned_df
        self.reset_comments()

    def build_bot_row(self):
        pass


if __name__ == '__main__':
    gui = StitcherGUI()
