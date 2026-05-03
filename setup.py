"""Setup script for emu68hatcher."""

from setuptools import find_packages, setup

# Find all packages in src/main/python
packages = find_packages(where="src/main/python")

setup(
    packages=packages,
    package_dir={"": "src/main/python"},
)
