#!/bin/bash

CONFIG_PATH="/data/mailrise.conf"
echo "$CONFIG" > "$CONFIG_PATH"
exec mailrise --config "$CONFIG_PATH"
