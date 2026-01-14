#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install Python dependencies
pip install -r requirements.txt

# Create a bin directory for ffmpeg
mkdir -p bin

# Download static ffmpeg build if it doesn't exist
if [ ! -f bin/ffmpeg ]; then
  echo "Downloading ffmpeg..."
  curl -L https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz | tar -xJ
  # Move binary to bin
  mv ffmpeg-master-latest-linux64-gpl/bin/ffmpeg bin/ffmpeg
  mv ffmpeg-master-latest-linux64-gpl/bin/ffprobe bin/ffprobe
  # Cleanup
  rm -rf ffmpeg-master-latest-linux64-gpl
  chmod +x bin/ffmpeg
  chmod +x bin/ffprobe
  echo "FFmpeg installed to bin/"
fi
