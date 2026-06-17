#!/usr/bin/env python3
"""Run the OpenClaw OTel Monitor server."""

import sys
import os

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.server.app import main

if __name__ == "__main__":
    main()