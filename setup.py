"""Setup script for emu68-hatcher."""

from setuptools import setup, find_packages

# Find all packages in src/main/python
packages = find_packages(where="src/main/python")

setup(
    packages=packages,
    package_dir={"": "src/main/python"},
)
