#!/bin/bash

# create the most beautiful png from an arbitrary file
if [ $# -lt 2 ]; then
    echo "Usage: $0 <input_file.ext> <output_file.png>" 1>&2
    exit 1
fi

python3 "$(realpath "$(dirname "${BASH_SOURCE[0]}")")/.pngspeak" -W 16 -uw 128 -uh 4096 < "$1" > "$2"

