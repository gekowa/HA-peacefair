import socket
import time
from collections import namedtuple
import logging

byte2int = lambda b: b


_LOGGER = logging.getLogger(__name__)


PzSensorResult = namedtuple(
    "PzSensorResult",
    ["voltage", "current", "power", "power_consumption", "freqency", "power_factor"],
)

MSG = b"\x01\x04\x00\x00\x00\x0A\x70\x0D"
RESPONSE_LENGTH = 25
SOCKET_TIMEOUT = 1.0
MAX_ATTEMPTS = 6


def __generate_crc16_table():
    """Generates a crc16 lookup table
    .. note:: This will only be generated once
    """
    result = []
    for byte in range(256):
        crc = 0x0000
        for _ in range(8):
            if (byte ^ crc) & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
            byte >>= 1
        result.append(crc)
    return result


__crc16_table = __generate_crc16_table()


def compute_crc(data):
    """Computes a crc16 on the passed in string. For modbus,
    this is only used on the binary serial protocols (in this
    case RTU).
    The difference between modbus's crc16 and a normal crc16
    is that modbus starts the crc value out at 0xffff.
    :param data: The data to create a crc16 of
    :returns: The calculated CRC
    """
    crc = 0xFFFF
    for a in data:
        idx = __crc16_table[(crc ^ byte2int(a)) & 0xFF]
        crc = ((crc >> 8) & 0xFF) ^ idx
    swapped = ((crc << 8) & 0xFF00) | ((crc >> 8) & 0x00FF)
    return swapped


def bytes_to_int_16(low_16, high_16):
    return (int.from_bytes(high_16, "big") << 16) + int.from_bytes(low_16, "big")


def check_crc(data):
    if len(data) < 2:
        return False
    crc = data[-2:]
    payload = data[:-2]

    expected_crc = compute_crc(payload)
    expected_crc_h = expected_crc >> 8
    expected_crc_l = expected_crc & 0x00FF

    return crc[0] == expected_crc_h and crc[1] == expected_crc_l


def decode_result(data):
    """Decode a complete response, preserving the meter's register units."""
    if len(data) != RESPONSE_LENGTH:
        raise BadValue(f"Expected {RESPONSE_LENGTH} bytes, received {len(data)}")
    if not check_crc(data):
        raise CRCError("Invalid response CRC")
    if data[:3] != b"\x01\x04\x14":
        raise BadValue("Unexpected device address, function or byte count")

    voltage = int.from_bytes(data[3:5], "big") / 10
    current = bytes_to_int_16(data[5:7], data[7:9]) / 1000
    power = bytes_to_int_16(data[9:11], data[11:13]) / 10
    consumption = bytes_to_int_16(data[13:15], data[15:17]) / 1000
    freq = int.from_bytes(data[17:19], "big") / 10
    power_factor = int.from_bytes(data[19:21], "big") / 100

    if current > 100 or power_factor > 1:
        raise BadValue("Current or power factor outside the meter's range")

    # Active power need not equal voltage * current (apparent power).
    # In particular, zero load and low power factor are valid measurements.
    return PzSensorResult(voltage, current, power, consumption, freq, power_factor)


def hexlify_packets(packet):
    """
    Returns hex representation of bytestring received
    :param packet:
    :return:
    """
    if not packet:
        return ""
    return " ".join([hex(byte2int(x)) for x in packet])


def poll(host, port):
    """Read one sample with bounded I/O; retry timeout, CRC and invalid data."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            # A fresh connection prevents a delayed previous reply from being
            # mistaken for the next one after a failed attempt.
            with socket.create_connection((host, port), timeout=SOCKET_TIMEOUT) as conn:
                conn.sendall(MSG)
                deadline = time.monotonic() + SOCKET_TIMEOUT
                data = bytearray()
                while len(data) < RESPONSE_LENGTH:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out receiving the meter response")
                    conn.settimeout(remaining)
                    chunk = conn.recv(RESPONSE_LENGTH - len(data))
                    if not chunk:
                        raise BadValue("Connection closed before a complete response")
                    data.extend(chunk)
                    if len(data) >= 3 and data[:3] != b"\x01\x04\x14":
                        raise BadValue("Unexpected response header or Modbus exception")
                _LOGGER.debug("Meter response: %s", hexlify_packets(data))
                result = decode_result(data)
                if result is None:
                    raise BadValue("Meter response contains no valid measurement")
                return result
        except (TimeoutError, CRCError, BadValue):
            if attempt == MAX_ATTEMPTS - 1:
                raise
            _LOGGER.debug("Retrying meter read after timeout, CRC or invalid data")


class CRCError(Exception):
    pass


class BadValue(Exception):
    pass


if __name__ == "__main__":
    poll("192.168.1.89", 9000)
