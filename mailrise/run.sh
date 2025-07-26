#!/bin/bash

CONFIG_PATH="/data/mailrise.conf"

# Write config from Home Assistant options
echo "$CONFIG" > "$CONFIG_PATH"

# Run Mailrise using custom config
exec mailrise --config "$CONFIG_PATH"
