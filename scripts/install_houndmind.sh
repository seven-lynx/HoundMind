#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# Prefer a Python interpreter that matches supported versions.
# Order: env $PYTHON, python3.10, python3.11
if [ -n "${PYTHON:-}" ]; then
	PYTHON_BIN="${PYTHON}"
	if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
		echo "PYTHON='${PYTHON_BIN}' not found on PATH. Install Python 3.10 or 3.11, or set PYTHON to a valid interpreter."
		exit 2
	fi
elif command -v python3.10 >/dev/null 2>&1; then
	PYTHON_BIN=python3.10
elif command -v python3.11 >/dev/null 2>&1; then
	PYTHON_BIN=python3.11
else
	echo "Python 3.10 or 3.11 is required. Install one and re-run the installer."
	exit 2
fi

# If an existing venv uses an unsupported Python, force recreation.
AUTO_FORCE_RECREATE=0
VENV_PY="${ROOT_DIR}/.venv/bin/python"
if [ -x "${VENV_PY}" ]; then
	ver="$(${VENV_PY} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
	if [ -z "${ver}" ] || { [ "${ver}" != "3.10" ] && [ "${ver}" != "3.11" ]; }; then
		AUTO_FORCE_RECREATE=1
	fi
fi

# If RUN_I2SAMP=1 is set, or user passes --run-i2samp, forward it.
EXTRA_ARGS=("--auto-system-deps")
SKIP_VENV=0

# Preserve any user-provided args
for a in "$@"; do
	if [ "$a" = "--skip-venv" ]; then
		SKIP_VENV=1
	fi
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

# Force venv recreation if we detected a mismatched interpreter (unless --skip-venv)
if [ ${AUTO_FORCE_RECREATE} -eq 1 ] && [ ${SKIP_VENV} -eq 0 ]; then
	skip=0
	for a in "${EXTRA_ARGS[@]}"; do
		if [ "$a" = "--force-recreate-venv" ]; then skip=1; break; fi
	done
	if [ $skip -eq 0 ]; then
		EXTRA_ARGS+=("--force-recreate-venv")
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
