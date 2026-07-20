#!/bin/sh
# launch emu68hatcher from this source checkout via the macos venv
# (.venv - the same one bootstrap.py manages)
cd "$(dirname "$0")" || exit 1

# a venv without pip is the leftover of a create that failed at the
# ensurepip step - rebuild it
if [ -x .venv/bin/python ] && [ ! -x .venv/bin/pip ]; then
    echo "Found a broken .venv (no pip) - rebuilding"
    rm -rf .venv
fi

if [ ! -x .venv/bin/python ]; then
    echo "First run - creating venv at .venv"
    python3 -m venv .venv || {
        rm -rf .venv
        echo "could not create venv - install python 3.10+ (xcode command line tools or brew)"
        exit 1
    }
fi

if [ ! -x .venv/bin/emu68hatcher ]; then
    echo "Installing emu68hatcher into .venv"
    .venv/bin/python -m pip install -e . || exit 1
fi

exec .venv/bin/python -m emu68hatcher
