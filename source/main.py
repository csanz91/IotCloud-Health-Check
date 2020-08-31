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
from telegram_notifications import sendNotification


mqttNotificationSent = False
apiNotificationSent = False
dataStorageNotificationSent = False
weatherNotificationSent = False
homeNotificationSent = False
modulesNotificationSent = False

tick = 0
tickTime = 30.0
while True:

    time.sleep(tickTime)
    tick += 1

    # Send a random value to the MQTT broker
    try:
        mqtt_client.sendValue()
        mqttNotificationSent = False
    except:
        if not mqttNotificationSent:
            sendNotification("MQTT is not working")
        mqttNotificationSent = True

    # 60 * 5 -> 300 seconds, 5 minutes
    if tick < (60 * 5 / tickTime):
        continue
    tick = 0

    # Check the Google Home service
    try:
        home_check.checkHome()
        homeNotificationSent = False
    except:
        if not homeNotificationSent:
            sendNotification("Home API is not working")
        homeNotificationSent = True

    # Check the API is working
    try:
        token = api_check.login()
        apiNotificationSent = False
    except:
        if not apiNotificationSent:
            sendNotification("API is not working")
        apiNotificationSent = True
        continue

    # Check data is being saved
    try:
        data_storage_check.checkSensorData(token)
        dataStorageNotificationSent = False
    except:
        if not dataStorageNotificationSent:
            sendNotification("Data storage is not working")
        dataStorageNotificationSent = True

    # Check the weather API
    try:
        weather_api.checkWeatherData(token)
        weatherNotificationSent = False
    except:
        if not weatherNotificationSent:
            sendNotification("Weather API is not working")
        weatherNotificationSent = True

    # Check the modules service
    try:
        # Test the switch is OFF
        assert not mqtt_client.switchState

        # Program the switch to turn ON
        modules_check.updateSensorTimer(token)
        mqtt_client.notifySwitchUpdated()

        # Wait for the switch to turn ON
        responseTime = 0
        timeout = 10
        while responseTime < timeout:
            if mqtt_client.switchState:
                break
            time.sleep(0.1)
            responseTime += 0.1
        if responseTime >= timeout:
            raise TimeoutError("The switch did not change in the expected time period")
        logger.info(f"Switch ON cleared in {responseTime} seconds")

        # Wait for the switch to turn OFF
        responseTime = 0
        timeout = 10
        while responseTime < timeout:
            if not mqtt_client.switchState:
                break
            time.sleep(0.1)
            responseTime += 0.1
        if responseTime >= timeout:
            raise TimeoutError("The switch did not change in the expected time period")
        logger.info(f"Switch OFF cleared in {responseTime} seconds")

        modulesNotificationSent = False
    except:
        if not modulesNotificationSent:
            sendNotification("Modules are not working")
        modulesNotificationSent = True
