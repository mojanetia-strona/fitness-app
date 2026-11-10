#!/bin/sh
# Kompilacja dla MicroPython 1.29 (pip install mpy-cross==1.29.0.post2)
cd "$(dirname "$0")" && python3 -m mpy_cross app.py && python3 -m mpy_cross miio.py
