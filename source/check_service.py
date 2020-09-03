from telegram_notifications import sendNotification


class CheckService(object):
    """Decorator example mixing class and function definitions."""

    def __init__(self, func, serviceName):
        self.func = func
        self.serviceName = serviceName
        self.notificationSent = False

    def __call__(self, *args, **kwargs):
        try:
            result = self.func(*args, **kwargs)
            if self.notificationSent:
                sendNotification(f"{self.serviceName} is now working \U00002705")
            self.notificationSent = False
            return result
        except:
            if not self.notificationSent:
                sendNotification(f"{self.serviceName} is not working \U0000274C")
            self.notificationSent = True

        return None


def checkService(serviceName):
    def decorator(func):
        return CheckService(func, serviceName)

    return decorator
