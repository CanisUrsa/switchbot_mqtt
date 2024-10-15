import asyncio
import configparser
import json
import os
import time

from bleak import BleakScanner
import paho.mqtt.publish as publish

from enum import Enum

config_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "config.ini")
config = configparser.ConfigParser()
config.optionxform = str
config.read(config_path)

MQTT_ENABLED = config["mqtt"].getboolean("enabled")
MQTT_PUBLISH_PERIOD = float(config["mqtt"]["publish_period"])
MQTT_HOST = config["mqtt"]["host"]
MQTT_PORT = int(config["mqtt"]["port"])
MQTT_USERNAME = config["mqtt"]["username"]
MQTT_PASSWORD = config["mqtt"]["password"]
MQTT_TOPIC_PREFIX = config["mqtt"]["topic_prefix"]

HOMEASSISTANT_SEND_CONFIG = config['homeassistant'].getboolean("send_config")

PERSISTENCE_ENABLED = config["persistence"].getboolean("enabled")
PERSISTENCE_SAVE_PERIOD = int(config["persistence"]["save_period"])
PERSISTENCE_PATH = config["persistence"]["path"]

METER_DEVICES = { name.replace("_", " "):config['meter'][name] for name in config['meter'] }
METER_ADDRESSES = [ METER_DEVICES[name] for name in METER_DEVICES ]

IO_THERMOHYDRO_DEVICES = { name.replace("_", " "):config['io_thermohydro'][name] for name in config['io_thermohydro'] }
IO_THERMOHYDRO_ADDRESSES = [ IO_THERMOHYDRO_DEVICES[name] for name in IO_THERMOHYDRO_DEVICES ]

PLUG_MINI_DEVICES = { name.replace("_", " "):config['plug_mini'][name] for name in config['plug_mini'] }
PLUG_MINI_ADDRESSES = [ PLUG_MINI_DEVICES[name] for name in PLUG_MINI_DEVICES ]

ADDRESS_TO_NAME = { }
ADDRESS_TO_TYPE = { }
for device_type in [METER_DEVICES, IO_THERMOHYDRO_DEVICES, PLUG_MINI_DEVICES]:
    for name, address in device_type.items():
        ADDRESS_TO_NAME[address] = name
        ADDRESS_TO_TYPE[address] = lambda : device_type

UUID_REQUEST = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
UUID_RESPONSE = "cba20003-224d-11e6-9fb8-0002a5d5c51b"
UUID_BROADCAST = "0000fd3d-0000-1000-8000-00805f9b34fb"

class SwitchbotDeviceType(Enum):
    BOT = 0x48              # Not supported
    METER = 0x54
    CURTAIN = 0x63          # Not supported
    CONTACT_SENSOR = 0x64   # Not supported
    HUMIDIFIER = 0x65       # Not supported
    PLUG_MINI = 0x67
    METER_PLUS = 0x69
    SMART_LOCK = 0x6F       # Not supported
    LED_STRIP = 0x72        # Not supported
    MOTION_SENSOR = 0x73    # Not supported
    COLOR_BULB = 0x75       # Not supported
    IO_THERMOHYDRO = 0x77
    CURTAIN_3 = 0x7B        # Not supported

SwitchbotDeviceTypeValues = [item.value for item in SwitchbotDeviceType]
SwitchbotDeviceTypeNames = [item.name for item in SwitchbotDeviceType]

SWITCHBOT_METADATA = {
    SwitchbotDeviceType.METER: {
        "name": "Meter",
        "fields": {
            "rssi":               { "name": "Linkquality",        "state_class": "measurement", "device_class": "signal_strength", "unit_of_measurement": "dB" },
            "battery":            { "name": "Battery",            "state_class": "measurement", "device_class": "battery",         "unit_of_measurement": "%"},
            "temperature":        { "name": "Temperature",        "state_class": "measurement", "device_class": "temperature",     "unit_of_measurement": "°C" },
            "humidity":           { "name": "Humidity",           "state_class": "measurement", "device_class": "humidity",        "unit_of_measurement": "%" },
            "available":          { "name": "Available",          "state_class": None,          "device_class": None,              "unit_of_measurement": None },
        }
    },
    SwitchbotDeviceType.METER_PLUS: {
        "name": "Meter Plus",
        "fields": {
            "rssi":               { "name": "Linkquality",        "state_class": "measurement", "device_class": "signal_strength", "unit_of_measurement": "dB" },
            "battery":            { "name": "Battery",            "state_class": "measurement", "device_class": "battery",         "unit_of_measurement": "%"},
            "temperature":        { "name": "Temperature",        "state_class": "measurement", "device_class": "temperature",     "unit_of_measurement": "°C" },
            "humidity":           { "name": "Humidity",           "state_class": "measurement", "device_class": "humidity",        "unit_of_measurement": "%" },
            "available":          { "name": "Available",          "state_class": None,          "device_class": None,              "unit_of_measurement": None },
        }
    },
    SwitchbotDeviceType.IO_THERMOHYDRO: {
        "name": "IO Thermohydro",
        "fields": {
            "rssi":               { "name": "Linkquality",        "state_class": "measurement", "device_class": "signal_strength", "unit_of_measurement": "dB" },
            "battery":            { "name": "Battery",            "state_class": "measurement", "device_class": "battery",         "unit_of_measurement": "%"},
            "temperature":        { "name": "Temperature",        "state_class": "measurement", "device_class": "temperature",     "unit_of_measurement": "°C" },
            "humidity":           { "name": "Humidity",           "state_class": "measurement", "device_class": "humidity",        "unit_of_measurement": "%" },
            "available":          { "name": "Available",          "state_class": None,          "device_class": None,              "unit_of_measurement": None },
        }
    },
    SwitchbotDeviceType.PLUG_MINI: {
        "name": "Plug Mini",
        "fields": {
            "rssi":               { "name": "Linkquality",        "state_class": "measurement", "device_class": "signal_strength", "unit_of_measurement": "dB" },
            "power":              { "name": "Power",              "state_class": "measurement", "device_class": "power",           "unit_of_measurement": "kW" },
            "energy":             { "name": "Energy",             "state_class": "measurement", "device_class": "energy",          "unit_of_measurement": "kWh" },
            "enabled":            { "name": "Enabled",            "state_class": None,          "device_class": None,              "unit_of_measurement": None },
            "available":          { "name": "Available",          "state_class": None,          "device_class": None,              "unit_of_measurement": None },
        }
    },
}

SWITCHBOT_DATA = { }
SWITCHBOT_PERSISTENCE = { }


def make_device_key(device_type, address):
    return f"{device_type}-{address}"


def split_device_key(device_key):
    tokens = device_key.split("-")
    return tokens[0], tokens[1]


def get_safe_name(name):
    return name.lower().replace(" ", "_").replace(":", "_")


def get_safe_device_key(device_key):
    return device_key.replace(":", "_")


async def switchbot_scan_unknown():
    def process_advertisement(device, data):
        timestamp = time.time()
        address = device.address
        rssi = data.rssi
        if UUID_BROADCAST not in data.service_data:
            return
        buffer = [int(x) for x in data.service_data[UUID_BROADCAST]]
        byte0_reserved = (buffer[0] & 0x80) >> 7
        device_type = buffer[0] & 0x7F
        if device_type in SwitchbotDeviceTypeValues:
            device_type = SwitchbotDeviceType(device_type)
            is_unknown = False
            if device_type in [SwitchbotDeviceType.METER, SwitchbotDeviceType.METER_PLUS]:
                if address not in METER_ADDRESSES:
                    is_unknown = True
            elif device_type == SwitchbotDeviceType.IO_THERMOHYDRO:
                if address not in IO_THERMOHYDRO_ADDRESSES:
                    is_unknown = True
            elif device_type == SwitchbotDeviceType.PLUG_MINI:
                if address not in PLUG_MINI_ADDRESSES:
                    is_unknown = True
            else:
                is_unknown = True
            if is_unknown:
                line = f"{device_type.name}: {address} {rssi} | SD "
                for key, value in data.service_data.items():
                    value = ''.join([f'{int(x):02X}' for x in value])
                    line += f"{key}: {value} "
                line += "| MD "
                for key, value in data.manufacturer_data.items():
                    value = ''.join([f'{int(x):02X}' for x in value])
                    line += f"{key}: {value} "
                print(line)
        else:
            print(f"Unknown device type {device_type}")

    scanner = BleakScanner(process_advertisement)
    await scanner.start()
    while True:
        await asyncio.sleep(1)


async def switchbot_sample():
    def advertisement_callback(device, data):
        global SWITCHBOT_DATA
        global PLUG_MINI_DATA

        timestamp = time.time()
        address = device.address
        if address not in ADDRESS_TO_NAME:
            return
        if UUID_BROADCAST not in data.service_data:
            return
        name = ADDRESS_TO_NAME[address]
        rssi = data.rssi
        sd_buffer = [int(x) for x in data.service_data[UUID_BROADCAST]]
        sd_byte0_reserved = (sd_buffer[0] & 0x80) >> 7
        device_type = sd_buffer[0] & 0x7F
        if device_type in SwitchbotDeviceTypeValues:
            device_type = SwitchbotDeviceType(device_type)
            key = make_device_key(device_type.name, address)
            if device_type in [SwitchbotDeviceType.METER, SwitchbotDeviceType.METER_PLUS]:
                sd_byte1_reserved = (sd_buffer[1] & 0xF0) >> 4
                group_d = (sd_buffer[1] & 0x08) != 0
                group_c = (sd_buffer[1] & 0x04) != 0
                group_b = (sd_buffer[1] & 0x02) != 0
                group_a = (sd_buffer[1] & 0x01) != 0
                sd_byte2_reserved = (sd_buffer[2] & 0x80) >> 7
                battery = (sd_buffer[2] & 0x7F)
                temperature_alert_high = (sd_buffer[3] & 0x80) != 0
                temperature_alert_low = (sd_buffer[3] & 0x40) != 0
                humidity_alert_high = (sd_buffer[3] & 0x20) != 0
                humidity_alert_low = (sd_buffer[3] & 0x10) != 0
                fractional_temperature = sd_buffer[3] & 0x0F
                temperature_negative = (sd_buffer[4] & 0x80) == 0
                temperature_integer = sd_buffer[4] & 0x7F
                temperature_c = (sd_buffer[5] & 0x80) == 0
                temperature = temperature_integer + fractional_temperature * 0.1
                humidity = sd_buffer[5] & 0x7F
                if temperature_negative:
                    temperature_integer *= -1
                if key not in SWITCHBOT_DATA:
                    SWITCHBOT_DATA[key] = { }
                SWITCHBOT_DATA[key]['rssi'] = rssi
                SWITCHBOT_DATA[key]['battery'] = battery
                SWITCHBOT_DATA[key]['temperature'] = temperature
                SWITCHBOT_DATA[key]['humidity'] = humidity
                SWITCHBOT_DATA[key]['last_advertisement'] = timestamp
            elif device_type == SwitchbotDeviceType.IO_THERMOHYDRO:
                sd_byte1 = sd_buffer[1] # Unknown
                sd_byte2_reserved = (sd_buffer[2] & 0x80) >> 7
                sd_byte2_reserved = (sd_buffer[2] & 0x80) >> 7
                battery = (sd_buffer[2] & 0x7F)
                
                md_buffer = [int(x) for x in data.manufacturer_data[2409]]
                mac_address = md_buffer[0:6]
                md_byte6_reserved = (md_buffer[6] & 0x80) >> 7
                md_byte6_unknown = (md_buffer[6] & 0x7F)
                md_byte7_unknown = md_buffer[7]
                temperature_fraction = md_buffer[8] & 0x0F
                temperature_sign = (md_buffer[9] & 0x80) == 0
                temperature_whole = md_buffer[9] & 0x7F
                temperature = temperature_whole + temperature_fraction * 0.1
                if temperature_sign:
                    temperature *= -1
                temperature_c = (md_buffer[10] & 0x80) == 0
                humidity = md_buffer[10] & 0x7F
                md_byte11_unknown = md_buffer[11]
                if key not in SWITCHBOT_DATA:
                    SWITCHBOT_DATA[key] = { }
                SWITCHBOT_DATA[key]['rssi'] = rssi
                SWITCHBOT_DATA[key]['battery'] = battery
                SWITCHBOT_DATA[key]['temperature'] = temperature
                SWITCHBOT_DATA[key]['humidity'] = humidity
                SWITCHBOT_DATA[key]['last_advertisement'] = timestamp
            elif device_type == SwitchbotDeviceType.PLUG_MINI:
                sd_byte1 = sd_buffer[1] # Unknown
                sd_byte2_reserved = (sd_buffer[2] & 0x80) >> 7
                sd_byte2_reserved = (sd_buffer[2] & 0x80) >> 7
                battery = (sd_buffer[2] & 0x7F)

                md_buffer = [int(x) for x in data.manufacturer_data[2409]]
                mac_address = md_buffer[0:6]
                sequence_number = md_buffer[6]
                on = (md_buffer[7] & 0x80) != 0
                delay = (md_buffer[8] & 0x01) != 0
                timer = (md_buffer[8] & 0x02) != 0
                utc = (md_buffer[8] & 0x04) != 0
                wifi_rssi = md_buffer[9]
                overload = (md_buffer[10] & 0x80) != 0
                power = (((md_buffer[10] & 0x7F) << 8) + md_buffer[11]) * 0.1 # Watts
                power = power / 1000.0 # Kilowatts
                if key not in SWITCHBOT_DATA:
                    SWITCHBOT_DATA[key] = { }
                if 'energy' not in SWITCHBOT_DATA[key]:
                    SWITCHBOT_DATA[key]['energy'] = SWITCHBOT_PERSISTENCE[key]['energy'] if key in SWITCHBOT_PERSISTENCE else 0.0
                elif 'last_advertisement' in SWITCHBOT_DATA[key] and 'power' in SWITCHBOT_DATA[key]:
                    time_delta = (timestamp - SWITCHBOT_DATA[key]['last_advertisement']) / 3600.0 # Hours
                    min_power = min(power, SWITCHBOT_DATA[key]['power'])
                    max_power = max(power, SWITCHBOT_DATA[key]['power'])
                    energy = 0.5 * time_delta * (max_power - min_power) + time_delta * min_power # Kilowatt-hours
                    SWITCHBOT_DATA[key]['energy'] += energy
                SWITCHBOT_DATA[key]['rssi'] = rssi
                SWITCHBOT_DATA[key]['power'] = power
                SWITCHBOT_DATA[key]['enabled'] = on
                SWITCHBOT_DATA[key]['last_advertisement'] = timestamp
                if key not in SWITCHBOT_PERSISTENCE:
                    SWITCHBOT_PERSISTENCE[key] = { }    
                SWITCHBOT_PERSISTENCE[key]['energy'] = SWITCHBOT_DATA[key]['energy']
    scanner = BleakScanner(advertisement_callback)
    await scanner.start()
    while True:
        await asyncio.sleep(1)


def homeassistant_device_config(device_key, model, name, address):
    return {
        "connections": [["mac", address]],
        # "hw_version" "",
        "identifiers": [get_safe_name(f"{MQTT_TOPIC_PREFIX}_{device_key}")],
        "manufacturer": "Switchbot",
        "model": model,
        # "model_id": "",
        "name": name,
        # "serial_number": serial_number,
        # "suggested_area": "",
        # "sw_version": "",
        # "via_device": "",
    }


def homeassistant_config(device_config, device_key, field, name, state_class, device_class, unit_of_measurement):
    device_type, address = split_device_key(device_key)
    fixed_address = address.replace("_", ":")
    device_name = ADDRESS_TO_NAME[fixed_address]
    payload_json = {
        "unique_id": get_safe_name(f"{MQTT_TOPIC_PREFIX}_{get_safe_name(device_type)}_{get_safe_name(device_name)}_{get_safe_name(field)}"),
        "object_id": get_safe_name(f"{MQTT_TOPIC_PREFIX}_{get_safe_name(device_type)}_{get_safe_name(device_name)}_{get_safe_name(field)}"),
        "name": name,
        "state_topic": f"{MQTT_TOPIC_PREFIX}/{get_safe_name(device_type)}_{get_safe_name(device_name)}/data",
        "value_template": "{{ value_json." + field + " }}",
        "device": device_config,
        "availability_topic": f"{MQTT_TOPIC_PREFIX}/{get_safe_name(device_type)}_{get_safe_name(device_name)}/data",
        "availability_template": "{{ value_json.available }}",
    }
    if state_class is not None:
        payload_json["state_class"] = state_class
    if device_class is not None:
        payload_json["device_class"] = device_class
    if unit_of_measurement is not None:
        payload_json["unit_of_measurement"] = unit_of_measurement
    return {
        "topic": f"homeassistant/sensor/{MQTT_TOPIC_PREFIX}_{get_safe_name(device_type)}_{get_safe_name(device_name)}/{field}/config",
        "payload": json.dumps(payload_json)
    }


async def mqtt_publish():
    target_time = time.time() + MQTT_PUBLISH_PERIOD
    while True:
        if not MQTT_ENABLED:
            pass
        else:
            messages = []
            for device_key, data in SWITCHBOT_DATA.items():
                safe_device_key = device_key.replace(":", "_")
                device_type, address = split_device_key(device_key)
                device_type = SwitchbotDeviceType[device_type]
                fixed_address = address.replace("_", ":")
                device_name = ADDRESS_TO_NAME[fixed_address]
                data["available"] = "online" if (time.time() - data["last_advertisement"]) < 60 else "offline"
                for prefix in SWITCHBOT_METADATA:
                    if device_type == prefix:
                        model = SWITCHBOT_METADATA[prefix]["name"]
                        device_config = homeassistant_device_config(safe_device_key, model, device_name, fixed_address)
                        for field in SWITCHBOT_METADATA[prefix]["fields"]:
                            field_data = SWITCHBOT_METADATA[prefix]["fields"][field]
                            field_config = homeassistant_config(device_config, safe_device_key, field, field_data["name"], field_data["state_class"], field_data["device_class"], field_data["unit_of_measurement"])
                            if HOMEASSISTANT_SEND_CONFIG:
                                messages.append(field_config)
                messages.append({ "topic": f"{MQTT_TOPIC_PREFIX}/{get_safe_name(device_type.name)}_{get_safe_name(device_name)}/data", "payload": json.dumps(data) })
            if len(messages) > 0:
                auth = None
                if MQTT_USERNAME != "":
                    auth = { "username": MQTT_USERNAME, "password": MQTT_PASSWORD }
                publish.multiple(messages, hostname=MQTT_HOST, port=MQTT_PORT, auth=auth)
        sleep_time = target_time - time.time()
        await asyncio.sleep(sleep_time)
        target_time += MQTT_PUBLISH_PERIOD


async def save_persistence():
    while PERSISTENCE_ENABLED:
        await asyncio.sleep(PERSISTENCE_SAVE_PERIOD)
        with open(PERSISTENCE_PATH, "w") as f:
            json.dump(SWITCHBOT_PERSISTENCE, f)


async def main():
    if PERSISTENCE_ENABLED:
        if os.path.exists(PERSISTENCE_PATH):
            with open(PERSISTENCE_PATH, "r") as f:
                SWITCHBOT_PERSISTENCE = json.load(f)

    await asyncio.gather(switchbot_sample(), mqtt_publish(), save_persistence())


asyncio.run(main())

# async def meter_loop(name, address):
#     # Get device for meter
#     device = None
#     while True:
#         try:
#             device = await BleakScanner.find_device_by_address(address)
#             if device is None:
#                 await asyncio.sleep(5)
#                 continue
#             else:
#                 break
#         except:
#             await asyncio.sleep(5)
#     # Get client for meter
#     client = BleakClient(device)
#     while True:
#         # Connect to meter
#         if not client.is_connected:
#             # Keep retrying to connect regardless of error
#             while True:
#                 try:
#                     await client.connect()
#                     await client.start_notify(UUID_RESPONSE, device_response)
#                     break
#                 except:
#                     await asyncio.sleep(5)
#         # Send request to meter forever
#         try:
#             while True:
#                 # Meter request
#                 packet = bytearray([0x57, 0x0F, 0x31]) # Read Display Mode and Value of Meter
#                 # Append name to response queue
#                 queue.append(name)
#                 await client.write_gatt_char(UUID_REQUEST, packet, response=True)
#                 await asyncio.sleep(5)
#         except:
#             queue.pop(len(queue)-1)
#             await asyncio.sleep(5)