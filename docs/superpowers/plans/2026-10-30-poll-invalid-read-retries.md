# Poll Invalid Read Retries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 无效读数参与 poll() 的有界重试，减少偶发读取失败。

**Architecture:** 保留解析异常接口，在现有重试循环内捕获 BadValue 并拒绝 None 解析结果。保持 coordinator 和实体行为。

**Tech Stack:** Python 标准库 socket、unittest；现有 Home Assistant pytest 环境。

**Spec:** docs/superpowers/specs/2026-10-30-power-rounded-retention-design.md（已按用户最终选择收缩范围）。

## Global Constraints

- 功能修改只限 poll(host, port)，不修改实体或 coordinator。
- 超时、CRC、BadValue 共用最多 6 次尝试；每次新建并关闭有超时的连接。
- 第 6 次仍可成功，失败则抛最后一次错误；其他 OSError 直接上抛。
- 不连接实际设备，不增加依赖或放宽解析校验。

## Review Focus

- 混合错误不重置尝试预算，最后一次成功可返回。
- 提前断开和错误帧头也必须重试并关闭连接。
- None 不能作为成功结果传给 HA。
- 零功率是成功，非超时 OSError 直接传播。
- 尝试耗尽必须保留最终异常原因。

### Task 1: 扩展 poll 的无效读数重试

**Files:** 修改 custom_components/peacefair/pzwifi.py、tests/test_pzwifi.py、README.md、AGENTS.md。

**Interfaces:** 消费 decode_result(data) 的 PzSensorResult 或协议异常；poll(host, port) 返回有效结果或抛出最后一次异常，不返回 None。

- [x] 新增模拟 TCP 连接测试：无效读数/帧头/提前断开后成功、持续无效 6 次、None 后成功及耗尽、混合错误后第 6 次成功/失败、零功率、普通连接错误。断言结果/最终错误、尝试次数、连接关闭。
- [x] 运行 python3 -B -m unittest discover -s tests -p test_pzwifi.py，确认新重试测试因当前遇到 BadValue 提前退出或接受 None 而失败。
- [x] 在 poll() 中校验解析结果不为 None，并将 BadValue 加入现有重试异常集合；同步函数说明和 debug 日志。
- [x] 更新 README、AGENTS.md 重试说明；运行协议回归（预期全部通过）、可用 HA 全套 pytest 及 git diff --check。
- [x] 审查最终差异并提交 fix: retry invalid meter readings within poll。
