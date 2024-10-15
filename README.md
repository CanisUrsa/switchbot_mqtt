# Switchbot Home Assistant Interface

An application that reads data from the Switchbot Devices to publish data to an MQTT server for usage with Home Assistant.

This code relies on data from [SwitchBotAPI-BLE](https://github.com/OpenWonderLabs/SwitchBotAPI-BLE) to parse BLE advertisement data as well as some manual reverse engineering in cases that the documentation is lacking. The sampled advertisement data is published to an MQTT server. Additionally it publishes the MQTT Home Assistant configuration data for automatic device and entity generation.

This code is intended to run on a Raspberry PI with BLE support.

# Installing

1. Make a copy of `config_template.ini` and name it `config.ini`.
2. Populate the `mqtt` section with your MQTT host, port. Username and password can be left blank if not configured. You can also change the topic prefix if desired, this can be useful if you have multiple PVS installations.
3. Populate the `meter`, `io_thermohydro`, and `plug_mini` sections with the name of the device and MAC address of the device.
4. If you do not want to enable home assistant configuration data it can be disabled by setting `send_config` to `False`.
5. If you are using a `plug_mini` then you can enable persistence through the `persistence` section. This will save energy information between executions of the code.
6. Give `run.sh` the ability to be executed using `chmod`.

# Executing

1. Execute `run.sh`. This will create the python virtual environment and install all required python dependencies if required and then run the application.

# Setting up a service

The code can be setup to run as a service by creating a service file, enabling the service, and finally starting the service. Before this is done you should manually execute `run.sh` to make sure the virtual environment is created properly and is publishing data. After ensuring everything is working cancel the script with **CTRL+C** before continuing.

1. Generate the system file `/lib/systemd/system/switchbot_mqtt.service`.
Note you may need to change the **ExecStart** field in the service file.
```
[Unit]
Description=Switchbot MQTT Interface
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=15
User=root
ExecStart=/home/pi/code/switchbot_mqtt/run.sh

[Install]
WantedBy=multi-user.target
```
2. Reload the daemon with `sudo systemctl daemon-reload`.
3. Enable the service with `sudo systemctl enable switchbot_mqtt.service`
4. Start the service with `sudo systemctl start switchbot_mqtt.service`
5. Verify the service is running by watching `systemctl status switchbot_mqtt.service` and making sure **Active** indicates **running** and it has been running for at least 1 minute.

# Known Issues
- Integration of plug mini power to energy happens when processing the BLE advertisement. The worse the connection to the plug the less accurate the integration will be.