#!/usr/bin/bashio

#################
# Update to v3 #
################

if bashio::config.true "TRANSMISSION_V3_UPDATE"; then

    (
        bashio::log.info "Updating transmission to v3"
        bashio::log.warning "If your previous version was v2, remove and add torrents again"

        # see https://github.com/haugene/docker-transmission-openvpn/discussions/1937
        wget -O 976b5901365c5ca1.key "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xa37da909ae70535824d82620976b5901365c5ca1"

        cat > /etc/apt/sources.list.d/transmission.list <<EOF
# Transmission PPA https://launchpad.net/~transmissionbt/+archive/ubuntu/ppa
deb [signed-by=/976b5901365c5ca1.key] http://ppa.launchpad.net/transmissionbt/ppa/ubuntu focal main
#deb-src http://ppa.launchpad.net/transmissionbt/ppa/ubuntu focal main
EOF

        apt-get update -o Dir::Etc::sourcelist="sources.list.d/transmission.list" -o Dir::Etc::sourceparts="-" -o APT::Get::List-Cleanup="0"
        apt-get install -y transmission-daemon transmission-cli
    ) >/dev/null

fi

####################
# Export variables #
####################

bashio::log.info "Exporting variables"
for k in $(bashio::jq "/data/options.json" 'keys | .[]'); do
    bashio::log.blue "$k"="$(bashio::config "$k")"
    export "$k"="$(bashio::config "$k")"
done
echo ""

###########################
# Correct download folder #
###########################

if [ -f "$TRANSMISSION_HOME"/settings.json ]; then
    echo "Updating variables"
    sed -i "/download-dir/c     \"download-dir\": \"$(bashio::config 'TRANSMISSION_DOWNLOAD_DIR')\"," "$TRANSMISSION_HOME"/settings.json
    sed -i "/incomplete-dir/c     \"incomplete-dir\": \"$(bashio::config 'TRANSMISSION_INCOMPLETE_DIR')\"," "$TRANSMISSION_HOME"/settings.json || true
    sed -i "/watch-dir/c     \"watch-dir\": \"$(bashio::config 'TRANSMISSION_WATCH_DIR')\"," "$TRANSMISSION_HOME"/settings.json || true
    sed -i.bak ':begin;$!N;s/,\n}/\n}/g;tbegin;P;D' "$TRANSMISSION_HOME"/settings.json
fi

#######################
# Correct permissions #
#######################

# Get variables
DOWNLOAD_DIR="$(bashio::config 'TRANSMISSION_DOWNLOAD_DIR')"
INCOMPLETE_DIR="$(bashio::config 'TRANSMISSION_INCOMPLETE_DIR')"
WATCH_DIR="$(bashio::config 'TRANSMISSION_WATCH_DIR')"
TRANSMISSION_HOME="$(bashio::config 'TRANSMISSION_HOME')"

# Get id
if bashio::config.has_value 'PUID' && bashio::config.has_value 'PGID'; then
    echo "Using PUID $(bashio::config 'PUID') and PGID $(bashio::config 'PGID')"
    PUID="$(bashio::config 'PUID')"
    PGID="$(bashio::config 'PGID')"
else
    PUID="$(id -u)"
    PGID="$(id -g)"
fi

# Update permissions
for folder in "$DOWNLOAD_DIR" "$INCOMPLETE_DIR" "$WATCH_DIR" "$TRANSMISSION_HOME"; do
    mkdir -p "$folder"
    chown -R "$PUID:$PGID" "$folder"
done

###################
# Custom provider #
###################

if bashio::config.true "OPENVPN_CUSTOM_PROVIDER"; then

    OVPNLOCATION="$(bashio::config "OPENVPN_CUSTOM_PROVIDER_OVPN_LOCATION")"
    OPENVPN_PROVIDER="${OVPNLOCATION##*/}"
    OPENVPN_PROVIDER="${OPENVPN_PROVIDER%.*}"
    OPENVPN_PROVIDER="${OPENVPN_PROVIDER,,}"
    bashio::log.info "Custom openvpn provider selected"

    # Check that ovpn file exists
    if [ ! -f "$(bashio::config "OPENVPN_CUSTOM_PROVIDER_OVPN_LOCATION")" ]; then
        bashio::log.fatal "Ovpn file not found at location provided : $OVPNLOCATION"
        exit 1
    fi

    # Copy ovpn file
    sed -i "s|config_repo_temp_dir=\$(mktemp -d)|config_repo_temp_dir=/tmp/tmp2|g" /etc/openvpn/fetch-external-configs.sh
    echo "Copying ovpn file to proper location"
    mkdir -p /etc/openvpn/"$OPENVPN_PROVIDER"
    mkdir -p /tmp/tmp2/temp/openvpn/"$OPENVPN_PROVIDER"
    cp "$OVPNLOCATION" /tmp/tmp2/temp/openvpn/"$OPENVPN_PROVIDER"/"$OPENVPN_PROVIDER".ovpn

    # Use custom provider
    echo "Exporting variable for custom provider : $OPENVPN_PROVIDER"
    export OPENVPN_PROVIDER="$OPENVPN_PROVIDER"
    export OPENVPN_CONFIG="$OPENVPN_PROVIDER"

else

    bashio::log.info "Custom openvpn provider not selected, the provider $OPENVPN_PROVIDER will be used"

fi

###################
# Accept local ip #
###################

ip route add 10.0.0.0/8 via 172.30.32.1
ip route add 192.168.0.0/16 via 172.30.32.1
ip route add 172.16.0.0/12 via 172.30.32.1
ip route add 172.30.0.0/16 via 172.30.32.1

################
# Auto restart #
################

if bashio::config.true 'auto_restart'; then

    bashio::log.info "Auto restarting addon if openvpn down"
    (set -o posix; export -p) > /env.sh
    chmod 777 /env.sh
    chmod +x /usr/bin/restart_addon
    sed -i "1a . /env.sh; /usr/bin/restart_addon >/proc/1/fd/1 2>/proc/1/fd/2" /etc/openvpn/tunnelDown.sh

fi

if [ -f /data/addonrestarted ]; then
    bashio::log.warning "Warning, transmission had failed and the addon has self-rebooted as 'auto_restart' option was on. Please check that it is still running"
    rm /data/addonrestarted
fi

#######################
# Run haugene scripts #
#######################

bashio::log.info "Running userscript"
chmod +x /etc/transmission/userSetup.sh
/./etc/transmission/userSetup.sh
echo ""

# Correct mullvad
if [ "$(bashio::config "OPENVPN_PROVIDER")" == "mullvad" ]; then
    bashio::log.info "Mullvad selected, copying script for IPv6 disabling"
    chown "$PUID:$PGID"  /opt/modify-mullvad.sh
    chmod +x  /opt/modify-mullvad.sh
    sed -i '$i/opt/modify-mullvad.sh' /etc/openvpn/start.sh
fi

bashio::log.info "Starting app"
/./etc/openvpn/start.sh & echo ""

#################
# Allow ingress #
#################

bashio::net.wait_for 9091 localhost 900
bashio::log.info "Ingress ready"
exec nginx
