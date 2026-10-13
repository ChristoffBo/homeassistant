## 1.5.1 (2026-10-13)
- New option **port** (default 3000): the port the Web UI listens on. Fixes the add-on failing to start with "address already in use :::3000" when something else on the host already uses port 3000
- The add-on runs on the host network, where the port box under **Network** has no effect; change **port** under **Configuration** instead, and set the **Network** port to the same number so the **Open Web UI** button points at it
- Docker Image: [cbothma/iot-hub:1.5.1](https://hub.docker.com/r/cbothma/iot-hub/tags)

## 1.5.0 (2026-10-12)
- First release as a Home Assistant add-on
- Compact device cards: name, Sonoff/Tuya marker, Online/Offline and LAN/Cloud at a glance, one-tap switching; tap a device for all its details
- Connects to Home Assistant through the Supervisor, no token needed
- Docker Image: [cbothma/iot-hub:1.5.0](https://hub.docker.com/r/cbothma/iot-hub/tags)
