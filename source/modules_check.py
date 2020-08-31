import logging
import logging.config
import time

from docker_secrets import getDocketSecrets
import requests

logger = logging.getLogger()

session = requests.Session()

userId = getDocketSecrets("iotcloud_userId")
locationId = getDocketSecrets("iotcloud_locationId")
deviceId = getDocketSecrets("iotcloud_deviceId")
switchSensorId = "healthcheck_toogle"
thermostatSensorId = "healthcheck_thermostat"


def updateSensorTimer(apiToken):

    headers = {"Authorization": f"Bearer {apiToken}"}

    # Turn of the switch for 3 seconds
    now = int(time.time())
    payload = {"sensorMetadata": {"timer": {"initialTimestamp": now, "duration": 3}}}

    response = session.put(
        f"https://api.iotcloud.es/api/v1/users/{userId}/locations/{locationId}/devices/{deviceId}/sensors/{switchSensorId}",
        json=payload,
        headers=headers,
    )

    decodedResponse = response.json()
    assert decodedResponse["result"]
