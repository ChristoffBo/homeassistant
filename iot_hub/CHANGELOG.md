## 1.5.1 - Ingress (2026-10-13)
- Home Assistant Ingress: the Web UI opens inside Home Assistant (sidebar panel **IOT Hub**), so it also works away from home through Home Assistant Cloud / Nabu Casa
- Only Home Assistant's own proxy can use the Ingress connection; you are already logged in through Home Assistant, so the hub's Web UI password is not asked there
- The direct port (default 3000) keeps working on your home network
- After updating the repository: on the add-on page use **Rebuild** so the add-on picks this up

## 1.5.1 (2026-10-13)
- New option **port** (default 3000): the port the Web UI listens on. Fixes the add-on failing to start with "address already in use :::3000" when something else on the host already uses port 3000
- The add-on runs on the host network, where the port box under **Network** has no effect; change **port** under **Configuration** instead, and set the **Network** port to the same number so the **Open Web UI** button points at it
- Docker Image: [cbothma/iot-hub:1.5.1](https://hub.docker.com/r/cbothma/iot-hub/tags)

## 1.5.0 (2026-10-12)
- First release as a Home Assistant add-on
- Compact device cards: name, Sonoff/Tuya marker, Online/Offline and LAN/Cloud at a glance, one-tap switching; tap a device for all its details
- Connects to Home Assistant through the Supervisor, no token needed
- Docker Image: [cbothma/iot-hub:1.5.0](https://hub.docker.com/r/cbothma/iot-hub/tags)
