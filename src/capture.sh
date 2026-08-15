#!/bin/bash
# Read-only screen capture helper for pulling game data without the
# record / save / hand-over loop.
#
#   ./capture.sh once            one capture, OCR'd immediately
#   ./capture.sh timed 20 2      20 captures, 2s apart (hover things as it runs)
#   ./capture.sh read <file>     OCR an existing image
#
# Captures land in caps/ and are OCR'd with the local Apple Vision tool.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
mkdir -p caps
MODE="${1:-once}"

shot() {  # $1 = output path
  screencapture -x -t png "$1" 2>/dev/null
  [ -s "$1" ] || { echo "capture blocked: grant Screen Recording to the terminal in"; \
                   echo "System Settings > Privacy & Security > Screen Recording"; return 1; }
}

case "$MODE" in
  once)
    f="caps/shot_$(date +%H%M%S).png"
    shot "$f" || exit 1
    echo "captured $f"
    ./ocr "$f"
    ;;
  timed)
    n="${2:-20}"; gap="${3:-2}"
    echo "taking $n captures, ${gap}s apart. Navigate the game now."
    for i in $(seq -w 1 "$n"); do
      f="caps/seq_$i.png"
      shot "$f" || exit 1
      sleep "$gap"
    done
    echo "done, OCRing all $n"
    ./ocr caps/seq_*.png
    ;;
  read)
    ./ocr "${2:?usage: capture.sh read <file>}"
    ;;
  *)
    echo "usage: capture.sh [once|timed N GAP|read FILE]"
    ;;
esac
