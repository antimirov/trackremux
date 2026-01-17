#!/usr/bin/env python3
"""
TrackRemux - Root Wrapper
This script allows running TrackRemux directly from the source directory.
"""
import sys
import os

# Add the current directory to sys.path so we can find the trackremux package
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from trackremux.__main__ import main

if __name__ == "__main__":
    main()
