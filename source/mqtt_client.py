import logging
import logging.config
import random
import ssl
import time

from docker_secrets import getDocketSecrets
import paho.mqtt.client as mqtt
from check_service import checkService

logger = logging.getLogger()

userId = getDocketSecrets("iotcloud_userId")
locationId = getDocketSecrets("iotcloud_locationId")
deviceId = getDocketSecrets("iotcloud_deviceId")
mqttToken = getDocketSecrets("iotcloud_mqtt_device_token")
analogSensorId = "healthcheck_analog"
switchSensorId = "healthcheck_toogle"

url = "mqtt.iotcloud.es"
mqttHeader = f"v1/{locationId}/{deviceId}/"
switchState = False


def on_connect(client, userdata, flags, rc):
    logger.info(f"Connected with result code: {rc}")
    client.subscribe(mqttHeader + switchSensorId + "/setState")
    client.publish(mqttHeader + "status", "online", retain=True)
    client.publish(mqttHeader + switchSensorId + "/aux/switch", "v1.0", retain=True)


def on_disconnect(client, userdata, rc):
    logger.info(f"Disconnected result code: {rc}")


def on_message(client, userdata, msg):
    msg.payload = msg.payload.decode("utf-8")
    global switchState
    switchState = msg.payload == "True"


@checkService("MQTT")
def sendValue():
    if client.is_connected():
        client.publish(mqttHeader + analogSensorId + "/value", random.random() * 100.0)


def notifySwitchUpdated():
    if client.is_connected():
        client.publish(mqttHeader + switchSensorId + "/updatedSensor", f'"{userId}"')


def waitForSwitchState(state: bool):
    # Wait for the switch to change state
    responseTime = 0
    timeout = 10
    while responseTime < timeout:
        if switchState == state:
            break
        time.sleep(0.1)
        responseTime += 0.1
    if responseTime >= timeout:
        raise TimeoutError("The switch did not change in the expected time period")


client = mqtt.Client(client_id="HealthChecker", transport="websockets")
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message
client.will_set(mqttHeader + "status", "offline", retain=True)
client.username_pw_set(mqttToken, "_")
client.tls_set(
    ca_certs=None,
    certfile=None,
    keyfile=None,
    cert_reqs=ssl.CERT_REQUIRED,
    tls_version=ssl.PROTOCOL_TLSv1_2,
)

def stop():
    client.disconnect()
    client.loop_stop()

client.connect(url, 443, 30)
client.loop_start()
