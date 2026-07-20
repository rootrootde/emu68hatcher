#!/bin/sh
# launch emu68hatcher from this source checkout, using a linux-only venv
# (.venvlinux) so a macos .venv in the same dir stays untouched
cd "$(dirname "$0")" || exit 1

# a venv without pip is the leftover of a create that failed at the
# ensurepip step (ubuntu without python3-venv) - rebuild it
if [ -x .venvlinux/bin/python ] && [ ! -x .venvlinux/bin/pip ]; then
    echo "Found a broken .venvlinux (no pip) - rebuilding"
    rm -rf .venvlinux
fi

if [ ! -x .venvlinux/bin/python ]; then
    echo "First run - creating linux venv at .venvlinux"
    python3 -m venv .venvlinux || {
        rm -rf .venvlinux
        echo "could not create venv - on ubuntu install it first: sudo apt install python3-venv"
        exit 1
    }
fi

if [ ! -x .venvlinux/bin/emu68hatcher ]; then
    echo "Installing emu68hatcher into .venvlinux"
    .venvlinux/bin/python -m pip install -e . || exit 1
fi

exec .venvlinux/bin/python -m emu68hatcher
