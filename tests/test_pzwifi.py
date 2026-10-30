"""Protocol regressions runnable without Home Assistant or a meter."""

import importlib.util
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import socket
from threading import Thread
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "pzwifi", Path(__file__).parents[1] / "custom_components/peacefair/pzwifi.py"
)
pzwifi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pzwifi)


def frame(*, current=1234, power=2838, energy=123456, power_factor=100):
    """Encode meter registers with an independent bitwise Modbus CRC."""
    registers = (
        2300, current & 0xFFFF, current >> 16, power & 0xFFFF, power >> 16,
        energy & 0xFFFF, energy >> 16, 500, power_factor, 0,
    )
    payload = b"\x01\x04\x14" + b"".join(
        value.to_bytes(2, "big") for value in registers
    )
    return with_crc(payload)


def with_crc(payload):
    crc = 0xFFFF
    for byte in payload:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return payload + crc.to_bytes(2, "little")


@contextmanager
def meter_responses(responses):
    """Supply one response per fresh connection, without contacting a meter."""
    responses = iter(responses)
    connections = []

    class Connection:
        def __init__(self, response):
            self.response = response
            self.stream = BytesIO(response) if isinstance(response, bytes) else None
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def sendall(self, request):
            assert request == b"\x01\x04\x00\x00\x00\x0a\x70\x0d"

        def settimeout(self, timeout):
            assert 0 < timeout <= 1

        def recv(self, count):
            if isinstance(self.response, Exception):
                raise self.response
            return self.stream.read(count)

    def connect(address, timeout):
        assert address == ("192.0.2.10", 9000)
        assert 0 < timeout <= 1
        assert all(connection.closed for connection in connections)
        connection = Connection(next(responses))
        connections.append(connection)
        return connection

    with patch.object(pzwifi.socket, "create_connection", new=connect):
        yield connections


class ProtocolTests(unittest.TestCase):
    def test_register_order_and_units(self):
        result = pzwifi.decode_result(frame())
        self.assertEqual(tuple(result), (230, 1.234, 283.8, 123.456, 50, 1))

    def test_zero_load_is_a_valid_measurement(self):
        try:
            result = pzwifi.decode_result(frame(current=0, power=0, power_factor=0))
        except Exception as err:
            self.fail(f"A zero-load frame must decode successfully: {err!r}")
        self.assertEqual(result.power, 0)
        self.assertEqual(result.current, 0)

    def test_low_power_factor_is_not_rejected_as_bad_power(self):
        try:
            result = pzwifi.decode_result(frame(current=1000, power=460, power_factor=20))
        except Exception as err:
            self.fail(f"Valid low-power-factor load rejected: {err!r}")
        self.assertEqual(result.power, 46)
        self.assertEqual(result.power_factor, 0.2)

    def test_corrupt_crc_is_rejected(self):
        bad = bytearray(frame())
        bad[4] ^= 1
        with self.assertRaises(pzwifi.CRCError):
            pzwifi.decode_result(bad)

    def test_short_frames_have_a_protocol_error(self):
        for data in (b"", b"\x01", with_crc(b"\x01\x04\x14")):
            with self.subTest(data=data):
                try:
                    pzwifi.decode_result(data)
                except pzwifi.BadValue:
                    continue
                except Exception as err:
                    self.fail(f"Short frame must raise BadValue, got {err!r}")
                self.fail("Short frame was accepted")

    def test_wrong_address_function_and_byte_count_are_rejected(self):
        for header in (b"\x02\x04\x14", b"\x01\x03\x14", b"\x01\x04\x12"):
            with self.subTest(header=header):
                with self.assertRaises(pzwifi.BadValue):
                    pzwifi.decode_result(with_crc(header + frame()[3:-2]))

    def test_out_of_range_measurements_are_rejected(self):
        for data in (frame(current=100001), frame(power_factor=101)):
            with self.subTest(data=data):
                with self.assertRaises(pzwifi.BadValue):
                    pzwifi.decode_result(data)

    def test_crc_handles_empty_input(self):
        try:
            self.assertFalse(pzwifi.check_crc(b""))
            self.assertFalse(pzwifi.check_crc(b"\x01"))
        except IndexError as err:
            self.fail(f"CRC check must tolerate short input: {err!r}")

    def test_tcp_fragments_are_assembled_and_connection_is_closed(self):
        observations = []
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(3)

            def serve():
                try:
                    with listener.accept()[0] as connection:
                        connection.settimeout(2)
                        observations.append(connection.recv(8))
                        data = frame()
                        for chunk in (data[:5], data[5:13], data[13:]):
                            connection.sendall(chunk)
                            time.sleep(0.01)
                        observations.append(connection.recv(8))
                except OSError as err:
                    observations.append(err)

            server = Thread(target=serve, daemon=True)
            server.start()
            try:
                result = pzwifi.poll(*listener.getsockname())
            except Exception as err:
                self.fail(f"Fragmented response failed: {err!r}")
            finally:
                server.join(timeout=3)
            self.assertIsNotNone(result)
            self.assertEqual(result.power_consumption, 123.456)
            self.assertEqual(observations, [pzwifi.MSG, b""])

    def test_retries_are_bounded_and_close_connections(self):
        for response, error_type in (
            (TimeoutError("timeout"), TimeoutError),
            (frame()[:-2] + b"\x00\x00", pzwifi.CRCError),
            (frame(current=100001), pzwifi.BadValue),
            (frame(power_factor=101), pzwifi.BadValue),
            (b"\x02\x04\x14", pzwifi.BadValue),
            (frame()[:10], pzwifi.BadValue),
            (b"", pzwifi.BadValue),
        ):
            with self.subTest(response=response):
                with meter_responses([response] * 6) as connections:
                    with self.assertRaises(error_type):
                        pzwifi.poll("192.0.2.10", 9000)
                self.assertEqual(len(connections), 6)
                self.assertTrue(all(connection.closed for connection in connections))

    def test_invalid_response_retries_until_valid_zero_power(self):
        for bad in (frame(current=100001), frame(power_factor=101),
                    b"\x02\x04\x14", frame()[:10], b""):
            with self.subTest(response=bad):
                with meter_responses(
                    [bad, frame(current=0, power=0, power_factor=0)]
                ) as connections:
                    result = pzwifi.poll("192.0.2.10", 9000)
                self.assertEqual(tuple(result), (230, 0, 0, 123.456, 50, 0))
                self.assertEqual(len(connections), 2)
                self.assertTrue(all(connection.closed for connection in connections))

    def test_mixed_errors_share_budget_and_allow_last_attempt_success(self):
        responses = [TimeoutError("timeout"), frame(current=100001),
                     frame()[:-2] + b"\x00\x00", b"", frame()[:10], frame()]
        with meter_responses(responses) as connections:
            result = pzwifi.poll("192.0.2.10", 9000)
        self.assertEqual(tuple(result), (230, 1.234, 283.8, 123.456, 50, 1))
        self.assertEqual(len(connections), 6)
        self.assertTrue(all(connection.closed for connection in connections))

    def test_mixed_errors_raise_last_error_when_budget_exhausted(self):
        last_error = pzwifi.BadValue("last invalid sample")
        responses = [TimeoutError("timeout"), frame(current=100001),
                     frame()[:-2] + b"\x00\x00", b"", frame()[:10], last_error]
        with meter_responses(responses) as connections:
            with self.assertRaises(pzwifi.BadValue) as raised:
                pzwifi.poll("192.0.2.10", 9000)
        self.assertIs(raised.exception, last_error)
        self.assertEqual(len(connections), 6)
        self.assertTrue(all(connection.closed for connection in connections))

    def test_none_result_is_retried(self):
        valid = pzwifi.PzSensorResult(230, 0, 0, 123.456, 50, 0)
        with meter_responses([frame()] * 2) as connections:
            with patch.object(pzwifi, "decode_result", side_effect=[None, valid]):
                result = pzwifi.poll("192.0.2.10", 9000)
        self.assertEqual(result, valid)
        self.assertEqual(len(connections), 2)
        self.assertTrue(all(connection.closed for connection in connections))

    def test_persistent_none_result_exhausts_budget(self):
        with meter_responses([frame()] * 6) as connections:
            with patch.object(pzwifi, "decode_result", return_value=None):
                with self.assertRaises(pzwifi.BadValue):
                    pzwifi.poll("192.0.2.10", 9000)
        self.assertEqual(len(connections), 6)
        self.assertTrue(all(connection.closed for connection in connections))

    def test_non_timeout_connection_error_is_not_retried(self):
        error = ConnectionRefusedError("offline")
        with patch.object(pzwifi.socket, "create_connection", side_effect=error) as connect:
            with self.assertRaises(ConnectionRefusedError) as raised:
                pzwifi.poll("192.0.2.10", 9000)
        self.assertIs(raised.exception, error)
        self.assertEqual(connect.call_count, 1)


if __name__ == "__main__":
    unittest.main()
