# BMW CarData MQTT Bridge

This add-on runs [bmw-mqtt-bridge](https://github.com/dj0abr/bmw-mqtt-bridge)
by DJ0ABR. It connects to BMW's official **CarData streaming** MQTT interface
and republishes your car's data to your local MQTT broker, where Home Assistant
can use it.

## 1. Get your BMW IDs

1. Log in at the [MyBMW website](https://www.bmw-connecteddrive.com/). Your car
   must be registered to your account.
2. Go to **Personal Data → My Vehicles → CarData**.
3. Click **Create Client ID** (do *not* click "Authenticate Vehicle"). Copy the
   Client ID into the add-on option **client_id**.
4. Scroll down to **CARDATA STREAM → Show Connection Details**. Copy the
   **USERNAME** into the add-on option **gcid**.
5. Under **CARDATA STREAM**, click **Change data selection** and enable the data
   points you want to receive. You only receive what you select here.

## 2. Log in to BMW

Start the add-on. On the first start it asks BMW for a login code and shows a
link:

- as a **notification** in Home Assistant, and
- in the add-on **Log** tab.

Open the link, log in with your BMW account and approve access. The add-on
notices this within a few seconds, stores the tokens and starts the bridge. If
the link expires before you use it, a new one is created automatically.

From then on, tokens are refreshed automatically. If BMW ever rejects the
stored login, the add-on starts a new login and notifies you again. To force a
new login (for example after changing the data selection or the BMW account),
turn on **reauthenticate** and restart the add-on.

## 3. MQTT broker

If you use the **Mosquitto broker** add-on, nothing needs to be configured: the
add-on gets the broker address and credentials from Home Assistant. For another
broker, set **mqtt_host**, **mqtt_port**, **mqtt_user** and **mqtt_password**.
TLS connections to the local broker are not supported.

## Topics

With the default prefix `bmw/`:

| Topic | Content |
|---|---|
| `bmw/status` | `true` / `false`: is the bridge connected to BMW (always retained) |
| `bmw/raw/<VIN>/<event>` | the message exactly as BMW sends it |
| `bmw/vehicles/<VIN>/<field>` | one topic per data field, e.g. `{"value":62.5,"unit":"%","timestamp":...}` (only with **split_topics**) |

BMW only sends data when something changes in the car, so it can take a while
until the first values appear. Use **MQTT Explorer** or
*Settings → Devices & services → MQTT → Configure → Listen to a topic* with
`bmw/#` to see what your car sends.

## Home Assistant entities

There are three ways to get entities:

- **BMW CarData integration** ([bmw-cardata-ha](https://github.com/kvanbiesen/bmw-cardata-ha)):
  it creates its own entities. Leave **ha_discovery** off to avoid duplicates.
- **ha_discovery: true**: the add-on announces every data field via MQTT
  discovery. You get one **BMW** device with sensors such as
  `sensor.bmw_fuel_level`, `sensor.bmw_range`, `sensor.bmw_mileage`,
  `binary_sensor.bmw_lock`, door/window/hood binary sensors, tyre pressures in
  bar and `device_tracker.bmw_location`. Fields without a built-in definition
  get a generic entity named after the field. Needs **split_topics**.
  Entities appear as soon as BMW sends the field for the first time.
- **Manual MQTT sensors** in `configuration.yaml`, as below.

### Manual sensor example

Use the field names you see on your broker:

```yaml
mqtt:
  binary_sensor:
    - name: "BMW connected"
      state_topic: "bmw/status"
      payload_on: "true"
      payload_off: "false"
      device_class: connectivity
  sensor:
    - name: "BMW battery"
      state_topic: "bmw/vehicles/YOUR_VIN/vehicle.drivetrain.batteryManagement.header"
      value_template: "{{ value_json.value }}"
      unit_of_measurement: "%"
      device_class: battery
```

## Options

| Option | Description |
|---|---|
| `client_id` | CarData Client ID (required) |
| `gcid` | CarData stream USERNAME (required) |
| `topic_prefix` | Prefix for all local topics, default `bmw/` |
| `split_topics` | Publish one topic per data field |
| `mqtt_retain` | Publish data topics retained |
| `status_stable_delay` | Seconds the BMW connection must be down before `status` becomes `false` |
| `reauthenticate` | Start a new BMW login on next start (switches itself off) |
| `ha_discovery` | Create Home Assistant entities via MQTT discovery (off by default) |
| `discovery_prefix` | Home Assistant's MQTT discovery prefix, default `homeassistant` |
| `mqtt_host`, `mqtt_port`, `mqtt_user`, `mqtt_password` | Only for brokers other than the Mosquitto add-on |
| `bmw_host`, `bmw_port` | Advanced: BMW streaming endpoint |

## Credits

Bridge by Kurt, DJ0ABR – MIT License.
