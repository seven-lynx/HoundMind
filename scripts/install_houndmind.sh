#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# Prefer a Python interpreter that is compatible with heavy Pi packages.
# Order: env $PYTHON, python3.10, python3.11, python3.9, python3
if [ -n "${PYTHON:-}" ]; then
	PYTHON_BIN="${PYTHON}"
elif command -v python3.10 >/dev/null 2>&1; then
	PYTHON_BIN=python3.10
elif command -v python3.11 >/dev/null 2>&1; then
	PYTHON_BIN=python3.11
elif command -v python3.9 >/dev/null 2>&1; then
	PYTHON_BIN=python3.9
else
	PYTHON_BIN=python3
fi

# If RUN_I2SAMP=1 is set, or user passes --run-i2samp, forward it.
EXTRA_ARGS=("--auto-system-deps")

# Preserve any user-provided args
for a in "$@"; do
	EXTRA_ARGS+=("$a")
done

# If caller requested automatic i2samp via env, ensure flag is present
if [ "${RUN_I2SAMP:-}" = "1" ]; then
	skip=0
	for a in "${EXTRA_ARGS[@]}"; do
		if [ "$a" = "--run-i2samp" ]; then skip=1; break; fi
	done
	if [ $skip -eq 0 ]; then
		EXTRA_ARGS+=("--run-i2samp")
	fi
fi

# If running interactively and not explicitly provided, prompt the user whether to run i2samp
if [ -t 0 ] && [ "${RUN_I2SAMP:-}" != "1" ]; then
	want=""
	for a in "${EXTRA_ARGS[@]}"; do
		if [ "$a" = "--run-i2samp" ]; then want="yes"; break; fi
	done
	if [ -z "$want" ]; then
		echo "Would you like to run the PiDog audio helper (i2samp.sh) after installing pidog? [y/N]"
		read -r ans || true
		case "$ans" in
			[yY]|[yY][eE][sS])
				EXTRA_ARGS+=("--run-i2samp")
				;;
			*) ;;
		esac
	fi
fi

"${PYTHON_BIN}" "${ROOT_DIR}/scripts/installer_core.py" "${EXTRA_ARGS[@]}"
