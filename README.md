# PyNsXStitch

Small helper library to stitch together Blackrock NeV and NsX files from a chunked recording into task specific files 
based on comments

**** WARNING: THIS CODE REMAINS AS YET UNVERIFIED AND MAKES NO GUARANTEE THAT THE OUTPUT NSX FILES WILL CONTAIN
INDIVIDUAL MISSED PACKETS OR DATA POINTS***

(though it does generally work well as far as I can tell...)

## Installation

### Stand-alone
To install this as a python project you can use to perform custom stitching:
  - Make sure you have a python environment (conda recommended) install with python 3.10 or greater
  - Clone the repository
    ```bash
    git clone git@github.com:shethlab/pyNsXStitch.git
    ```
  - Then install all the requirements with
    ```bash
    pip install -r requirements.txt
    ```
  - Check out the usage section below for usage instructions. If you plan to run the included jupyter notebooks, you 
will need to make sure `jupyter` is installed. You can either do this yourself, or uncomment the jupyter line in the 
requirements file before running the pip command above.


### Dependency
To install this code as a dependency to your own project, add the following line to your requirements.txt:
```requirements
git+ssh://git@github.com/shethlab/pyNsXStitch.git@main#egg=pynsxstitch
```
This will automatically solve the dependencies of this project and install it as a python package when you run
```bash
pip install -r requirements.txt
```

## Usage
See GUI_Instructions.md for extensive instructions on how to use the GUI. This section is primarily concerned with
using the code directly as a part of your python code. See the scripts and notebooks in the `examples` folder for
additional details

This package is broken up into several modules:
#### Stitchers
The two objects in this file are the intended top-level utilities provided by this package. They are designed to
facilitate looping over the data from mutliple files as if it was all in one file. To performs stitching, you will need
to instantiate and iterate through the data with the appropriate Stitcher for each file type (see examples). The main 
functions of interest on each of these objects are:
  - `write`: Write the data from all the files in this stitcher to a single file. This uses the headers from the first 
file, and then iterates through and writes in the data from all the remaining files.
  - `iter_data`: this iterates through all the data in all the files passed to the stitcher as if it was all coming from
a single file.

#### Streamers
These are generator functions that manage the streaming data out of a file and into memory. They are designed to be able
to iterate through the data in the binary files quickly, and provide basic support for time range selection. They are 
largely a re-formulation of the blackrock python utilities, but optimized for reading data sequentially instead of in 
large batches
  - `stream_nev_packets`: This iterator yields NeV data packets one-by-one, indexed by both the timestamp and packet_id. 
More information on how to interpret the packet id is available in the blackrock documentation. (See the [references](#references))
  - `stream_nsx_data`: This iterator yields small data batches (~1MB by default, you can adjust this packet size in the
setting file). If a batch is at the start of one of the packets stored in the file, then the yielded value will include
a tuple of the timestamp at the start of the packet, and the size of the full packet. Otherwise, the first returned 
value will be `None`. In all cases, the packet data is a numpy memory_map of the raw data. If the batch extends past the
end of the packet then it will be truncated.
  - `iter_nsx_timestamps`: Quickly iterate through all the packets in an NsX file, returning only the headers. Useful 
primarily for checking the size and duration of the NsX file, as well as assessing data drop rates

#### Helpers
These are small atomic functions that provide helpful utilities when performing stitching. Some of the most useful ones
(in no particular order) include:
  - `get_all_nev_comments`: Read all comments from the given list of NeV files and package them into a pandas dataframe
  - `get_all_streamed_files`: Return a dictionary of all the NeV and NsX files in the given directory
  - `get_nsx_in_range`: Of the given NsX files, select only those that fall at least in part within the given time range (in seconds)

## References
 - Uses the Python utilities from blackrock: [link](https://github.com/BlackrockNeurotech/Python-Utilities)
 - Documentation of the NeV and NsX file formats: [link](https://blackrockneurotech.com/wp-content/uploads/LB-0023-7.00_NEV_File_Format.pdf)

Fulfills similar requirements to the old matlab stitching code [link](https://github.com/shethlab/TOC-Chronological-Stiching) 
but faster and better fits within a python-oriented ecosystem.