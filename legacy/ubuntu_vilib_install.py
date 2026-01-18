#!/usr/bin/env python3
from distutils.log import warn
import os, sys
import time
import threading

# version
# =================================================================
sys.path.append("./vilib")

import pwd

owner_uid = os.stat(__file__).st_uid
user_name = pwd.getpwuid(owner_uid).pw_name

from version import __version__

print("Start installing vilib %s for user %s" % (__version__, user_name))


# define color print
# =================================================================
def warn(msg, end="\n", file=sys.stdout, flush=False):
    print(f"\033[0;33m{msg}\033[0m", end=end, file=file, flush=flush)


def error(msg, end="\n", file=sys.stdout, flush=False):
    print(f"\033[0;31m{msg}\033[0m", end=end, file=file, flush=flush)


# check if run as root
# =================================================================
if os.geteuid() != 0:
    warn('Script must be run as root. Try "sudo python3 install.py".')
    sys.exit(1)

# global variables defined
# =================================================================
errors = []

avaiable_options = ["-h", "--help", "--no-dep"]

usage = """
Usage:
    sudo python3 install.py [option]

Options:
               --no-dep    Do not download dependencies
    -h         --help      Show this help text and exit
"""


# utils
# =================================================================
def run_command(cmd=""):
    import subprocess

    p = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    result = p.stdout.read().decode("utf-8")
    status = p.poll()
    return status, result


at_work_tip_sw = False


def working_tip():
    char = ["/", "-", "\\", "|"]
    i = 0
    global at_work_tip_sw
    while at_work_tip_sw:
        i = (i + 1) % 4
        sys.stdout.write("\033[?25l")  # cursor invisible
        sys.stdout.write("%s\033[1D" % char[i])
        sys.stdout.flush()
        time.sleep(0.5)

    sys.stdout.write(" \033[1D")
    sys.stdout.write("\033[?25h")  # cursor visible
    sys.stdout.flush()


def do(msg="", cmd=""):
    print(" - %s ... " % (msg), end="", flush=True)
    # at_work_tip start
    global at_work_tip_sw
    at_work_tip_sw = True
    _thread = threading.Thread(target=working_tip)
    _thread.daemon = True
    _thread.start()
    # process run
    status, result = run_command(cmd)
    # print(status, result)
    # at_work_tip stop
    at_work_tip_sw = False
    while _thread.is_alive():
        time.sleep(0.01)
    # status
    if status == 0 or status == None or result == "":
        print("Done")
    else:
        print("\033[1;35mError\033[0m")
        errors.append("%s error:\n  Status:%s\n  Error:%s" % (msg, status, result))


def check_python_version():
    import sys

    major = int(sys.version_info.major)
    minor = int(sys.version_info.minor)
    micro = int(sys.version_info.micro)
    return major, minor, micro


def check_os_bit():
    """
    # import platform
    # machine_type = platform.machine()
    latest bullseye uses a 64-bit kernel
    This method is no longer applicable, the latest raspbian will uses 64-bit kernel
    (kernel 6.1.x) by default, "uname -m" shows "aarch64",
    but the system is still 32-bit.
    """
    _, os_bit = run_command("getconf LONG_BIT")
    return int(os_bit)


# print system and hardware information
# =================================================================
python_version = check_python_version()
os_bit = check_os_bit()

print(f"Python version: {python_version[0]}.{python_version[1]}.{python_version[2]}")
print(f"({os_bit}bit)")
print("")

# Dependencies list installed with apt
# =================================================================
APT_INSTALL_LIST = [
    "python3-libcamera",
    # install python3-picamera2: https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
    "python3-picamera2",
    "rpicam-apps",
    "python3-pyqt5",
    "python3-opengl",
    # install python3-opencv: # https://qengineering.eu/install-opencv-4.5-on-raspberry-64-os.html
    "python3-opencv",
    "opencv-data",
    # install ffmpeg
    "ffmpeg",
    # install mediapipe dependencies
    "libgtk-3-0",
    "libxcb-shm0",
    "libcdio-paranoia-dev",
    "libsdl2-2.0-0",
    "libxv1",
    "libtheora0",
    "libva-drm2",
    "libva-x11-2",
    "libvdpau1",
    "libharfbuzz0b",
    "libbluray2",
    "libatlas-base-dev",
    "libhdf5-103",
    # "libopenexr25",
    "libzbar0",
    "libopenblas-dev",
]

# Dependencies list installed with pip3
# =================================================================
PIP_INSTALL_LIST = [
    "tflite-runtime",
    "Flask",
    "imutils",
    "qrcode",
    "pyzbar",  # pyzbar:one-dimensional barcodes and QR codes
    "pyzbar[scripts]",
    "readchar",  # will update setuptools to the latest version
    "protobuf>=3.20.0",  # mediapipe need
]

# check whether mediapipe is supported
is_mediapipe_supported = False
if os_bit == 64:
    is_mediapipe_supported = True
    PIP_INSTALL_LIST.append("mediapipe")
    PIP_INSTALL_LIST.append("numpy")
else:
    is_mediapipe_supported = False
    warn("mediapipe is only supported on 64bit system.")


# main function
# =================================================================
def install():
    options = []
    if len(sys.argv) > 1:
        options = sys.argv[1:]
        for opt in options:
            if opt not in avaiable_options:
                print("Option {} is not found.".format(opt))
                print(usage)
                sys.exit(0)
        if "-h" in options or "--help" in options:
            print(usage)
            sys.exit(0)

    # check whether pip has the option "--break-system-packages"
    _is_bsps = ""
    status, _ = run_command("pip3 help install|grep break-system-packages")
    if status == 0:
        _is_bsps = "--break-system-packages"

    print("Install vilib python package")
    # do(msg="run setup file",
    #     cmd='python3 setup.py install')
    do(msg="pip3 install ./", cmd=f"pip3 install ./ {_is_bsps}")
    do(msg="cleanup", cmd="rm -rf vilib.egg-info")

    if "--no-dep" not in options:
        # install dependencies with apt
        # ===================================
        print("apt install dependency:")
        do(msg="dpkg configure", cmd="dpkg --configure -a")
        do(msg="update apt-get", cmd="apt-get update -y")
        for dep in APT_INSTALL_LIST:
            do(msg=f"install {dep}", cmd=f"apt-get install {dep} -y")

        # install dependencies with pip
        # ===================================
        print("pip3 install dependency:")

        if _is_bsps != "":  # if true
            print("\033[38;5;8m pip3 install with --break-system-packages\033[0m")
        # update pip
        do(msg="update pip3", cmd=f"python3 -m pip install --upgrade pip {_is_bsps}")
        for dep in PIP_INSTALL_LIST:
            if dep.endswith(".whl"):
                dep_name = dep.split("/")[-1]
            else:
                dep_name = dep
            do(msg=f"install {dep_name}", cmd=f"pip3 install {dep} {_is_bsps}")
        #
        if is_mediapipe_supported == False:
            print(
                "\033[38;5;8m  mediapipe is not supported on this platform... Skip \033[0m"
            )

    print("Create workspace")
    # ===================================
    if not os.path.exists("/opt"):
        os.mkdir("/opt")
        run_command("chmod 774 /opt")
        run_command(f"chown -R {user_name}:{user_name} /opt")
    do(
        msg="create dir",
        cmd="mkdir -p /opt/vilib"
        + " && chmod 774 /opt/vilib"
        + f" && chown -R {user_name}:{user_name} /opt/vilib",
    )
    do(
        msg="copy workspace",
        cmd="cp -r ./workspace/* /opt/vilib/"
        + " && chmod 774 /opt/vilib/*"
        + f" && chown -R {user_name}:{user_name} /opt/vilib/*",
    )

    # check errors
    if len(errors) == 0:
        print("Finished")
    else:
        print("\n\nError happened in install process:")
        for error in errors:
            print(error)
        print(
            "Try to fix it yourself, or contact service@sunfounder.com with this message"
        )


if __name__ == "__main__":
    try:
        install()
    except KeyboardInterrupt:
        print("\n\nCanceled.")
    finally:
        sys.stdout.write(" \033[1D")
        sys.stdout.write("\033[?25h")  # cursor visible
        sys.stdout.flush()
