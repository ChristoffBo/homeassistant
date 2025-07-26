#!/bin/bash

CONFIG_PATH="/data/mailrise.conf"

# Save config from GUI to file
echo "$CONFIG" > "$CONFIG_PATH"

# Run Mailrise with provided config
exec mailrise --config "$CONFIG_PATH"
