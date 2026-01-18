# RTAB-Map Installation Guide for Pi4 (HoundMind)

This guide documents the recommended steps to install RTAB-Map and its Python bindings (rtabmap-py) on Raspberry Pi 4 for HoundMind SLAM integration.

---

## 1. System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y cmake g++ git libopencv-dev libpcl-dev libqt5svg5-dev libqt5core5a libqt5gui5 libqt5widgets5 qtbase5-dev qtchooser qt5-qmake qtbase5-dev-tools libboost-all-dev libeigen3-dev libusb-1.0-0-dev libsqlite3-dev libopenni2-dev libproj-dev libgtsam-dev python3-pip python3-dev
```

## 2. Install RTAB-Map from Source

```bash
git clone https://github.com/introlab/rtabmap.git
cd rtabmap
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DWITH_PYTHON=ON -DPYTHON_EXECUTABLE=$(which python3)
make -j$(nproc)
sudo make install
```

## 3. Install Python Bindings (rtabmap-py)

If not built automatically, build and install the Python bindings:

```bash
cd ../python
python3 setup.py build
sudo python3 setup.py install
```

## 4. Test Installation

```bash
python3 -c "import rtabmap; print(rtabmap.__version__)"
```

---

## Notes
- Building RTAB-Map on Pi4 may take 1-2 hours.
- For best performance, use a Pi Camera or USB camera supported by OpenCV.
- If you encounter errors, see the official RTAB-Map [wiki](https://github.com/introlab/rtabmap/wiki/Installation) for troubleshooting.

---

## Integration
- Once installed, the HoundMind SLAM module will auto-detect and use RTAB-Map if `settings.slam_pi4.backend = "rtabmap"`.
- All dependencies should be installed in the same Python environment as HoundMind.
