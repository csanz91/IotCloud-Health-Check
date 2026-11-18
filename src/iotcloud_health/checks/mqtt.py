"""MQTT broker WebSocket Secure (WSS) connectivity health check."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import socket
import ssl
from typing import Any
from urllib.parse import urlparse

from iotcloud_health.checker import HealthCheckError, check_service, describe_error
from iotcloud_health.checks.ssl_helper import verify_certificate
from iotcloud_health.config import settings

logger = logging.getLogger("iotcloud_health.checks.mqtt")

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_HANDSHAKE_BYTES = 16384


def _expected_accept(key: str) -> str:
    digest = hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _read_http_head(sock: socket.socket) -> str:
    """Reads from the socket until the end of the HTTP response headers."""
    buf = b""
    while b"\r\n\r\n" not in buf and len(buf) < _MAX_HANDSHAKE_BYTES:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf.decode("latin1", errors="replace")


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
    if is_ssl:
        ssl_days_remaining = verify_certificate(
            host,
            port,
            label="MQTT",
            impact="External WebSocket clients cannot establish a TLS connection.",
            min_days_valid=settings.ssl_min_days_valid,
            timeout=timeout,
        )

    # 2. Open Connection
    try:
        raw_sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as err:
        raise HealthCheckError(
            f"🔴 [MQTT WSS Down] Failed to connect to {host}:{port}: {describe_error(err)}. "
            "External clients and sensors cannot reach the MQTT broker."
        ) from err

    try:
        sock: socket.socket = (
            ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host)
            if is_ssl
            else raw_sock
        )
    except (OSError, ssl.SSLError) as err:
        raw_sock.close()
        raise HealthCheckError(
            f"🔴 [MQTT WSS Down] TLS handshake with {host}:{port} failed: {describe_error(err)}. "
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
            resp_data = _read_http_head(sock)
    except OSError as err:
        raise HealthCheckError(
            f"🔴 [MQTT WSS Handshake Failed] Socket error during handshake with {mqtt_url}: "
            f"{describe_error(err)}."
        ) from err

    lines = resp_data.split("\r\n")
    status_line = lines[0] if lines else ""
    status_parts = status_line.split()
    if len(status_parts) < 2 or status_parts[1] != "101":
        raise HealthCheckError(
            f"🔴 [MQTT WSS Handshake Failed] Broker at {mqtt_url} returned '{status_line[:200]}' "
            "instead of HTTP 101 Switching Protocols."
        )

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    if headers.get("upgrade", "").lower() != "websocket":
        raise HealthCheckError(
            f"🔴 [MQTT WSS Handshake Failed] Broker at {mqtt_url} did not return "
            "'Upgrade: websocket' header."
        )
    if "mqtt" not in headers.get("sec-websocket-protocol", "").lower():
        raise HealthCheckError(
            f"🔴 [MQTT WSS Handshake Failed] Broker at {mqtt_url} did not return "
            "'Sec-WebSocket-Protocol: mqtt'."
        )
    accept = headers.get("sec-websocket-accept")
    if accept is not None and accept != _expected_accept(key):
        raise HealthCheckError(
            f"🔴 [MQTT WSS Handshake Failed] Broker at {mqtt_url} returned an invalid "
            "Sec-WebSocket-Accept value (response is not from a WebSocket endpoint)."
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
