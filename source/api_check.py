import logging
import logging.config

from docker_secrets import getDocketSecrets
from check_service import checkService
import requests

logger = logging.getLogger()

session = requests.Session()

iotcloudMail = getDocketSecrets("iotcloud_mail")
iotcloudPassword = getDocketSecrets("iotcloud_password")
iotcloudUserId = getDocketSecrets("iotcloud_userId")


url = "https://api.iotcloud.es/api/v1/login"


@checkService("API")
def login():
    payload = {
        "email": iotcloudMail,
        "password": iotcloudPassword,
    }

    response = session.post(url, json=payload)
    decodedResponse = response.json()
    assert decodedResponse["data"]["userId"] == iotcloudUserId
    token = decodedResponse["data"]["token"]
    return token
