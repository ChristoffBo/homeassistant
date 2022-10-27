#!/bin/bash
cd mimic3
source ./.venv/bin/activate
pip3 install --upgrade pip

mimic3-server
