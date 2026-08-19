#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 INPUT.docx OUTPUT.pdf" >&2
    exit 2
fi

exec forge docx-to-pdf --input "$1" --output "$2"
