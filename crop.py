#!/usr/bin/env python3
"""
Shrink font in a hexdraw text file
(c) 2019 Rob Hagemans, licence: https://opensource.org/licenses/MIT
"""

import sys
import argparse
import logging

import monobit

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')


# parse command line
parser = argparse.ArgumentParser()
parser.add_argument('infile', nargs='?', type=argparse.FileType('r'), default=sys.stdin)
parser.add_argument('outfile', nargs='?', type=argparse.FileType('w'), default=sys.stdout)
parser.add_argument(
    '--left', default=0, type=int,
    help='first pixel on left'
)
parser.add_argument(
    '--top', default=0, type=int,
    help='first pixel from top'
)
parser.add_argument(
    '--right', default=None, type=int,
    help='last pixel on right'
)
parser.add_argument(
    '--bottom', default=None, type=int,
    help='last pixel at bottom'
)
args = parser.parse_args()

font = monobit.hexdraw.load(args.infile)
font = monobit.crop(font, args.left, args.top, args.right, args.bottom)
monobit.hexdraw.save(font, args.outfile)