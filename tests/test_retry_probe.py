"""Offline checks for the standalone field experiment; no physical meter needed."""

from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from threading import Thread
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools" / "measure_retry_delay.py"
spec = importlib.util.spec_from_file_location("retry_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
protocol = runpy.run_path(str(ROOT / "tests" / "test_pzwifi.py"))
frame = protocol["frame"]
reference = protocol["pzwifi"]


def reading(outcome):
    return {
        "timestamp_utc": "2026-10-30T00:00:00+00:00", "outcome": outcome,
        "elapsed_ms": 1, "power_w": 0 if outcome == "ok" else "",
        "error": "" if outcome == "ok" else outcome, "frame_hex": "",
    }


class RetryProbeTests(unittest.TestCase):
    def test_decoder_matches_integration(self):
        for data in (frame(), frame(current=0, power=0, power_factor=0),
                     frame(current=1000, power=460, power_factor=20)):
            with self.subTest(data=data):
                self.assertEqual(probe.decode_frame(data), reference.decode_result(data)._asdict())
        for data in (b"", frame()[:10], frame(current=100001), frame(power_factor=101),
                     protocol["with_crc"](b"\x02\x04\x14" + frame()[3:-2]),
                     frame()[:-2] + b"\x00\x00"):
            with self.subTest(data=data):
                with self.assertRaises((reference.CRCError, reference.BadValue)) as original:
                    reference.decode_result(data)
                with self.assertRaises((probe.CRCError, probe.BadValue)) as standalone:
                    probe.decode_frame(data)
                self.assertEqual(type(original.exception).__name__, type(standalone.exception).__name__)

    def test_defaults_use_single_request_and_ten_second_response_deadline(self):
        args = probe.parse_args(["--host", "example", "--port", "9000"])
        self.assertEqual(args.timeout, 10)
        self.assertEqual(args.interval, 5)
        self.assertEqual(args.connect_timeout, 3)
        self.assertFalse(hasattr(args, "delays_ms"))

    def test_late_fragmented_reply_uses_one_send_and_measures_from_send_completion(self):
        conn = TimedConnection([(1.2, frame()[:5]), (0.8, frame()[5:])])
        with patch.object(probe.socket, "create_connection", side_effect=conn.connect) as connect, \
                patch.object(probe.time, "monotonic", side_effect=lambda: conn.now):
            row = probe.read_once("example", 9000, 10, 3)
        self.assertEqual(row["outcome"], "ok")
        self.assertEqual(row["phase"], "complete")
        self.assertEqual(row["first_byte_ms"], 1200)
        self.assertEqual(row["complete_frame_ms"], 2000)
        self.assertEqual(row["connect_ms"], 200)
        self.assertEqual(row["send_ms"], 100)
        self.assertEqual(row["bytes_received"], 25)
        self.assertEqual(row["elapsed_ms"], 2300)
        self.assertEqual(conn.sent, [probe.REQUEST])
        self.assertTrue(conn.closed)
        self.assertEqual(connect.call_count, 1)
        self.assertAlmostEqual(conn.timeouts[-1], 8.8)

    def test_partial_timeout_keeps_bytes_and_does_not_reset_deadline(self):
        conn = TimedConnection([(1.2, frame()[:5]), (8.8, TimeoutError("timeout"))])
        with patch.object(probe.socket, "create_connection", side_effect=conn.connect), \
                patch.object(probe.time, "monotonic", side_effect=lambda: conn.now):
            row = probe.read_once("example", 9000, 10, 3)
        self.assertEqual(row["outcome"], "timeout")
        self.assertEqual(row["phase"], "receive")
        self.assertEqual(row["first_byte_ms"], 1200)
        self.assertIsNone(row["complete_frame_ms"])
        self.assertEqual(row["bytes_received"], 5)
        self.assertEqual(row["frame_hex"], frame()[:5].hex(" "))
        self.assertAlmostEqual(conn.timeouts[-1], 8.8)
        self.assertEqual(conn.sent, [probe.REQUEST])
        self.assertTrue(conn.closed)

    def test_timeout_phase_identifies_connection_and_send(self):
        with patch.object(probe.socket, "create_connection", side_effect=TimeoutError("connect")):
            row = probe.read_once("example", 9000, 10, 3)
        self.assertEqual(row["phase"], "connect")
        self.assertIsNone(row["first_byte_ms"])
        conn = TimedConnection([], send_error=TimeoutError("send"))
        with patch.object(probe.socket, "create_connection", side_effect=conn.connect):
            row = probe.read_once("example", 9000, 10, 3)
        self.assertEqual(row["phase"], "send")
        self.assertEqual(row["outcome"], "timeout")
        self.assertTrue(conn.closed)

    def test_interrupted_receive_keeps_partial_data(self):
        conn = TimedConnection([(0.1, frame()[:5]), (0.1, KeyboardInterrupt())])
        with patch.object(probe.socket, "create_connection", side_effect=conn.connect):
            row = probe.read_once("example", 9000, 10, 3)
        self.assertEqual(row["outcome"], "interrupted")
        self.assertEqual(row["bytes_received"], 5)
        self.assertEqual(row["phase"], "receive")
        self.assertTrue(conn.closed)

    def test_summary_distinguishes_late_success_and_timeout_without_bytes(self):
        base = {"elapsed_ms": 2100, "phase": "complete", "first_byte_ms": 1200,
                "complete_frame_ms": 2000, "bytes_received": 25, "outcome": "ok"}
        rows = [base, dict(base, complete_frame_ms=500, first_byte_ms=100),
                dict(base, outcome="timeout", phase="receive", bytes_received=0,
                     complete_frame_ms=None, first_byte_ms=None),
                dict(base, outcome="timeout", phase="receive", bytes_received=5, complete_frame_ms=None),
                dict(base, outcome="timeout", phase="connect", bytes_received=0,
                     complete_frame_ms=None, first_byte_ms=None),
                dict(base, outcome="interrupted", phase="receive", complete_frame_ms=None)]
        report = probe.summarize(rows)
        self.assertEqual(report["completed_rounds"], 5)
        self.assertEqual(report["success_rate"], 0.4)
        self.assertEqual(report["valid_responses_after_1s"], 1)
        self.assertEqual(report["receive_timeouts_without_bytes"], 1)
        self.assertEqual(report["receive_timeouts_with_partial_bytes"], 1)
        self.assertEqual(report["timeout_phases"], {"receive": 2, "connect": 1})
        self.assertEqual(report["valid_complete_frame_ms"]["p95"], 2000)
        self.assertIsNone(probe.summarize([])["success_rate"])

    def test_invalid_cli_values_rejected(self):
        for extra in (["--timeout", "inf"], ["--timeout", "0"], ["--connect-timeout", "0"],
                      ["--rounds", "0"], ["--port", "0"], ["--delays-ms", "250"]):
            with self.subTest(extra=extra), patch("sys.stderr", new=StringIO()):
                with self.assertRaises(SystemExit):
                    probe.parse_args(["--host", "example", "--port", "9000", *extra])

    def test_main_saves_interrupted_attempt_without_counting_completed_round(self):
        row = dict(reading("interrupted"), phase="receive", connect_ms=1, send_ms=1,
                   first_byte_ms=10, complete_frame_ms=None, bytes_received=3)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"
            with patch.object(probe, "read_once", return_value=row), redirect_stdout(StringIO()):
                status = probe.main(["--host", "example", "--port", "9000", "--output", str(output)])
            self.assertEqual(status, 130)
            report = json.loads((output / "summary.json").read_text())
            self.assertTrue(report["interrupted"])
            self.assertEqual(report["completed_rounds"], 0)
            self.assertEqual(len((output / "attempts.csv").read_text().splitlines()), 2)

    def test_standalone_script_waits_for_late_reply_without_resending(self):
        observations = []
        with tempfile.TemporaryDirectory() as directory, socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(5)

            def serve():
                try:
                    for delay, response in ((1.1, frame()), (0, frame()[:-2] + b"\x00\x00")):
                        with listener.accept()[0] as connection:
                            connection.settimeout(3)
                            request = bytearray()
                            while len(request) < 8:
                                chunk = connection.recv(8 - len(request))
                                if not chunk:
                                    raise AssertionError("Client closed before sending command")
                                request.extend(chunk)
                            observations.append(bytes(request))
                            time.sleep(delay)
                            connection.sendall(response[:5])
                            connection.sendall(response[5:])
                            observations.append(connection.recv(1))
                except Exception as exc:
                    observations.append(exc)

            server = Thread(target=serve, daemon=True)
            server.start()
            standalone = Path(directory) / SCRIPT.name
            shutil.copyfile(SCRIPT, standalone)
            output = Path(directory) / "result"
            completed = subprocess.run(
                [sys.executable, str(standalone), "--host", "127.0.0.1", "--port", str(listener.getsockname()[1]),
                 "--rounds", "2", "--timeout", "3", "--interval", "0", "--output", str(output)],
                cwd=directory, capture_output=True, text=True, timeout=10,
            )
            server.join(timeout=4)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(observations, [probe.REQUEST, b""] * 2)
            report = json.loads((output / "summary.json").read_text())
            self.assertEqual(report["completed_rounds"], 2)
            self.assertEqual(report["successful_rounds"], 1)
            self.assertEqual(report["outcomes"], {"ok": 1, "crc": 1})
            self.assertEqual(report["valid_responses_after_1s"], 1)
            self.assertGreaterEqual(report["valid_first_byte_ms"]["min"], 1000)


class TimedConnection:
    def __init__(self, events, send_error=None):
        self.events = iter(events)
        self.send_error = send_error
        self.now = 0
        self.closed = False
        self.sent = []
        self.timeouts = []

    def connect(self, address, timeout):
        self.now += 0.2
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def sendall(self, request):
        self.sent.append(request)
        self.now += 0.1
        if self.send_error:
            raise self.send_error

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def recv(self, count):
        delay, result = next(self.events)
        self.now += delay
        if isinstance(result, BaseException):
            raise result
        assert len(result) <= count
        return result


if __name__ == "__main__":
    unittest.main()
