# 🧩 IOT Hub Home Assistant Add-on

One local control centre for Sonoff (eWeLink) and Tuya / Smart Life devices. Devices are controlled directly on your network; the cloud is only the backup.

✅ Uses the image: cbothma/iot-hub (amd64 + arm64)  
✅ Sonoff and Tuya in one place, LAN first, cloud as backup  
✅ Tuya without a developer account: one QR scan in the Smart Life app  
✅ New devices added in the Sonoff or Smart Life app appear by themselves  
✅ Connects to Home Assistant by itself, no token needed  
✅ Persistent storage: logins, device keys and settings survive updates

🌍 Web UI:  
Open it from the add-on page (**Open Web UI**) or at `http://<home-assistant-ip>:3000`

### Changing the port
If port 3000 is already used on your Home Assistant host (the log shows `address already in use :::3000`), set a free port in **Configuration > port**, then set the same number under **Network** so the **Open Web UI** button uses it, and restart the add-on. The **Network** box alone does not move the port: the add-on runs on the host network, where port mappings are ignored.

⚙️ First-time setup (all in the Web UI):  
1. **Account** page: log in with your eWeLink account (Sonoff devices).  
2. **Tuya** page: press **Show QR code**, then in the Smart Life app tap **+ > Scan** and confirm.  
3. **Settings > Tuya connection**: switch on **Publish Tuya devices to Home Assistant**. If you use LocalTuya or Home Assistant's own Tuya integration, disable it first, otherwise every Tuya device shows up twice.

📝 Notes:  
- Runs on the host network: device discovery needs it.  
- Only one app at a time can control a device locally. Remove SonoffLAN, LocalTuya or the old eWeLink add-on for the devices the hub takes over; the hub keeps their entity IDs so automations keep working.  
- Set a Web UI password under **Settings > System** if others share your network.
