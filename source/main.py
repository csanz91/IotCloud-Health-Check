import logging
import logging.config
import time


# Logging setup
logger = logging.getLogger()
handler = logging.handlers.RotatingFileHandler(
    "../logs/healthCheck.log", mode="a", maxBytes=1024 * 1024 * 10, backupCount=2
)
formatter = logging.Formatter(
    "%(asctime)s <%(levelname).1s> %(funcName)s:%(lineno)s: %(message)s"
)
logger.setLevel(logging.INFO)
handler.setFormatter(formatter)
logger.addHandler(handler)

import mqtt_client
import api_check
import data_storage_check
import weather_api
import home_check
import modules_check


tick = 0
tickTime = 30.0
while True:

    time.sleep(tickTime)
    tick += 1

    # Send a random value to the MQTT broker
    mqtt_client.sendValue()

    # 60 * 5 -> 300 seconds, 5 minutes
    if tick < (60 * 5 / tickTime):
        continue
    tick = 0

    # Check the Google Home service
    home_check.checkHome()

    # Check the API is working
    token = api_check.login()
    if not token:
        continue

    # Check data is being saved
    data_storage_check.checkSensorData(token)

    # Check the weather API
    weather_api.checkWeatherData(token)

    # Check the modules service
    modules_check.checkModules(token)
