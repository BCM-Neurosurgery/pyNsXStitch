import os
import shutil
import sys
import traceback
import time
import warnings
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from datetime import datetime
import numpy as np
import pandas as pd
from brpylib import NevFile
import xml.etree.ElementTree as xml
from pyNsXStitch.stitchers import StitchedNsXFile, StitchedNeVFile
from pyNsXStitch.helpers import get_all_nev_comments, get_all_streamed_files, get_nev_rec_start, \
    find_nsx_in_range, get_support_files
from pyNsXStitch.streamers import stream_nev_packets


def run_stitch_async(gui):
    try:
        # Overall initialization. Get values from all variables ASAP before they're likely to be changed
        gui.notify(f'Starting stitching process')
        source_dir = gui.source_dir.get()
        output_dir = gui.output_dir.get()
        start = round(gui.start_timestamp.get())
        end = round(gui.end_timestamp.get())
        try:
            os.makedirs(output_dir, exist_ok=True)
        except FileNotFoundError:
            gui.error('Could not find the selected output directory!\n'
                      '  Are you sure it has been selected correctly?\n')
            return

        # Stitch the NeV files first
        gui.notify('Stitching NeV files...')
        gui.update_progressbar(0)
        nev_stitch = StitchedNeVFile(gui.streamed_files['NeV'], start, end)
        with open(gui.get_out_filepath('nev'), 'wb') as nev_out:
            nev_stitch.write(nev_out, gui_updater=gui.update_progressbar)
        gui.update_progressbar(100)
        gui.notify('Stitched NeV file complete')

        # Stitch each of the NsX filetypes
        gui.notify('Beginning NsX stitching...')
        nsx_files = {filetype: files for filetype, files in gui.streamed_files.items() if 'ns' in filetype.lower()}
        for filetype, files in nsx_files.items():
            gui.update_progressbar(0)
            gui.notify(f'Stitching from {len(files)} {filetype} files')
            in_range = find_nsx_in_range(files, start, end)
            gui.notify(f'Found {len(in_range)} files in the selected time range')
            if in_range:
                nsx_start = datetime.now()
                nsx_stitch = StitchedNsXFile(in_range, start, end, aggressive_concat=gui.aggressive_stitch.get())
                with open(gui.get_out_filepath(filetype.lower()), 'wb+') as nsx_out:
                    nsx_stitch.write(nsx_out, gui_updater=gui.update_progressbar)
                elapsed = (datetime.now() - nsx_start)
                gui.notify(f'Finished stitching {filetype} files ({round(elapsed.total_seconds(), 4)} s)')
            else:
                gui.error('Could not find enough files to stitch!')
                continue

        # Copy over all the metadata files
        gui.notify('Copying metadata and helper files...')
        gui.update_progressbar(0)
        non_streamed_files = get_support_files(source_dir)
        n_files = len(non_streamed_files)
        for i, filename in enumerate(non_streamed_files):
            new_name = gui.get_out_filepath(filename.split('.')[-1])
            shutil.copy(
                os.path.join(source_dir, filename),
                os.path.join(output_dir, new_name)
            )
            gui.update_progressbar(100 * (i+1)/n_files)

        gui.notify('Stitching complete. \n')
    except Exception as e:
        gui.disp_error(*sys.exc_info())
    finally:
        gui.update_progressbar(-1)


def load_dir_async(gui):
    """Do the work of loading the NeV files. Can be run asynchronously"""
    try:
        gui.update_progressbar(0)
        gui.notify(f'Loading data in: {gui.source_dir.get()}')

        # With the new version of central, data from multiple NSPs can be in the same folder
        all_streamed_files = get_all_streamed_files(gui.source_dir.get(), full_paths=True)
        all_nsps = list(all_streamed_files.keys())
        if not all_nsps:
            gui.error('No streamed files with NSP information found!')
            return
        elif len(all_nsps) == 1:
            # Only 1 NSP here, so we can move forward
            nsp = all_nsps[0]
            gui.streamed_files = all_streamed_files[nsp]
        else:
            # Found multiple NSPs, ask the user to select
            def select(*args):
                selected.set(True)
                closed.set(True)
                win.destroy()
            def cancel(*args):
                closed.set(True)
                win.destroy()
            gui.notify('Please select an NSP!')
            win = tk.Toplevel(gui.root)
            win.geometry("150x100")
            win.title('NSP Select')
            selected = tk.BooleanVar(gui.root, value=False)
            closed = tk.BooleanVar(gui.root, value=False)
            nsp_var = tk.StringVar(gui.root,)
            tk.Label(master=win, text='Please select an NSP:').pack(side=tk.TOP, anchor=tk.NW)
            tk.OptionMenu(win, nsp_var, *all_nsps).pack(side=tk.TOP)
            buttons = tk.Frame(master=win)
            tk.Button(master=buttons, text='Select', command=select).pack(side=tk.LEFT, anchor=tk.E)
            tk.Button(master=buttons, text='Cancel', command=cancel).pack(side=tk.LEFT, anchor=tk.E)
            buttons.pack(side=tk.TOP)

            # Wait until the little popup window has been closed
            while not closed.get():
                time.sleep(0.1)

            if selected.get():
                # User selected a value
                gui.streamed_files = all_streamed_files[nsp_var.get()]
            else:
                # User pressed cancel
                gui.notify('Aborting comment load...')
                return

        first_nsp = list(gui.streamed_files.keys())[0]
        gui.notify(f'Using comments from {first_nsp}')
        gui.update_patient_id()
        gui.notify(f'Found {len(gui.streamed_files["NeV"])} NeV files')

        # Iter through all the comment packets in all files
        gui.notify(f'Loading comments from NeV...')
        timestamps, comments, file_names = [], [], []
        n_files = len(gui.streamed_files["NeV"])
        for i, file in enumerate(gui.streamed_files["NeV"]):
            nev = NevFile(file)
            gui.update_progressbar((i+1)/n_files*100)
            for (ts, packet_id), raw_data in stream_nev_packets(nev, packet_type=65535):
                timestamps.append(ts)
                text_data = raw_data[6:]
                comment = text_data.decode('ASCII').rstrip('\x00')  # TODO: handle other charsets
                comments.append(comment)
                file_names.append(os.path.basename(file))  # store file name
        gui.update_progressbar(100)
        gui.notify(f'Found {len(timestamps)} comments')

        # Convert to a dataframe for drawing to the GUI
        timestamps = np.array(timestamps)
        first_nev = NevFile(gui.streamed_files['NeV'][0])
        gui.nev_start = get_nev_rec_start(first_nev)
        gui.ts_freq = first_nev.basic_header['TimeStampResolution']
        cleaned_df = pd.DataFrame.from_dict({
            'Timestamp': timestamps,
            'Time Elapsed': np.round((timestamps - gui.nev_start) / gui.ts_freq, 2),
            'Comment': comments,
            'File Name': file_names
        })
        gui.full_comment_df = cleaned_df
        gui.notify('Loading comments to this window... ')
        gui.reset_comments()
        gui.notify(f'Ready for time selection...\n')
        gui.update_progressbar(-1)
    except Exception as e:
        gui.disp_error(*sys.exc_info())
    finally:
        gui.update_progressbar(-1)


class StitcherGUI(object):

    def __init__(self):

        # Top level window elements
        self.root = self.init_window()

        # Variables used for tracking the GUI state
        self.source_dir = tk.StringVar(self.root, value=None)
        self.output_dir = tk.StringVar(self.root, value=None)
        self.search_text = tk.StringVar(self.root, value='')
        self.file_name = tk.StringVar(self.root, value='stitched')
        self.start_time = tk.DoubleVar(master=self.root, value=None)
        self.end_time = tk.DoubleVar(master=self.root, value=None)
        self.start_timestamp = tk.IntVar(master=self.root, value=None)
        self.end_timestamp = tk.IntVar(master=self.root, value=None)
        self.patient_id = tk.StringVar(master=self.root, value=None)
        self.aggressive_stitch = tk.BooleanVar(master=self.root, value=False)

        # Additional important values to keep track of
        self.full_comment_df = self.init_comments()
        self.comment_df = self.init_comments()
        self.streamed_files = None
        self.ts_freq = None
        self.nev_start = None
        self.custom_name = None

        # Additional GUI elements
        self.time_frame = None
        self.comment_frame = None
        self.comment_table = None
        self.console = None
        self.progressbar = None
        self.progress_fill = None
        self.progress_bg = None

        self.build_gui()

        self.notify('Stitcher GUI version 0.1')
        self.notify('Ready')
        self.root.mainloop()

    def init_window(self):
        root = tk.Tk()
        root.title('Manual Time Alignment')
        root.geometry("1200x800")
        tk.Tk.report_callback_exception = self.disp_error
        warnings.showwarning = self.show_warning
        return root

    @staticmethod
    def init_comments():
        """Initialize an empty comment dataframe with just headers"""
        return pd.DataFrame.from_dict({
            'Timestamp': [], 'TimeElapsed': [], 'Comment': [], 'File Name': []
        })

    def build_gui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main_frame = tk.Frame(self.root)
        main_frame.grid(row=0, column=0, sticky='nsew')
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        top_row = self.build_top_row(main_frame)
        top_row.grid(row=0, column=0, padx=10, pady=10, sticky='ew')

        mid_row = self.build_mid_row(main_frame)
        mid_row.grid(row=1, column=0, padx=10, pady=10, sticky='nsew')

        bot_row = self.build_bot_row(main_frame)
        bot_row.grid(row=2, column=0, padx=10, pady=10, sticky='ew')
        
    def build_top_row(self, parent):
        top_row_frame = tk.Frame(parent)
        top_row_frame.columnconfigure(0, weight=1)
        top_row_frame.columnconfigure(1, weight=0)

        source_frame = tk.Frame(top_row_frame)
        self.build_directory_select(source_frame, 'Source Directory', self.source_dir)
        source_frame.grid(row=0, column=0, padx=5, sticky='ew')

        output_frame = tk.Frame(top_row_frame)
        self.build_directory_select(output_frame, 'Output Directory', self.output_dir)
        output_frame.grid(row=1, column=0, padx=5, sticky='ew')

        load_btn = tk.Button(top_row_frame, text='Load', command=self.load_dir, background='Steelblue1')
        load_btn.grid(row=0, column=1, pady=5)

        return top_row_frame

    @staticmethod
    def build_directory_select(parent, label, variable):
        parent.columnconfigure(1, weight=1)

        label = tk.Label(parent, text=label)
        label.grid(row=0, column=0, padx=5, sticky='w')

        entry = tk.Entry(parent, textvariable=variable)
        entry.grid(row=0, column=1, padx=5, sticky='ew')

        browse_btn = tk.Button(parent, text='Browse', command=lambda: variable.set(filedialog.askdirectory()))
        browse_btn.grid(row=0, column=2, padx=5)

    def build_mid_row(self, parent):
        mid_row_frame = tk.Frame(parent)
        mid_row_frame.columnconfigure(0, weight=1)
        mid_row_frame.rowconfigure(0, weight=1)

        paned_window = tk.PanedWindow(mid_row_frame, orient=tk.HORIZONTAL, sashwidth=10, sashrelief=tk.RAISED)
        paned_window.grid(row=0, column=0, sticky='nsew')

        time_select = self.build_time_select(paned_window)
        paned_window.add(time_select, minsize=800)

        info_column = self.build_info_column(paned_window)
        paned_window.add(info_column, minsize=200)

        return mid_row_frame

    def update_patient_id(self):
        patient_id = '--'
        if self.source_dir.get():
            sif_files = [f for f in os.listdir(self.source_dir.get()) if f.endswith('.sif')]
            sif_data = xml.parse(os.path.join(self.source_dir.get(), sif_files[0]))
            patient = sif_data.getroot().findall('Patient/Id')[0].text
            if patient is None:
                patient_id = 'Unavailable'
            else:
                patient_id = patient
        self.patient_id.set(f'Patient ID: {patient_id}')

    def build_info_column(self, parent):
        info_column = tk.Frame(parent)

        # Show the quick summary instructions
        instruction_path = os.path.join(os.path.dirname(__file__), 'GUI_quick_instructions.txt')
        with open(instruction_path, 'r') as f:
            instructions = f.read()
        how_to_label = tk.Label(info_column, text=instructions, justify=tk.LEFT)
        how_to_label.grid(row=0, column=0, padx=5, pady=5, sticky='ew')

        # Show data about the selected patient
        tk.Label(info_column, textvariable=self.patient_id, justify=tk.LEFT).grid(row=1, column=0, padx=5, pady=5, sticky='ew')
        self.update_patient_id()

        return info_column

    def build_time_select(self, parent):
        self.time_frame = tk.Frame(parent)
        self.time_frame.columnconfigure(0, weight=0)
        self.time_frame.columnconfigure(1, weight=1)
        self.time_frame.rowconfigure(0, weight=1)

        inputs = tk.Frame(self.time_frame)

        tk.Label(inputs, text="Comment Search").grid(row=0, column=0, padx=5, sticky='w')
        tk.Entry(inputs, textvariable=self.search_text).grid(row=1, column=0, padx=5, sticky='ew')

        buttons = tk.Frame(inputs)
        tk.Button(buttons, text='Search', command=self.search_comments).pack(side=tk.RIGHT)
        tk.Button(buttons, text='Reset', command=self.reset_comments).pack(side=tk.RIGHT)
        buttons.grid(row=3, column=0, padx=5, sticky='w', pady=(0, 10)) # add padding to bottom only

        tk.Label(inputs, text="Start Time").grid(row=4, column=0, padx=5, sticky='w')
        tk.Entry(inputs, textvariable=self.start_time).grid(row=5, column=0, padx=5, sticky='ew')

        tk.Label(inputs, text="End Time").grid(row=6, column=0, padx=5, sticky='w')
        tk.Entry(inputs, textvariable=self.end_time).grid(row=7, column=0, padx=5, sticky='ew')

        buttons = tk.Frame(inputs)
        tk.Button(buttons, text='Update', command=self.update_tlims).pack(side=tk.RIGHT)
        tk.Button(buttons, text='Reset', command=self.reset_tlims).pack(side=tk.RIGHT)
        buttons.grid(row=8, column=0, padx=5, sticky='w', pady=(0, 10))

        tk.Label(inputs, text="Output Name").grid(row=9, column=0, padx=5, sticky='w')
        tk.Entry(inputs, textvariable=self.file_name).grid(row=10, column=0, padx=5, sticky='ew')

        buttons = tk.Frame(inputs)
        tk.Button(buttons, text='Remember', command=self.set_name).pack(side=tk.RIGHT)
        tk.Button(buttons, text='Reset', command=self.reset_name).pack(side=tk.RIGHT)
        buttons.grid(row=11, column=0, padx=5, sticky='w', pady=(0, 10))

        tk.Label(inputs, text="More Options").grid(row=12, column=0, padx=5, sticky='w')
        tk.Checkbutton(inputs, text='Aggressive Stitch', variable=self.aggressive_stitch).grid(row=13, column=0, padx=5, sticky='w')

        inputs.grid(row=0, column=0, padx=5, pady=5, sticky='nw')

        self.reset_comments()

        return self.time_frame

    def set_name(self):
        self.custom_name = self.file_name.get()
        self.notify('Saved a custom output file name')

    def reset_name(self):
        self.custom_name = None
        self.file_name.set('stitched')
        self.auto_set_name()
        self.notify('Cleared custom name.')

    def auto_set_name(self):
        # Only auto update name if no explicit custom name has been set
        if self.custom_name is not None:
            return

        found_name = 'stitched'
        for idx, row in self.full_comment_df.iterrows():
            row_ts = row['Timestamp']
            if row_ts > self.end_timestamp.get():
                self.warn('No valid TASKID comment found in the time range')
                break  # We're out of the search interval w/o finding a $TASKID. Finish searching
            if row_ts < self.start_timestamp.get():
                continue  # We're before the search interval, move to next comment
            if row['Comment'].startswith('$TASKID'):
                # We found a filename comment. Parse it and finish searching
                found_name = row['Comment'].split(' ')[1]
                break

        self.notify(f'Updating output name')
        self.file_name.set(found_name)

    def get_row_color(self, row_ts):
        if self.start_timestamp.get() == row_ts:
            return 'palegreen'
        elif self.end_timestamp.get() == row_ts:
            return 'lightcoral'
        elif self.start_timestamp.get() < row_ts < self.end_timestamp.get():
            return 'SteelBlue1'
        else:
            return ''

    def build_comment_table(self):
        if self.comment_frame:
            self.comment_frame.destroy()

        self.comment_frame = tk.Frame(self.time_frame)
        self.comment_frame.grid(row=0, column=1, sticky='nsew')
        # self.time_frame.rowconfigure(1, weight=1)
        # self.time_frame.columnconfigure(0, weight=1)

        self.comment_table = ttk.Treeview(self.comment_frame, columns=list(self.comment_df.columns), show='headings')
        for col in self.comment_df.columns:
            self.comment_table.heading(col, text=col)
            self.comment_table.column(col, stretch=True)

        self.comment_table.grid(row=0, column=0, sticky='nsew')
        self.comment_frame.rowconfigure(0, weight=1)
        self.comment_frame.columnconfigure(0, weight=1)

        scrollbar = ttk.Scrollbar(self.comment_frame, orient=tk.VERTICAL, command=self.comment_table.yview)
        self.comment_table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky='ns')

        for idx, row in self.comment_df.iterrows():
            values = [row[col] for col in self.comment_df.columns]
            self.comment_table.insert('', 'end', values=values, tags=(self.get_row_color(row['Timestamp']),))

        self.comment_table.tag_configure('palegreen', background='palegreen')
        self.comment_table.tag_configure('lightcoral', background='lightcoral')
        self.comment_table.tag_configure('SteelBlue1', background='SteelBlue1')

        self.comment_table.bind('<ButtonRelease-1>', self.handle_comment_click)

    def handle_comment_click(self, event):
        region = self.comment_table.identify("region", event.x, event.y)
        if region == "cell":
            row = self.comment_table.identify_row(event.y)
            timestamp = int(self.comment_table.item(row)['values'][0])
            if self.start_timestamp.get() == 0 or timestamp < self.start_timestamp.get():
                self.start_timestamp.set(timestamp)
            else:
                self.end_timestamp.set(timestamp)
            self.update_ts_lims()
            self.recolor_table()

    def recolor_table(self):
        for row_id in self.comment_table.get_children():
            timestamp = int(self.comment_table.item(row_id)['values'][0])
            color = self.get_row_color(timestamp)
            self.comment_table.item(row_id, tags=(color,))

        if self.start_timestamp.get() > self.end_timestamp.get() > 0.0:
            self.error('WARNING: The start timestamp is greater than the end timestamp!\n'
                       '  This will result in no data being selected')

    def update_ts_lims(self):
        """Update the displayed values in the time range entry based on comment selection"""
        ts_lims = np.array([self.start_timestamp.get(), self.end_timestamp.get()])
        time_lims = (ts_lims - self.nev_start) / self.ts_freq
        self.start_time.set(np.round(time_lims[0], 4))
        self.end_time.set(np.round(time_lims[1], 4))

        self.auto_set_name()
        self.recolor_table()

    def update_tlims(self):
        """Find the narrowest pair of timestamps that contain the time limits in seconds"""
        time_lims = np.array([self.start_time.get(), self.end_time.get()])
        approx_ts_lims = (time_lims * self.ts_freq) + self.nev_start
        self.start_timestamp.set(np.floor(approx_ts_lims[0]))
        self.end_timestamp.set(np.ceil(approx_ts_lims[1]))

        self.recolor_table()
        self.auto_set_name()

    def reset_tlims(self):
        self.start_timestamp.set(0)
        self.end_timestamp.set(0)
        self.start_time.set(0.0)
        self.end_time.set(0.0)
        self.recolor_table()

    def search_comments(self):
        """Search for and display only a subset of the comments based on comment text"""
        search_text = self.search_text.get()
        self.notify(f'Searching {len(self.full_comment_df)} comments')
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
        """Build the comment dataframe section of the GUI from scratch"""
        self.build_comment_table()
        self.notify(f'Showing {len(self.comment_df)} matching comments')

    def load_dir(self):
        """Load all the NeV comments into memory, trigger populating the comment frame"""
        thd = threading.Thread(target=load_dir_async, args=(self,))  # timer thread
        thd.daemon = True
        thd.start()

    def update_progressbar(self, progress):
        """Update the progressbar fill to based on the current task progress"""
        if self.progressbar:
            console_width = self.console.winfo_width()
            if progress < 0:
                self.progressbar.itemconfig(self.progress_fill, state='hidden')
            else:
                progress = max(0, min(progress, 100))
                self.progressbar.itemconfig(self.progress_fill, state='normal')
                self.progressbar.coords(self.progress_fill, 0, 0, progress * console_width / 100, 20)
            self.progressbar.coords(self.progress_bg, 0, 0, console_width, 20)
            self.progressbar.update()

    def build_bot_row(self, parent):
        bot_row = tk.Frame(parent)
        bot_row.columnconfigure(0, weight=1)
        bot_row.columnconfigure(1, weight=4)
        bot_row.rowconfigure(0, weight=1)
        bot_row.rowconfigure(1, weight=0)

        console_frame = tk.Frame(bot_row)
        self.console = tk.Text(console_frame, height=12, state='disabled')
        self.console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(console_frame, orient=tk.VERTICAL, command=self.console.yview)
        self.console.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        console_frame.grid(row=0, column=0, padx=5, pady=5, sticky='nsew')

        progressbar_frame = tk.Frame(bot_row)
        progressbar_frame.columnconfigure(0, weight=1)
        self.progressbar = tk.Canvas(progressbar_frame, height=20)
        self.progressbar.grid(row=0, column=0, sticky='ew')
        progressbar_frame.grid(row=1, column=0, padx=5, pady=5, sticky='ew')

        self.progress_bg = self.progressbar.create_rectangle(0, 0, 0, 20, fill='white')
        self.progress_fill = self.progressbar.create_rectangle(0, 0, 0, 20, fill='Steelblue1')

        # Add formatting to the console
        self.console.tag_configure('error', foreground='red')
        self.console.tag_configure('warning', foreground='DarkOrange3')

        # Add the master action buttons
        button_frame = tk.Frame(bot_row)
        stitch_button = tk.Button(button_frame, text='Stitch', background='Steelblue1', command=self.do_stitch)
        stitch_button.pack(padx=5, pady=5)
        reset_button = tk.Button(button_frame, text='Reset', command=self.full_reset)
        reset_button.pack(padx=5, pady=5)
        exit_button = tk.Button(button_frame, text='Exit', background='lightcoral', command=self.close_and_exit)
        exit_button.pack(padx=5, pady=5)
        button_frame.grid(row=0, column=1, padx=5, pady=5, sticky='sw')

        return bot_row

    def write_to_console(self, message, tags=(), pad_newline=True):
        """Universal function for adding text to the log console"""
        if self.console:
            if pad_newline:
                message = f'{message}\n'
            self.console['state'] = 'normal'
            self.console.insert('end', message, tags)
            self.console['state'] = 'disabled'
            self.console.see('end')
        else:
            print(message)

    def notify(self, message):
        """Write a generic non-tagged message to the console"""
        self.write_to_console(message)

    def warn(self, message):
        """Write a generic non-tagged message to the console"""
        self.write_to_console(message, tags=('warning',))

    def disp_error(self, exec, val, tb):
        """Display a caught error with traceback in the console"""
        formatted = traceback.format_exception(exec, val, tb)
        for line in formatted:
            self.write_to_console(line, tags=('error',), pad_newline=False)
        self.notify('Process aborted')

    def show_warning(self, message, category, filename, lineno, file=None, line=None):
        self.write_to_console(message, tags=('warning',))

    def error(self, message):
        """Display a short error message in the console"""
        self.write_to_console(message, tags=('error',))

    def get_out_filepath(self, filetype):
        filename = f'{self.file_name.get()}.{filetype}'
        path = os.path.join(self.output_dir.get(), filename)
        return path

    def do_stitch(self):
        thd = threading.Thread(target=run_stitch_async, args=(self,))  # timer thread
        thd.daemon = True
        thd.start()

    def full_reset(self):
        """Reset all GUI elements and variables to their default values"""
        self.source_dir.set("/")
        self.output_dir.set("/")
        self.reset_tlims()
        self.full_comment_df = self.init_comments()
        self.reset_comments()
        self.notify('Reset complete. Ready to load data \n')

    def close_and_exit(self):
        self.notify('Exiting.')
        exit()


if __name__ == '__main__':
    gui = StitcherGUI()