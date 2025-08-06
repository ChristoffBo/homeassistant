#!/bin/bash
chmod +x /app/toolkit.py /app/uploader.py /app/backup.py
python3 /app/uploader.py &
python3 /app/toolkit.py &
python3 /app/backup.py
