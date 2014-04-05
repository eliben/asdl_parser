#!/bin/bash
set -eu
set -x

python3 asdl_c.py -h /tmp Python.asdl
python3 asdl_c.py -c /tmp Python.asdl
