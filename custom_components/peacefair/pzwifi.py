import socket
import time
import os
from collections import namedtuple
import logging

byte2int = lambda b: b


_LOGGER = logging.getLogger(__name__)


PzSensorResult = namedtuple(
    "PzSensorResult",
    ["voltage", "current", "power", "power_consumption", "freqency", "power_factor"],
)

MSG = b"\x01\x04\x00\x00\x00\x0A\x70\x0D"


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
    crc = data[-2:]
    payload = data[:-2]

    expected_crc = compute_crc(payload)
    expected_crc_h = expected_crc >> 8
    expected_crc_l = expected_crc & 0x00FF

    return crc[0] == expected_crc_h and crc[1] == expected_crc_l


def decode_result(bytes):
    # global ok, bad
    # print(f'----------{len(bytes)} OK: {ok} BAD: {bad} BAD Rate: {round(100 * bad / (bad + ok))}% )')

    # if not (len(bytes) == 25):
    #     print('Value error.')
    #     bad += 1
    #     return

    if not check_crc(bytes):
        raise CRCError

    # should check CRC first
    voltage_b = bytes[3:5]
    voltage = int.from_bytes(voltage_b, "big") / 10
    print(f"Voltage: {voltage} V")

    # current_l = bytes[5:7]
    # current_h = bytes[7:9]

    current_b = [*bytes[7:9], *bytes[5:7]]
    current = int.from_bytes(current_b, "big") / 1000
    # current = bytes_to_int_16(current_l, current_h) / 1000
    print(f"Current: {current} A")

    # power_l = bytes[9:11]
    # power_h = bytes[11:13]
    power_b = [*bytes[11:13], *bytes[9:11]]
    # power = bytes_to_int_16(power_l, power_h) / 10
    power = int.from_bytes(power_b, "big") / 10
    print(f"Power: {power} W")

    # consumption_l = bytes[13:15]
    # consumption_h = bytes[15:17]
    consumption_b = [*bytes[15:17], *bytes[13:15]]
    # consumption = bytes_to_int_16(consumption_l, consumption_h) / 1000 / 1000
    consumption = int.from_bytes(consumption_b, "big") / 1000
    print(f"Consumption: {consumption} kWh")

    freq_b = bytes[17:19]
    freq = int.from_bytes(freq_b, "big") / 10
    print(f"Frequency: {freq} Hz")

    power_factor_b = bytes[19:21]
    power_factor = int.from_bytes(power_factor_b, "big") / 100
    print(f"Power factor: {power_factor}%")

    alert_b = bytes[21:23]
    alert = not int.from_bytes(alert_b, "big") == 0
    print(f"Alert: {alert}")

    print("----------")

    # Check if P=I*A holds
    power_delta = (power - current * voltage) / power
    if abs(power_delta) > 0.5:
        raise BadValue

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
    # TODO: Write some log
    conn = socket.socket()
    conn.connect((host, port))

    conn.settimeout(1)

    retries = 0

    while retries <= 5:
        retries += 1

        conn.sendall(MSG)

        try:
            data = conn.recv(1024)
            _LOGGER.info(hexlify_packets(data))
            result = decode_result(data)

            if result is None:
                print("Result is None. (BadValue)")
                raise BadValue()

            print("Result is OK.")
            return result

        except socket.timeout:
            continue
        except CRCError:
            continue


class CRCError(Exception):
    pass


class BadValue(Exception):
    pass


if __name__ == "__main__":
    poll("192.168.1.89", 9000)
