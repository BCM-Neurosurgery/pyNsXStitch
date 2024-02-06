Small helper library to stitch together Blackrock NeV and NsX files from a chunked recording into task specific files 
based on comments

## Installation

### Stand-alone
To install this as a python project you can use to perform custom stitching:
  - Make sure you have a python environment (conda recommended) install with python 3.10 or greater
  - Clone the repository
    - ```git clone git@github.com:shethlab/NsXStitching-python.git```
  - Then install all the requirements with
    - ```pip install -r requirements.txt```
  - Check out the included jupyter notebooks for usage instructions


### Dependency
Installing this project as a dependency is not yet supported.
Need to:
  - add a setup.py
  - re-organize the directory structure 
Eventually you will be able to include the following line in your requirements.txt:
```requirements
git+ssh://git@github.com/shethlab/NsXStitching-python.git@main#egg=nsxstitch
```

## References
 - Uses the Python utilities from blackrock: [link](https://github.com/BlackrockNeurotech/Python-Utilities)
 - Documentation of the NeV and NsX file formats: [link](https://blackrockneurotech.com/wp-content/uploads/LB-0023-7.00_NEV_File_Format.pdf)

Fulfills similar requirements to the old matlab stitching code [link](https://github.com/shethlab/TOC-Chronological-Stiching) 
but faster and better fits within a python-oriented ecosystem.