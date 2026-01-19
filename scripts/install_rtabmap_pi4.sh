#!/usr/bin/env bash
set -euo pipefail

# Simple helper to build and install RTAB-Map and its Python bindings on a Raspberry Pi 4.
# Run this on the Pi4 as a user with sudo privileges. Building can take a long time.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/.build/rtabmap"

echo "RTAB-Map install helper"

if python3 -c "import importlib,sys
try:
    importlib.import_module('rtabmap')
    print('found')
except Exception:
    sys.exit(1)" 2>/dev/null; then
    echo "rtabmap python bindings already present; exiting"
    exit 0
fi

sudo apt-get update
sudo apt-get install -y \
  build-essential cmake git python3-dev pkg-config \
  libatlas-base-dev libopenblas-dev liblapack-dev \
  libjpeg-dev libtiff-dev libavcodec-dev libavformat-dev libswscale-dev \
  libv4l-dev libxvidcore-dev libx264-dev libgtk-3-dev \
  libboost-all-dev libeigen3-dev libusb-1.0-0-dev libsqlite3-dev libopenni2-dev libproj-dev

mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

if [ ! -d rtabmap ]; then
    git clone https://github.com/introlab/rtabmap.git
fi
cd rtabmap
git fetch --all --prune
git checkout master || true

mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DWITH_PYTHON=ON -DPYTHON_EXECUTABLE=$(which python3)
make -j$(nproc)
sudo make install

# Build & install Python bindings if present
if [ -d ../python ]; then
    cd ../python
    python3 setup.py build
    sudo python3 setup.py install
fi

echo "RTAB-Map build/install completed. Test with: python3 -c 'import rtabmap; print(rtabmap.__version__)'"
