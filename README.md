# PyNsXStitch

Small helper library to stitch together Blackrock NeV and NsX files from a chunked recording into task specific files 
based on comments

Please report any bugs and issues you find as issues on the github repo:
https://github.com/BCM-Neurosurgery/pyNsXStitch/issues

# Installation

## Stand-alone
To install this as a python project you can use to perform custom stitching:
  - Make sure you have python 3.10 or newer installed (3.12 or newer recommended)
  - Make sure you have a python virtual environment set up and activated (uv  or conda recommended).
  - Clone the repository. You can use GitHub Desktop, or if you're working in terminal:
    ```bash
    git clone git@github.com:BCM-Neurosurgery/pyNsXStitch.git
    ```
  - Make sure to `cd` to the cloned directory containing the source code
  - Then install all the requirements with one of the following, depending on the environment manager you use
    - conda: `pip install .`
    - uv:    `uv pip install .`
  - Check out the usage section below for usage instructions. If you plan to run the included jupyter notebooks, you 
will need to make sure `jupyter` is installed.

This is the option you want to follow if:
  - You want to use the GUI to stitch data
  - You want to use one of the existing example scripts to stitch/anonymize data
  - You want to contribute to the project 

## Dependency
To install this code as a dependency to your own project, add the following line to your dependencies in your `pyproject.toml`:
```requirements
pyNsXStitch @ git+ssh://git@github.com/BCM-Neurosurgery/pyNsXStitch.git@main
```
This will automatically solve the dependencies of this project and install it as a python package when you install all 
the dependencies for your project

This is the option you want to use if:
  - You are writing your own code/package and want to use this package as a tool

# Usage
See GUI_Instructions.md for extensive instructions on how to use the GUI. This section is primarily concerned with
using the code directly as a part of your python code. See the scripts and notebooks in the `examples` folder for
additional details


## Usage ready scripts
There are several ready to use scripts to accomplish various common tasks, more or less ready to use. However, these
scripts are generally designed as simplified stubs and examples of usage. To customize behavior, please build out your
own scripts using this package as a dependency.

We list a few of the more useful scripts here.

### batch_anonymize.py
Recurse through the contents of a directory, applying basic anonymization functions to all BRK files discovered in that 
directory and outputting them to a new location. 

**THIS PROCESS DOES NOT GUARANTEE COMPLETE ANONYMIZATION AND YOU MUST ALWAYS CHECK THAT THE OUTPUT FILES ARE CORRECTLY 
ANONYMIZED AND STRIPPED OF POTENTIAL PHI!**

### stitch_all.py
Stitch together all the individual TOC-mode BRK files in a directory into a single output file.

### stitch_listed.py
Stitch together data from a collection of TOC mode recordings based on tasks listed in a csv file

## Python functionality

This package is broken up into several modules:
### Stitchers
The two objects in this file are the intended top-level utilities provided by this package. They are designed to
facilitate looping over the data from mutliple files as if it was all in one file. To performs stitching, you will need
to instantiate and iterate through the data with the appropriate Stitcher for each file type (see examples). The main 
functions of interest on each of these objects are:
  - `write`: Write the data from all the files in this stitcher to a single file. This uses the headers from the first 
file, and then iterates through and writes in the data from all the remaining files.
  - `iter_data`: this iterates through all the data in all the files passed to the stitcher as if it was all coming from
a single file.

### Streamers
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

### Anonymizers
Collection of functions and tools useful for anonymizing BRK data files and stripping out PHI.
  - `remove_audio_nsx`:
  - `remove_dates_nev`:
  - `remove_dates_nsx`:
  - `nev_anoonymize`: Helper function to anonymize a single nev file. Currently only obfuscates dates
  - `nsx_anonymize`: Helper function to anonymize a single NSX file. Currently removes audio channels and obfuscates dates


### Helpers
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