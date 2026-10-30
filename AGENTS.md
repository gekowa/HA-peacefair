# Repository Guidelines

## 项目概览（Project Overview）

Peacefair 是 Home Assistant 自定义电能测量集成。硬件由 Peacefair 计量模块、开合式 CT 和 ESP32 组成；ESP32 将 TTL 串口数据透传到 Wi-Fi，集成通过本地 TCP 读取电压、电流、功率、电能、频率及功率因数。不是独立服务，也不包含 ESP32 固件。

## 架构与数据流（Architecture & Data Flow）

- **配置入口**：`config_flow.py` 提供 UI 添加、重新配置和 YAML 导入，保存 `host`、`port`。`sensor.py` 的旧 `async_setup_platform` 仅触发一次导入，不创建实体。沿用单设备模式，已有配置条目时不重复导入或覆盖。
- **协议层**：`pzwifi.py` 的同步 `poll(host, port)` 发送固定读寄存器报文，按完整帧累计 TCP 分段；`decode_result` 校验长度、CRC、响应头和读数范围，转换寄存器和单位，返回 `PzSensorResult` 命名元组。
- **状态与依赖传递**：`__init__.py` 创建 `PeacefairCoordinator`，等待首次刷新后保存到 `entry.runtime_data`，再加载 sensor 平台；读数保存在 `coordinator.data`。coordinator 每约 5 秒通过 executor 调用同步 `poll`；异常转成 `UpdateFailed`，实体由 `CoordinatorEntity` 管理可用性。
- **实际启用路径**：`manifest.json` 设置 `config_flow: true`、`single_config_entry: true`。`__init__.py` 实现条目加载和卸载；`config_flow.py` 提供有效配置流。`schema.py` 在 HA 2026 不同版本中选择运行环境提供的 Probatio 或 Voluptuous。

## 关键目录（Key Directories）

- `custom_components/peacefair/`：完整可安装集成；协议解析与 HA 实体接入分别保留在 `pzwifi.py` 和 `sensor.py`，避免相互混杂。
- `custom_components/peacefair/translations/`：英文和简体中文配置流文案；新增错误键需同步 `strings.json` 及两份翻译。
- `.github/workflows/`：发布自动化，不是测试流水线。`tests/` 包含标准库协议回归及真实 HA 测试实例的集成测试；仓库没有构建产物目录。

## 开发命令（Development Commands）

以下命令均从仓库根目录执行；是直接调用现有工具，不是仓库预设任务。

```bash
# Python 语法检查；不验证 Home Assistant API 兼容性
python3 -m compileall -q custom_components/peacefair

# 无需 Home Assistant 或硬件的 CRC 冒烟检查
python3 -B -c 'import sys; sys.path.insert(0, "custom_components/peacefair"); import pzwifi as p; assert p.check_crc(p.MSG); bad = bytearray(p.MSG); bad[3] ^= 1; assert not p.check_crc(bad)'
```

- **构建**：无需编译。发布工作流在集成目录执行 `zip <archive> -r ./`，产物为 `peacefair.zip`，压缩包根目录直接包含集成文件。
- **测试**：`python3 -B -m unittest discover -s tests -p test_pzwifi.py` 可仅用标准库检查协议；使用 Python 3.14 在虚拟环境安装 `requirements-test.txt` 后执行 `python -m pytest -q`，测试 HA 2026.10.4 的配置流、迁移、实体和轮询。没有配置 formatter/lint 或 Node 任务。
- **运行**：将集成目录放入 HA 配置目录下的 `custom_components/peacefair/` 并重启，在“设置 → 设备与服务”添加 Peacefair。旧版 YAML 会自动导入，确认 UI 条目出现后删除对应旧配置。旧配置示例：

```yaml
sensor:
  - platform: peacefair
    host: 192.168.1.89  # 改为 ESP32 地址
    port: 9000         # 改为透传服务实际端口；不是代码默认值
```

`host`、`port` 均须显式填写；UI 的端口提示为 9000，不代表设备的实际设置。`python3 custom_components/peacefair/pzwifi.py` 会连接源码硬编码的 `192.168.1.89:9000`，不是离线测试，勿在未知网络环境直接运行。

## 代码约定与常用模式（Code Conventions & Common Patterns）

- 沿用 Python 四空格缩进、函数/变量 `snake_case`、类名 `PascalCase`、常量 `UPPER_SNAKE_CASE`；没有统一格式化配置，避免顺手重排无关代码。
- 实体定义集中在 `SENSOR_TYPES` 的 `SensorEntityDescription`；直接读数的 key 必须与 `PzSensorResult` 字段一致，派生实体 `power_rounded` 在实体层从 `power` 四舍五入到整数 W（0.5 向上取整）。现有拼写 **`freqency`** 同时用于结果字段、实体 key 和 `sensor.peacefair_freqency`，不能只改一处而忽略实体 ID 兼容性。
- 保持寄存器高低字顺序和缩放规则；电能使用 kWh 与 `TOTAL_INCREASING`，其他实体沿用各自单位和状态类别。
- 协议错误使用 `CRCError`、`BadValue`；`poll` 对超时、CRC 错误和 `BadValue` 共用最多六次尝试，空解析结果按 `BadValue` 重试。失败连接关闭后，等待 100 毫秒再开始下一次尝试；耗尽后直接抛出最后一次异常，不额外等待。每次尝试使用带超时的新连接并可靠关闭；其他连接错误直接上抛。
- 配置校验和 coordinator 轮询均必须通过 `hass.async_add_executor_job` 调用同步 socket；`async_config_entry_first_refresh` 只能在条目 setup 内等待完成后加载实体。
- 无数据时 `native_value` 返回 `None`；更新失败由 coordinator 标为 unavailable，不提供虚假测量值。实体唯一标识使用配置条目 ID 和 key；首次注册保留旧 `sensor.peacefair_*` ID，后续尊重注册表中的用户改名。修改地址不重建配置条目。
- 日志使用 `_LOGGER = logging.getLogger(__name__)`，协议报文只记 debug，不使用 print。

## 重要文件（Important Files）

- `config_flow.py`、`coordinator.py`、`sensor.py`、`pzwifi.py`（均在集成目录）：分别负责配置流程、共享轮询、实体与 YAML 导入、协议解析。
- `custom_components/peacefair/const.py`：集成域 `DOMAIN = "peacefair"`。
- `custom_components/peacefair/manifest.json` 与 `manifest.json.tpl`：运行时元数据及发布模板；修改共同元数据时同步两者，保留模板的 `%%%VERSION%%%` 占位符，发布时模板会覆盖 manifest。
- `hacs.json`：HACS 最低版本与 ZIP 安装约定；配置流文案在 `strings.json`、`translations/en.json` 和 `translations/zh-Hans.json`。
- `.github/workflows/release.yml`：main 推送或手动触发，按 Conventional Commits 生成版本/变更说明，再更新 manifest、打标签并发布 ZIP；会写回仓库，不要当作本地验证命令执行。
- `README.md`：硬件用途、UI 配置、升级路径和测试命令；`info.md`：简短 HACS 描述；`LICENSE`：MIT 许可。

## 运行时与工具偏好（Runtime/Tooling Preferences）

- 运行于 Home Assistant 的 Python 环境；`hacs.json` 声明最低 HA 版本 `2026.1.0`。单位使用 HA 枚举，运行时数据使用 `ConfigEntry.runtime_data`。不同 2026 小版本的依赖有所变化，不要将单版本通过等同所有版本验证。
- 使用与目标 HA 兼容的 Python；`requirements-test.txt` 固定当前测试依赖，README 说明早期 2026 测试环境。无 Node/Bun 工具链，无需添加前端依赖。
- manifest 的 `requirements`、`dependencies` 均为空：没有声明额外安装依赖，但集成层仍依赖 HA 及其环境；只有 `pzwifi.py` 可仅用标准库独立运行。

## 测试与质量检查（Testing & QA）

- 使用 unittest 和 pytest；尚无覆盖率门槛或 CI 质量关卡。发布成功不等于功能验证，语法与 CRC 冒烟检查也不能代替集成测试。
- 修改协议逻辑时运行协议回归：正常帧单位转换、错误 CRC、短帧、零功率、低功率因数、异常读数、TCP 分段及重试/关闭。测试只用本机模拟服务，不连接硬编码设备地址。
- 修改实体/轮询后，在兼容 HA 与可控设备环境检查七个实体、首次读数、约 5 秒更新、断线/超时后的状态及日志；涉及多设备时检查实体 ID 是否冲突。
- 区分真实 HA 测试实例（模拟计量设备）、本机 TCP 测试和实际设备验证；没有硬件时明确说明，不能以自动化通过替代实际 ESP32 通信验证。
