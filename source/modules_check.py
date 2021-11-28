import logging
import logging.config
import time
from json.decoder import JSONDecodeError

from docker_secrets import getDocketSecrets
from check_service import checkService
import mqtt_client
import requests

logger = logging.getLogger()

session = requests.Session()

userId = getDocketSecrets("iotcloud_userId")
locationId = getDocketSecrets("iotcloud_locationId")
deviceId = getDocketSecrets("iotcloud_deviceId")
switchSensorId = "healthcheck_switch"
thermostatSensorId = "healthcheck_thermostat"


def updateSensorTimer(apiToken):

    headers = {"Authorization": f"Bearer {apiToken}"}

    # Turn of the switch for 5 seconds
    now = int(time.time())
    payload = {"sensorMetadata": {"timer": {"initialTimestamp": now, "duration": 5}}}

    response = session.put(
        f"https://api.iotcloud.es/api/v1/users/{userId}/locations/{locationId}/devices/{deviceId}/sensors/{switchSensorId}",
        json=payload,
        headers=headers,
    )

    try:
        decodedResponse = response.json()
    except JSONDecodeError:
        logger.info(response.text)
        raise
    assert decodedResponse["result"]


@checkService("Modules")
def checkModules(token):
    # Test the switch is OFF
    assert not mqtt_client.switchState

    # Program the switch to turn ON
    updateSensorTimer(token)

    # Wait for the switch to turn ON
    mqtt_client.waitForSwitchState(True)

    # Wait for the switch to turn OFF
    mqtt_client.waitForSwitchState(False)
