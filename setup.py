import sys

from setuptools import Extension, setup

# Define the C extension module
pds_extension = Extension(
    "spork.runtime.pds",
    sources=["spork/runtime/pds.c"],
    include_dirs=[],
    extra_compile_args=["-O3"] if sys.platform != "win32" else ["/O2"],
)

setup(
    ext_modules=[pds_extension],
)
