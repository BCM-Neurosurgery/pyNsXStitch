## Usage Instructions:
1. Select the directory that contains the TOC mode recording data you would like to stitch as the `Source Directory`.
2. Select the directory you would like to write the stitched data into as the `Output Directory`
3. Press the `Load` button to load all comments from all NeV files in the selected source directory
4. Select a start and end time for the epoch you would like to stitch. This can be accomplished in several ways
   - You can select a comment as the start and end of your recording by clicking the `Start/Stop` radio buttons in the
   table of displayed comments. To help find the appropriate comments, you can use the search box on the left side of the
   GUI. When you press search, only the previously displayed comments that include your entered search string will be
   shown. Press `Reset` to once again show all comments.
   - You can manually enter a time elapsed as a decimal (in seconds, SS.sss) since the start of the recording for the
   `start` and `end` fields on the left side of the GUI. Press Update to apply these changes.
   - You can manually enter a time of day for the `start` and `end` fields on the left side of the GUI. Make sure your
   start time is entered in 24hr format and includes a semicolon between hours minutes and seconds. Fractions of a second
   should be entered as decimals (`HH:MM:SS.ss`). Press Update to apply these changes.
   Regardless of which method you use, the selected comments will be highlighted in the displayed comments table. Green
   shows that the selected comments occurs at exactly the start of the selected interval, red that it occurs exactly at the
   end. All comments within the interval are highlighted in blue.
5. Make sure that an output file name is appropriate. The default name is 'stitched' if this is left unchanged, the 
output files will be named: `stitched.ccf`, `stitched.nev`, `stitched.ns3` and so on. If a $TASKID comment is found in 
the selected time range, then the name in that comment will be used by default unless a custom name has already been 
manually set.
6. Press the `Stitch` button to begin the stitching process. This will run asynchronously in the background, and both
text updates on the different steps of the process and a progressbar for each step will show up and the bottom of the 
screen. We expect a stitching rate on the order of several GB of NsX data per second, but longer recordings may take time.

## Errors
Throughout the stitching process, the GUI will show progress updates and user messages in the scrolling console window
at the bottom of the screen. State/Progress updates are shown in black, warnings in orange, and errors in red. If you
see an unexpected error, please contact tomek.fraczek@bcm.edu
