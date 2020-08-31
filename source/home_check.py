import logging
import logging.config

from docker_secrets import getDocketSecrets
import requests

logger = logging.getLogger()

session = requests.Session()

homeToken = getDocketSecrets("iotcloud_home_token")

url = "https://home.iotcloud.es"


def checkHome():
    headers = {"Authorization": f"Bearer {homeToken}"}
    requestId = "ff36a3cc-ec34-11e6-b1a0-64510650abcf"
    payload = {
        "requestId": requestId,
        "inputs": [{"intent": "action.devices.SYNC"}],
    }

    response = session.post(url, json=payload, headers=headers)
    decodedResponse = response.json()

    assert decodedResponse["requestId"] == requestId
