#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# Python 3.11-3.13 is what `pyproject.toml` declares and `installer_core.py` enforces: Bookworm
# ships 3.11, Trixie 3.13, and 3.10 is end-of-life where pip refuses the package. The newest
# probe wins, so a 3.10 that happens to be first on PATH is never chosen (#113).
supported_python() {
	local version
	version="$("${1}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
	case "${version}" in
		3.11|3.12|3.13) return 0 ;;
	esac
	return 1
}

# Order: env $PYTHON, then the newest python3 the image has.
if [ -n "${PYTHON:-}" ]; then
	PYTHON_BIN="${PYTHON}"
	if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
		echo "PYTHON='${PYTHON_BIN}' not found on PATH. Install Python 3.11-3.13, or set PYTHON to a valid interpreter."
		exit 2
	fi
	if ! supported_python "${PYTHON_BIN}"; then
		echo "PYTHON='${PYTHON_BIN}' is not 3.11-3.13. HoundMind supports 3.11-3.13 (Bookworm ships 3.11)."
		exit 2
	fi
else
	for candidate in python3.13 python3.12 python3.11; do
		if command -v "${candidate}" >/dev/null 2>&1; then
			PYTHON_BIN="${candidate}"
			break
		fi
	done
	if [ -z "${PYTHON_BIN:-}" ]; then
		echo "Python 3.11-3.13 is required. Install one and re-run the installer."
		exit 2
	fi
fi

# If an existing venv uses an unsupported Python, force recreation.
AUTO_FORCE_RECREATE=0
VENV_PY="${ROOT_DIR}/.venv/bin/python"
if [ -x "${VENV_PY}" ]; then
	if ! supported_python "${VENV_PY}"; then
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
