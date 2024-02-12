# Always prefer setuptools over distutils
from setuptools import setup, find_packages
import pathlib

here = pathlib.Path(__file__).parent.resolve()

# Get the long description from the README file
long_description = (here / "README.md").read_text(encoding="utf-8")

# Arguments marked as "Required" below must be included for upload to PyPI.
# Fields marked as "Optional" may be commented out.
setup(
    name="sampleproject",  # Required
    version="0.1.0",  # Required
    description="Package to stitch blackrock toc mode recording files",  # Optional
    long_description=long_description,  # Optional
    long_description_content_type="text/markdown",  # Optional (see note above)
    url="https://github.com/shethlab/NsXStitching-python",  # Optional
    author="Tomasz Fraczek",  # Optional
    author_email="tfraczek@uw.edu",  # Optional
    keywords="sample, setuptools, development",  # Optional
    # You can just specify package directories manually here if your project is
    # simple. Or you can use find_packages()
    packages=find_packages(),  # Required
    python_requires=">=3.7, <4",
    # For an analysis of "install_requires" vs pip's requirements files see:
    # https://packaging.python.org/discussions/install-requires-vs-requirements/
    install_requires=["numpy", "pandas", "matplotlib"],  # Optional
)