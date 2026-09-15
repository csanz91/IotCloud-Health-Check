"""MQTT broker WebSocket Secure (WSS) connectivity health check."""

from __future__ import annotations

import base64
import logging
import os
import socket
import ssl
from typing import Any
from urllib.parse import urlparse

from iotcloud_health.checker import HealthCheckError, check_service
from iotcloud_health.checks.ssl_helper import get_ssl_days_remaining
from iotcloud_health.config import settings

logger = logging.getLogger("iotcloud_health.checks.mqtt")


@check_service("mqtt_wss")
def check_mqtt_wss(
    url: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Probes the MQTT broker via WSS and verifies WebSocket upgrade and SSL validity."""
    mqtt_url = url or settings.mqtt_wss_url

    parsed = urlparse(mqtt_url)
    host = parsed.hostname or "mqtt.iotcloud.es"
    is_ssl = parsed.scheme in ("wss", "https")
    port = parsed.port or (443 if is_ssl else 80)
    path = parsed.path or "/mqtt"
    if not path.startswith("/"):
        path = f"/{path}"

    ssl_days_remaining: int | None = None

    # 1. SSL Certificate Verification (if WSS/HTTPS)
    if is_ssl and host:
        try:
            ssl_days_remaining = get_ssl_days_remaining(host, port, timeout=timeout)
        except (OSError, ssl.SSLError, ValueError) as err:
            raise HealthCheckError(
                f"🔴 [MQTT SSL Failed] Failed SSL handshake for {host}:{port}: {err}. "
                "External WebSocket clients cannot establish TLS connection."
            ) from err

        if ssl_days_remaining < 0:
            raise HealthCheckError(
                f"🔴 [MQTT SSL Expired] SSL certificate for {host} has expired! "
                "External WebSocket clients cannot connect."
            )
        if ssl_days_remaining <= settings.ssl_min_days_valid:
            raise HealthCheckError(
                f"🔴 [MQTT SSL Expiring Soon] SSL certificate for {host} expires in "
                f"{ssl_days_remaining} days! Immediate renewal required."
            )

    # 2. Open Connection
    try:
        raw_sock = socket.create_connection((host, port), timeout=timeout)
        if is_ssl:
            ctx = ssl.create_default_context()
            sock: socket.socket = ctx.wrap_socket(raw_sock, server_hostname=host)
        else:
            sock = raw_sock
    except (OSError, ssl.SSLError) as err:
        raise HealthCheckError(
            f"🔴 [MQTT WSS Down] Failed to connect to {host}:{port}: {err}. "
            "External clients and sensors cannot reach the MQTT broker."
        ) from err

    # 3. WebSocket Upgrade Handshake
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Protocol: mqtt\r\n\r\n"
    )

    try:
        with sock:
            sock.sendall(req.encode("ascii"))
            resp_data = sock.recv(4096).decode("latin1", errors="replace")
    except OSError as err:
        raise HealthCheckError(
            f"🔴 [MQTT WSS Handshake Failed] Socket error during handshake with {mqtt_url}: {err}."
        ) from err

    lines = resp_data.split("\r\n")
    status_line = lines[0] if lines else ""
    if "101" not in status_line:
        raise HealthCheckError(
            f"🔴 [MQTT WSS Handshake Failed] Broker at {mqtt_url} returned '{status_line}' "
            "instead of HTTP 101 Switching Protocols."
        )

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip().lower()

    if headers.get("upgrade") != "websocket":
        raise HealthCheckError(
            f"🔴 [MQTT WSS Handshake Failed] Broker at {mqtt_url} did not return "
            "'Upgrade: websocket' header."
        )
    if "mqtt" not in headers.get("sec-websocket-protocol", ""):
        raise HealthCheckError(
            f"🔴 [MQTT WSS Handshake Failed] Broker at {mqtt_url} did not return "
            "'Sec-WebSocket-Protocol: mqtt'."
        )

    logger.info(
        "MQTT WSS health check passed (%s, status 101, SSL %s days remaining)",
        mqtt_url,
        ssl_days_remaining,
    )
    return {
        "url": mqtt_url,
        "status": 101,
        "ssl_days_remaining": ssl_days_remaining,
    }
