import logging
import logging.config
from json.decoder import JSONDecodeError

from docker_secrets import getDocketSecrets
from check_service import checkService
import requests

logger = logging.getLogger()

session = requests.Session()

userId = getDocketSecrets("iotcloud_userId")


@checkService("Weather")
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
    try:
        decodedResponse = response.json()
    except JSONDecodeError:
        logger.info(response.text)
        raise
    data = decodedResponse["data"]
    assert data["weatherDataExpanded"]["ubi"] == "TERUEL"
    assert len(data["hist"])
