# BMW CarData Home Assistant Add-ons

## Installation

[![Open your Home Assistant instance and show the add add-on repository dialog with this repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmaxcerny%2Fha-addon-bmw-cardata-mqtt-bridge)

Click the button above, confirm adding the repository, then install **BMW CarData MQTT Bridge** and follow its Documentation tab.

Or manually:

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
2. Open the ⋮ menu → **Repositories** and add `https://github.com/maxcerny/ha-addon-bmw-cardata-mqtt-bridge`.
3. Install **BMW CarData MQTT Bridge** and follow its Documentation tab.

For a local install without GitHub, copy the `bmw_cardata_bridge` folder into
the `/addons` share of your Home Assistant (e.g. via the Samba or SSH add-on),
then click **Check for updates** in the Add-on Store. It appears under
*Local add-ons*.

## Add-ons

- [BMW CarData MQTT Bridge](bmw_cardata_bridge/) – based on
  [dj0abr/bmw-mqtt-bridge](https://github.com/dj0abr/bmw-mqtt-bridge) (MIT).
