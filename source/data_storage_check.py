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
analogSensorId = "healthcheck_analog"


def checkSensorData(apiToken):

    headers = {"Authorization": f"Bearer {apiToken}"}

    # Check we have data in the last 5 minutes
    now = int(time.time())
    payload = {"initialTimestamp": now - 60 * 5, "finalTimestamp": now}

    response = session.post(
        f"https://api.iotcloud.es/api/v1/users/{userId}/locations/{locationId}/devices/{deviceId}/sensorsdata/{analogSensorId}",
        json=payload,
        headers=headers,
    )

    decodedResponse = response.json()
    data = decodedResponse["data"]
    assert len(data) > 2
