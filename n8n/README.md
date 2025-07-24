Installation

    Add my Hass.io add-ons repository to your Hass.io instance.
    Click the Save button to store your configuration.
    Start the add-on.
    Add-on will fail, that is ok
    ssh into your homeassistant and run chmod 2777 /addon_configs/2effc9b9_n8n
    start add-on
    Check the logs of the add-on to see if everything went well.
    Open WebUI should work via :port.
    Setup administrator account
    Settings will be in /addon_configs/2effc9b9_n8n

Configuration

port : 5678 #port you want to run on.

Webui can be found at <your-ip>:port.
