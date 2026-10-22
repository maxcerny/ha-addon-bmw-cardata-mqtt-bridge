"""Home Assistant MQTT discovery for the BMW CarData bridge (optional).

For setups without the BMW CarData integration (bmw-cardata-ha): that
integration creates its own entities, so leave this off when you use it.

The bridge republishes every CarData field on its own retained topic
(<prefix>vehicles/<VIN>/<field>, payload {"value": ..., "unit": ..., "timestamp": ...}).
This service watches those topics and, the first time it sees a field,
publishes a retained discovery config so HA creates an entity for it. One HA
device per VIN.

Known fields (FIELDS) get a proper name, entity id, device class and unit.
Anything else gets a generic entity: binary_sensor for booleans, sensor
otherwise, named after the field.

Latitude/longitude are combined into <prefix>location/<VIN> (retained) for
the device_tracker. <prefix>status (bridge connected to BMW) and the raw
message timestamp become a connectivity and a "last update" entity.

Config from the environment: MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASSWORD,
TOPIC_PREFIX (with trailing slash), DISCOVERY_PREFIX.
"""
import json
import os
import re

import paho.mqtt.client as mqtt

PREFIX = os.environ.get('TOPIC_PREFIX', 'bmw/')
DISCOVERY = os.environ.get('DISCOVERY_PREFIX', 'homeassistant')

# CarData unit -> HA unit
UNITS = {'percent': '%', 'kpa': 'kPa', 'l': 'L', 'km': 'km', 'min': 'min', 'h': 'h',
         'degrees': '°', 'kw': 'kW', 'kwh': 'kWh', 'v': 'V', 'a': 'A', 'celsius': '°C', 's': 's'}

LAT = 'vehicle.cabin.infotainment.navigation.currentLocation.latitude'
LON = 'vehicle.cabin.infotainment.navigation.currentLocation.longitude'
HEADING = 'vehicle.cabin.infotainment.navigation.currentLocation.heading'

ON_OFF = "{{ 'ON' if value_json.value else 'OFF' }}"
NOT_CLOSED = "{{ 'OFF' if value_json.value == 'CLOSED' else 'ON' }}"
BAR = '{{ (value_json.value | float / 100) | round(2) }}'


def opening(key, name, device_class='door'):
    return {'component': 'binary_sensor', 'key': key, 'name': name,
            'device_class': device_class, 'value_template': ON_OFF}


def window(key, name):
    return {'component': 'binary_sensor', 'key': key, 'name': name,
            'device_class': 'window', 'value_template': NOT_CLOSED}


def tire(key, name, enabled=True):
    return {'component': 'sensor', 'key': key, 'name': name, 'device_class': 'pressure',
            'unit_of_measurement': 'bar', 'value_template': BAR, 'state_class': 'measurement',
            'suggested_display_precision': 1, 'enabled_by_default': enabled}


# field -> entity config; 'key' becomes the entity id: <component>.bmw_<key>
FIELDS = {
    # fuel / range / odometer
    'vehicle.drivetrain.fuelSystem.level': {
        'component': 'sensor', 'key': 'fuel_level', 'name': 'Fuel level', 'unit_of_measurement': '%',
        'icon': 'mdi:gas-station', 'state_class': 'measurement'},
    'vehicle.drivetrain.fuelSystem.remainingFuel': {
        'component': 'sensor', 'key': 'fuel_remaining', 'name': 'Fuel remaining', 'unit_of_measurement': 'L',
        'device_class': 'volume_storage', 'state_class': 'measurement'},
    'vehicle.drivetrain.lastRemainingRange': {
        'component': 'sensor', 'key': 'range', 'name': 'Range', 'unit_of_measurement': 'km',
        'device_class': 'distance', 'state_class': 'measurement', 'icon': 'mdi:map-marker-distance'},
    'vehicle.vehicle.travelledDistance': {
        'component': 'sensor', 'key': 'mileage', 'name': 'Mileage', 'unit_of_measurement': 'km',
        'device_class': 'distance', 'state_class': 'total_increasing', 'icon': 'mdi:counter'},
    # electric / hybrid
    'vehicle.drivetrain.batteryManagement.header': {
        'component': 'sensor', 'key': 'battery_level', 'name': 'Battery level', 'unit_of_measurement': '%',
        'device_class': 'battery', 'state_class': 'measurement'},
    'vehicle.drivetrain.electricEngine.kombiRemainingElectricRange': {
        'component': 'sensor', 'key': 'electric_range', 'name': 'Electric range', 'unit_of_measurement': 'km',
        'device_class': 'distance', 'state_class': 'measurement'},
    'vehicle.drivetrain.electricEngine.charging.status': {
        'component': 'sensor', 'key': 'charging_status', 'name': 'Charging status', 'icon': 'mdi:ev-station'},
    'vehicle.powertrain.electric.battery.stateOfCharge.target': {
        'component': 'sensor', 'key': 'charge_target', 'name': 'Charge target', 'unit_of_measurement': '%',
        'icon': 'mdi:battery-arrow-up', 'enabled_by_default': False},
    # locks, doors, windows, lids
    'vehicle.cabin.door.status': {
        'component': 'binary_sensor', 'key': 'lock', 'name': 'Lock', 'device_class': 'lock',
        'value_template': "{{ 'OFF' if value_json.value in ['SECURED', 'LOCKED'] else 'ON' }}"},
    'vehicle.cabin.door.row1.driver.isOpen': opening('door_driver', 'Driver door'),
    'vehicle.cabin.door.row1.passenger.isOpen': opening('door_passenger', 'Passenger door'),
    'vehicle.cabin.door.row2.driver.isOpen': opening('door_rear_driver', 'Rear driver door'),
    'vehicle.cabin.door.row2.passenger.isOpen': opening('door_rear_passenger', 'Rear passenger door'),
    'vehicle.cabin.window.row1.driver.status': window('window_driver', 'Driver window'),
    'vehicle.cabin.window.row1.passenger.status': window('window_passenger', 'Passenger window'),
    'vehicle.cabin.window.row2.driver.status': window('window_rear_driver', 'Rear driver window'),
    'vehicle.cabin.window.row2.passenger.status': window('window_rear_passenger', 'Rear passenger window'),
    'vehicle.cabin.sunroof.status': window('sunroof', 'Sunroof'),
    'vehicle.body.hood.isOpen': opening('hood', 'Hood', 'opening'),
    'vehicle.body.trunk.isOpen': opening('trunk', 'Trunk', 'opening'),
    'vehicle.body.trunk.door.isOpen': opening('tailgate', 'Tailgate', 'opening'),
    'vehicle.body.trunk.window.isOpen': opening('tailgate_window', 'Tailgate window', 'window'),
    # tyres
    'vehicle.chassis.axle.row1.wheel.left.tire.pressure': tire('tire_front_left', 'Tyre front left'),
    'vehicle.chassis.axle.row1.wheel.right.tire.pressure': tire('tire_front_right', 'Tyre front right'),
    'vehicle.chassis.axle.row2.wheel.left.tire.pressure': tire('tire_rear_left', 'Tyre rear left'),
    'vehicle.chassis.axle.row2.wheel.right.tire.pressure': tire('tire_rear_right', 'Tyre rear right'),
    'vehicle.chassis.axle.row1.wheel.left.tire.pressureTarget': tire('tire_front_left_target', 'Tyre front left target', False),
    'vehicle.chassis.axle.row1.wheel.right.tire.pressureTarget': tire('tire_front_right_target', 'Tyre front right target', False),
    'vehicle.chassis.axle.row2.wheel.left.tire.pressureTarget': tire('tire_rear_left_target', 'Tyre rear left target', False),
    'vehicle.chassis.axle.row2.wheel.right.tire.pressureTarget': tire('tire_rear_right_target', 'Tyre rear right target', False),
    # climate
    'vehicle.vehicle.preConditioning.activity': {
        'component': 'sensor', 'key': 'climatisation', 'name': 'Climatisation', 'icon': 'mdi:fan'},
    'vehicle.vehicle.preConditioning.remainingTime': {
        'component': 'sensor', 'key': 'climatisation_remaining', 'name': 'Climatisation remaining',
        'unit_of_measurement': 'min', 'device_class': 'duration'},
    'vehicle.vehicle.preConditioning.isRemoteEngineRunning': {
        'component': 'binary_sensor', 'key': 'remote_engine', 'name': 'Remote engine running',
        'device_class': 'running', 'value_template': ON_OFF},
    # position (lat/lon go to the device_tracker)
    HEADING: {
        'component': 'sensor', 'key': 'heading', 'name': 'Heading', 'unit_of_measurement': '°',
        'icon': 'mdi:compass', 'enabled_by_default': False},
}


def slug(text):
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', text)
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')


def generic(field, payload):
    """Entity config for a field that is not in FIELDS."""
    short = re.sub(r'^(vehicle\.)+', '', field)
    name = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', short).replace('.', ' ').lower()
    cfg = {'key': slug(short), 'name': name[:1].upper() + name[1:]}
    value = payload.get('value')
    if isinstance(value, bool):
        return {**cfg, 'component': 'binary_sensor', 'value_template': ON_OFF}
    cfg['component'] = 'sensor'
    unit = payload.get('unit')
    if unit:
        cfg['unit_of_measurement'] = UNITS.get(unit.lower(), unit)
    if isinstance(value, (int, float)):
        cfg['state_class'] = 'measurement'
    elif isinstance(value, (dict, list)):
        cfg['value_template'] = '{{ value_json.value | tojson | truncate(250) }}'
    return cfg


class Discovery:
    def __init__(self, client):
        self.client = client
        self.announced = set()     # (vin, key)
        self.position = {}         # vin -> {field: value}

    def device(self, vin):
        return {'identifiers': [f'bmw_cardata_{vin}'], 'name': 'BMW', 'manufacturer': 'BMW',
                'model': 'CarData', 'serial_number': vin}

    def announce(self, vin, cfg, state_topic=None, **extra):
        """Publish one entity's discovery config once per run."""
        cfg = dict(cfg)
        component, key = cfg.pop('component'), cfg.pop('key')
        if (vin, key) in self.announced:
            return
        self.announced.add((vin, key))
        config = {
            'device': self.device(vin),
            'unique_id': f'bmw_{vin}_{key}',
            'default_entity_id': f'{component}.bmw_{key}',
            'value_template': '{{ value_json.value }}',
            **cfg, **extra,
        }
        if state_topic:
            config['state_topic'] = state_topic
        config = {k: v for k, v in config.items() if v is not None or k == 'name'}
        self.client.publish(f'{DISCOVERY}/{component}/bmw_{vin}/{key}/config', json.dumps(config), retain=True)
        print(f'[discovery] {component}.bmw_{key} ({vin})', flush=True)

    def on_field(self, vin, field, payload):
        if field in (LAT, LON):
            self.on_position(vin, field, payload)
            return
        cfg = FIELDS.get(field) or generic(field, payload)
        self.announce(vin, cfg, f'{PREFIX}vehicles/{vin}/{field}',
                      json_attributes_topic=f'{PREFIX}vehicles/{vin}/{field}',
                      json_attributes_template='{{ {"timestamp": value_json.timestamp, "raw": value_json.value} | tojson }}')
        if field == HEADING:
            self.on_position(vin, field, payload)

    def on_position(self, vin, field, payload):
        pos = self.position.setdefault(vin, {})
        pos[field] = payload.get('value')
        pos['timestamp'] = payload.get('timestamp')
        if pos.get(LAT) is None or pos.get(LON) is None:
            return
        topic = f'{PREFIX}location/{vin}'
        self.client.publish(topic, json.dumps({
            'latitude': pos[LAT], 'longitude': pos[LON], 'heading': pos.get(HEADING),
            'gps_accuracy': 0, 'timestamp': pos['timestamp']}), retain=True)
        self.announce(vin, {'component': 'device_tracker', 'key': 'location', 'name': None,
                            'icon': 'mdi:car', 'source_type': 'gps'},
                      json_attributes_topic=topic, value_template=None)

    def on_raw(self, vin, payload):
        self.announce(vin, {'component': 'sensor', 'key': 'last_update', 'name': 'Last update',
                            'device_class': 'timestamp', 'value_template': '{{ value_json.timestamp }}'},
                      f'{PREFIX}raw/{vin}')
        self.announce(vin, {'component': 'binary_sensor', 'key': 'connected', 'name': 'Stream connected',
                            'device_class': 'connectivity', 'entity_category': 'diagnostic',
                            'value_template': "{{ 'ON' if value_json.connected else 'OFF' }}"},
                      f'{PREFIX}status')


def main():
    if hasattr(mqtt, 'CallbackAPIVersion'):   # paho >= 2
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    else:
        client = mqtt.Client()
    if os.environ.get('MQTT_USER'):
        client.username_pw_set(os.environ['MQTT_USER'], os.environ.get('MQTT_PASSWORD') or None)
    disc = Discovery(client)

    def on_connect(c, userdata, flags, rc):
        print(f'[discovery] connected to MQTT (rc={rc})', flush=True)
        c.subscribe([(f'{PREFIX}vehicles/+/+', 0), (f'{PREFIX}raw/+', 0)])

    def on_message(c, userdata, msg):
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        parts = msg.topic[len(PREFIX):].split('/')
        try:
            if parts[0] == 'vehicles' and len(parts) == 3:
                disc.on_field(parts[1], parts[2], payload)
            elif parts[0] == 'raw' and len(parts) == 2:
                disc.on_raw(parts[1], payload)
        except Exception as e:  # one odd message must not stop discovery
            print(f'[discovery] {msg.topic}: {e!r}', flush=True)

    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(1, 60)
    client.connect_async(os.environ.get('MQTT_HOST', 'localhost'), int(os.environ.get('MQTT_PORT', 1883)))
    client.loop_forever(retry_first_connection=True)


if __name__ == '__main__':
    main()
