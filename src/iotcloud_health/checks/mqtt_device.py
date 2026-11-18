"""MQTT device login health check (plain MQTT on 1883, the path real devices use).

Logs in to EMQX with the demo device's real token and subscribes to one of its own
topics. That exercises the broker's TCP listener plus both api-internal hooks EMQX
relies on: /mqtt/emqx/authn (CONNECT) and /mqtt/emqx/authz (SUBSCRIBE).
"""

from __future__ import annotations

import logging
import os
import socket
import struct
from typing import Any

import requests

from iotcloud_health.checker import (
    HealthCheckError,
    check_service,
    describe_error,
    get_session,
    response_detail,
)
from iotcloud_health.config import settings

logger = logging.getLogger("iotcloud_health.checks.mqtt_device")

# device_id -> MQTT token. Device tokens never expire, so fetch once per process.
# EMQX still asks api-internal to verify the token on every CONNECT.
_token_cache: dict[str, str] = {}

_CONNACK_REASONS = {
    1: "unacceptable protocol version",
    2: "client identifier rejected",
    3: "server unavailable",
    4: "bad username or password",
    5: "not authorized",
}


def _encode_length(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n % 128, n // 128
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _encode_str(s: str) -> bytes:
    data = s.encode("utf-8")
    return struct.pack("!H", len(data)) + data


def _connect_packet(client_id: str, username: str, password: str) -> bytes:
    flags = 0x80 | 0x40 | 0x02  # username, password, clean session
    body = (
        _encode_str("MQTT")
        + bytes([4, flags])
        + struct.pack("!H", 30)  # keep-alive seconds
        + _encode_str(client_id)
        + _encode_str(username)
        + _encode_str(password)
    )
    return b"\x10" + _encode_length(len(body)) + body


def _subscribe_packet(packet_id: int, topic: str) -> bytes:
    body = struct.pack("!H", packet_id) + _encode_str(topic) + b"\x00"
    return b"\x82" + _encode_length(len(body)) + body


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("broker closed the connection")
        buf += chunk
    return buf


def _read_packet(sock: socket.socket) -> tuple[int, bytes]:
    """Returns (packet type, body) for the next MQTT packet."""
    header = _recv_exact(sock, 1)[0]
    length, multiplier = 0, 1
    while True:
        byte = _recv_exact(sock, 1)[0]
        length += (byte & 0x7F) * multiplier
        if not byte & 0x80:
            break
        multiplier *= 128
    return header >> 4, _recv_exact(sock, length)


def _get_device_token(sess: requests.Session, device_id: str) -> str:
    if device_id in _token_cache:
        return _token_cache[device_id]

    url = f"{settings.internal_api_url.rstrip('/')}/devices/{device_id}/mqtt-auth"
    try:
        resp = sess.get(url, headers={"X-M2M-Token": settings.m2m_token}, timeout=10)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [MQTT Token Unavailable] Could not fetch the MQTT token for '{device_id}' "
            f"from the Internal API: {describe_error(err)}."
        ) from err
    if resp.status_code != 200:
        raise HealthCheckError(
            f"🔴 [MQTT Token Unavailable] GET /devices/{device_id}/mqtt-auth returned HTTP "
            f"{resp.status_code}: {response_detail(resp)}.",
            status_code=resp.status_code,
        )
    try:
        token = resp.json()["token"]
    except (ValueError, KeyError, TypeError) as err:
        raise HealthCheckError(
            f"🔴 [MQTT Token Unavailable] /devices/{device_id}/mqtt-auth returned no token."
        ) from err
    _token_cache[device_id] = token
    return token


@check_service("mqtt_device")
def check_mqtt_device_login(
    host: str | None = None,
    port: int | None = None,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Connects to the broker on plain MQTT as the demo device and subscribes to its topic."""
    host = host or settings.mqtt_tcp_host
    port = port or settings.mqtt_tcp_port
    location_id = settings.iotcloud_location_id
    device_id = settings.iotcloud_device_id
    topic = f"v1/{location_id}/{device_id}/{settings.thermostat_sensor_id}/aux/setpoint"

    token = _get_device_token(session or get_session(), device_id)
    # A unique client ID, so the virtual runtime's own session is never taken over.
    client_id = f"iotcloud-healthcheck-{os.urandom(4).hex()}"

    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as err:
        raise HealthCheckError(
            f"🔴 [MQTT Broker Unreachable] Cannot open TCP {host}:{port}: {describe_error(err)}. "
            "Devices cannot reach the broker (EMQX down, port forward or DynHost IP)."
        ) from err

    try:
        with sock:
            sock.sendall(_connect_packet(client_id, token, "_"))
            ptype, body = _read_packet(sock)
            if ptype != 2 or len(body) < 2:
                raise HealthCheckError(
                    f"🔴 [MQTT Protocol Error] {host}:{port} answered CONNECT with packet "
                    f"type {ptype} instead of CONNACK."
                )
            if body[1] != 0:
                reason = _CONNACK_REASONS.get(body[1], f"code {body[1]}")
                raise HealthCheckError(
                    f"🔴 [MQTT Login Refused] EMQX refused the device login ({reason}). "
                    "api-internal /mqtt/emqx/authn is down or rejecting tokens: devices "
                    "that reconnect cannot log in."
                )

            sock.sendall(_subscribe_packet(1, topic))
            while True:
                ptype, body = _read_packet(sock)
                if ptype == 9:  # SUBACK (retained PUBLISHes may arrive first)
                    break
            granted = body[2:]
            if not granted or granted[0] == 0x80:
                raise HealthCheckError(
                    f"🔴 [MQTT Subscribe Denied] EMQX denied the device's SUBSCRIBE to its own "
                    f"topic '{topic}'. api-internal /mqtt/emqx/authz is down or rejecting: "
                    "devices cannot receive commands."
                )
            sock.sendall(b"\xe0\x00")  # DISCONNECT
    except (OSError, ConnectionError) as err:
        raise HealthCheckError(
            f"🔴 [MQTT Broker Unreachable] Connection to {host}:{port} failed during the MQTT "
            f"handshake: {describe_error(err)}."
        ) from err

    logger.info("MQTT device login passed (%s:%s as '%s')", host, port, device_id)
    return {"host": host, "port": port, "device_id": device_id}
