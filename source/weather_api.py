import logging
import logging.config

from docker_secrets import getDocketSecrets
import requests

logger = logging.getLogger()

session = requests.Session()

userId = getDocketSecrets("iotcloud_userId")


def checkWeatherData(apiToken):
    headers = {"Authorization": f"Bearer {apiToken}"}

    payload = {
        "postalCode": "44002",
        "measurement": "temperature",
    }

    response = session.post(
        f"https://api.iotcloud.es/api/v1/users/{userId}/weather",
        json=payload,
        headers=headers,
    )
    decodedResponse = response.json()
    data = decodedResponse["data"]
    assert data["weatherDataExpanded"]["ubi"] == "TERUEL"
    assert len(data["hist"])
