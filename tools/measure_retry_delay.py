#!/usr/bin/env python3
"""Standalone single-request Peacefair diagnostic (Python 3.9+, stdlib only).

Each round sends at most one read command and waits on the same TCP connection.
Protocol validation mirrors integration 1.0.2. No retries or device writes.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import socket
import statistics
import time


REQUEST = b"\x01\x04\x00\x00\x00\x0a\x70\x0d"
FRAME_LENGTH = 25
ATTEMPT_FIELDS = (
    "timestamp_utc", "round", "outcome", "phase", "elapsed_ms", "connect_ms",
    "send_ms", "first_byte_ms", "complete_frame_ms", "bytes_received",
    "power_w", "error", "frame_hex",
)


class CRCError(Exception):
    pass


class BadValue(Exception):
    pass


def decode_frame(data):
    """Match 1.0.2 validation, register order and units; preserve zero power."""
    if len(data) != FRAME_LENGTH:
        raise BadValue(f"Expected {FRAME_LENGTH} bytes, received {len(data)}")
    crc = 0xFFFF
    for byte in data[:-2]:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    if int.from_bytes(data[-2:], "little") != crc:
        raise CRCError("Invalid response CRC")
    if data[:3] != b"\x01\x04\x14":
        raise BadValue("Unexpected device address, function or byte count")

    def word(start):
        return int.from_bytes(data[start:start + 2], "big")

    current = (word(5) + (word(7) << 16)) / 1000
    power_factor = word(19) / 100
    if current > 100 or power_factor > 1:
        raise BadValue("Current or power factor outside the meter's range")
    return {
        "voltage": word(3) / 10,
        "current": current,
        "power": (word(9) + (word(11) << 16)) / 10,
        "power_consumption": (word(13) + (word(15) << 16)) / 1000,
        "freqency": word(17) / 10,
        "power_factor": power_factor,
    }


def read_once(host, port, timeout, connect_timeout=3.0):
    """Send once; first-byte/frame times start after sendall finishes."""
    started = time.monotonic()
    timestamp = datetime.now(timezone.utc).isoformat()
    data = bytearray()
    outcome, error, power = "ok", "", ""
    phase = "connect"
    connect_ms = send_ms = first_byte_ms = complete_frame_ms = None
    try:
        with socket.create_connection((host, port), timeout=connect_timeout) as connection:
            connected = time.monotonic()
            connect_ms = round((connected - started) * 1000, 3)
            phase = "send"
            connection.settimeout(connect_timeout)
            connection.sendall(REQUEST)
            sent = time.monotonic()
            send_ms = round((sent - connected) * 1000, 3)
            phase = "receive"
            deadline = sent + timeout
            while len(data) < FRAME_LENGTH:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out receiving the meter response")
                connection.settimeout(remaining)
                chunk = connection.recv(FRAME_LENGTH - len(data))
                if not chunk:
                    raise BadValue("Connection closed before a complete response")
                received = time.monotonic()
                if first_byte_ms is None:
                    first_byte_ms = round((received - sent) * 1000, 3)
                data.extend(chunk)
                if len(data) == FRAME_LENGTH:
                    complete_frame_ms = round((received - sent) * 1000, 3)
                if len(data) >= 3 and data[:3] != b"\x01\x04\x14":
                    raise BadValue("Unexpected response header or Modbus exception")
            phase = "decode"
            result = decode_frame(data)
            if result is None:
                raise BadValue("Meter response contains no valid measurement")
            power = result["power"]
            phase = "complete"
    except TimeoutError as exc:
        outcome, error = "timeout", str(exc)
    except CRCError as exc:
        outcome, error = "crc", str(exc)
    except BadValue as exc:
        outcome, error = "invalid", str(exc)
    except OSError as exc:
        outcome, error = "connection", str(exc)
    except KeyboardInterrupt:
        outcome, error = "interrupted", "Interrupted by user"
    return {
        "timestamp_utc": timestamp,
        "outcome": outcome,
        "phase": phase,
        "error": error,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        "connect_ms": connect_ms,
        "send_ms": send_ms,
        "first_byte_ms": first_byte_ms,
        "complete_frame_ms": complete_frame_ms,
        "bytes_received": len(data),
        "power_w": power,
        "frame_hex": data.hex(" "),
    }


def timing_stats(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    return {
        "count": len(values), "min": values[0], "mean": statistics.mean(values),
        "p50": statistics.median(values),
        "p95": values[math.ceil(len(values) * 0.95) - 1], "max": values[-1],
    }


def summarize(rows):
    """Completed includes errors but excludes a Ctrl+C-interrupted transaction."""
    completed = [row for row in rows if row["outcome"] != "interrupted"]
    valid = [row for row in completed if row["outcome"] == "ok"]
    timeouts = [row for row in completed if row["outcome"] == "timeout"]
    receive_timeouts = [row for row in timeouts if row["phase"] == "receive"]
    return {
        "completed_rounds": len(completed),
        "successful_rounds": len(valid),
        "failed_rounds": len(completed) - len(valid),
        "success_rate": len(valid) / len(completed) if completed else None,
        "outcomes": dict(Counter(row["outcome"] for row in completed)),
        "timeout_phases": dict(Counter(row["phase"] for row in timeouts)),
        "receive_timeouts_without_bytes": sum(row["bytes_received"] == 0 for row in receive_timeouts),
        "receive_timeouts_with_partial_bytes": sum(row["bytes_received"] > 0 for row in receive_timeouts),
        "valid_responses_after_1s": sum(row["complete_frame_ms"] > 1000 for row in valid),
        "valid_responses_after_3s": sum(row["complete_frame_ms"] > 3000 for row in valid),
        "valid_responses_after_5s": sum(row["complete_frame_ms"] > 5000 for row in valid),
        "valid_first_byte_ms": timing_stats(row["first_byte_ms"] for row in valid),
        "valid_complete_frame_ms": timing_stats(row["complete_frame_ms"] for row in valid),
        "round_elapsed_ms": timing_stats(row["elapsed_ms"] for row in completed),
    }


def finite_number(value, minimum, inclusive):
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("请输入数字") from exc
    if not math.isfinite(result) or result < minimum or (result == minimum and not inclusive):
        relation = "大于等于" if inclusive else "大于"
        raise argparse.ArgumentTypeError(f"必须是{relation} {minimum} 的有限数字")
    return result


def nonnegative(value):
    return finite_number(value, 0, True)


def positive(value):
    return finite_number(value, 0, False)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Peacefair 单次请求诊断：每轮只发送一次，在同一连接等待响应，不重试。",
        epilog="请暂停 HA 集成及其他读取程序。Ctrl+C 保存已完成记录和当前接收的部分数据。",
    )
    parser.add_argument("--host", required=True, help="ESP32 地址（无默认值）")
    parser.add_argument("--port", required=True, type=int, help="TCP 透传端口（无默认值）")
    parser.add_argument("--rounds", type=int, default=20, help="单次请求的总轮数，默认 20")
    parser.add_argument("--interval", type=nonnegative, default=5.0,
                        help="本轮结束到下一轮开始的秒数，默认 5")
    parser.add_argument("--timeout", type=positive, default=10.0,
                        help="发送完成后，等待完整响应的总时限，默认 10 秒；收到部分数据不重置时限")
    parser.add_argument("--connect-timeout", type=positive, default=3.0,
                        help="TCP 连接和发送阶段各自的超时，默认 3 秒")
    parser.add_argument("--output", type=Path, help="新建的结果目录；默认使用当前时间命名")
    args = parser.parse_args(argv)
    if not args.host.strip() or not 1 <= args.port <= 65535 or args.rounds < 1:
        parser.error("host 不得为空，port 必须为 1～65535，rounds 必须至少为 1")
    return args


def milliseconds(value):
    return "未到达" if value is None else f"{value:.0f}ms"


def print_summary(report):
    rate = "—" if report["success_rate"] is None else f'{report["success_rate"]:.1%}'
    print(f'\n完成 {report["completed_rounds"]} 轮，成功 {report["successful_rounds"]} 轮，成功率 {rate}')
    print("结果分类：" + json.dumps(report["outcomes"], ensure_ascii=False))
    print("超时阶段：" + json.dumps(report["timeout_phases"], ensure_ascii=False))
    print(f'接收超时：完全未收到字节 {report["receive_timeouts_without_bytes"]} 次，'
          f'收到部分字节 {report["receive_timeouts_with_partial_bytes"]} 次')
    for seconds in (1, 3, 5):
        print(f'有效完整响应超过 {seconds} 秒：{report[f"valid_responses_after_{seconds}s"]} 次')
    stats = report["valid_complete_frame_ms"]
    if stats:
        print(f'有效完整响应耗时：P50 {stats["p50"]:.0f}ms，P95 {stats["p95"]:.0f}ms，最大 {stats["max"]:.0f}ms')
    print("首字节/完整响应耗时从发送完成算起；超过 1 秒的有效响应可用于判断原时限是否偏短。")
    print("若长时间仍无响应，需要继续排查链路；本实验不保证延迟响应属于本轮请求。")


def main(argv=None):
    args = parse_args(argv)
    output = args.output or Path(datetime.now().strftime("response-probe-%Y%m%d-%H%M%S-%f"))
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise SystemExit(f"无法新建结果目录（不会覆盖已有数据）：{exc}") from exc
    config = vars(args).copy()
    config.update({
        "output": str(output.resolve()), "mode": "single_request", "max_attempts": 1,
        "protocol_reference": "Peacefair integration 1.0.2",
        "started_utc": datetime.now(timezone.utc).isoformat(),
    })
    (output / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"目标 {args.host}:{args.port}，共 {args.rounds} 轮，每轮只发送一次，无重试。")
    print(f"响应时限 {args.timeout:g} 秒，连接/发送各 {args.connect_timeout:g} 秒，轮间等待 {args.interval:g} 秒。")
    print("请先暂停其他读取程序。本工具只读寄存器，不清零电能、不修改设备配置。")
    print(f"结果目录：{output.resolve()}", flush=True)
    rows = []
    interrupted = False
    with (output / "attempts.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=ATTEMPT_FIELDS)
        writer.writeheader()
        stream.flush()
        try:
            for number in range(1, args.rounds + 1):
                if number > 1:
                    time.sleep(args.interval)
                print(f"[{number}/{args.rounds}] 发送一次请求并等待…", flush=True)
                row = {"round": number, **read_once(args.host, args.port, args.timeout, args.connect_timeout)}
                rows.append(row)
                writer.writerow(row)
                stream.flush()
                print(f'  {row["outcome"]}，阶段 {row["phase"]}，首字节 {milliseconds(row["first_byte_ms"])}，'
                      f'完整帧 {milliseconds(row["complete_frame_ms"])}，收到 {row["bytes_received"]} 字节', flush=True)
                if row["outcome"] == "interrupted":
                    interrupted = True
                    break
        except KeyboardInterrupt:
            interrupted = True
        finally:
            report = {
                "config": config, "finished_utc": datetime.now(timezone.utc).isoformat(),
                "interrupted": interrupted, **summarize(rows),
            }
            (output / "summary.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
            )
            if interrupted:
                print("\n已中断；当前已记录的部分数据保留在 attempts.csv，汇总排除中断轮次。")
            print_summary(report)
            print(f"\n结果已保存到 {output.resolve()}")
    return 130 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
