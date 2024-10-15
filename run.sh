#!/usr/bin/env bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
VENV_DIR="${SCRIPT_DIR}/.venv"

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv $VENV_DIR
  source "${VENV_DIR}/bin/activate"
  pip install bleak
  pip install paho-mqtt
fi

if [ -d "$VENV_DIR" ]; then
  source "${VENV_DIR}/bin/activate"
  python "${SCRIPT_DIR}/switchbot.py"
fi