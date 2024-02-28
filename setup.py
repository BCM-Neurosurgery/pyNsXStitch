# Always prefer setuptools over distutils
from setuptools import setup, find_packages
import pathlib

here = pathlib.Path(__file__).parent.resolve()

# Get the long description from the README file
long_description = (here / "README.md").read_text(encoding="utf-8")

# See the link below for a great documentation of how setup() works
#   https://packaging.python.org/en/latest/guides/distributing-packages-using-setuptools/
setup(
    name="pyNsXStitch",
    version="0.1.2",
    description="Package to stitch blackrock toc mode recording files",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/shethlab/NsXStitching-python",
    author="Tomasz Fraczek",
    author_email="tfraczek@uw.edu",
    keywords="Blackrock, stitching",
    packages=find_packages(),
    python_requires=">=3.8, <4",
    install_requires=["numpy", "pandas", "matplotlib"],
)