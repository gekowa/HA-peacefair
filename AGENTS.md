# Repository Guidelines

## 项目概览（Project Overview）

Peacefair 是 Home Assistant 自定义电能测量集成。硬件由 Peacefair 计量模块、开合式 CT 和 ESP32 组成；ESP32 将 TTL 串口数据透传到 Wi-Fi，集成通过本地 TCP 读取电压、电流、功率、电能、频率及功率因数。不是独立服务，也不包含 ESP32 固件。

## 架构与数据流（Architecture & Data Flow）

- **配置入口**：`sensor.py` 的 `async_setup_platform` 读取 YAML 中的 `host`、`port`，创建一个每 5 秒更新的 `DataUpdateCoordinator`，供六个 `PFSensor` 共享。
- **协议层**：`pzwifi.py` 的同步 `poll(host, port)` 发送固定读寄存器报文，接收响应；`decode_result` 校验 CRC、转换寄存器和单位，返回 `PzSensorResult` 命名元组。
- **状态与依赖传递**：配置由更新回调闭包捕获；coordinator 和实体描述通过构造函数传入实体。读数保存在 `coordinator.data`，`native_value` 按描述的 `key` 取属性；没有独立状态库或依赖注入容器。
- **实际启用路径**：`manifest.json` 设置 `config_flow: false`；`__init__.py` 的 setup/unload 实现被注释，`config_flow.__py__` 不是可加载的 `config_flow.py`。不要把这些模板残留当作有效配置入口。

## 关键目录（Key Directories）

- `custom_components/peacefair/`：完整可安装集成；协议解析与 HA 实体接入分别保留在 `pzwifi.py` 和 `sensor.py`，避免相互混杂。
- `custom_components/peacefair/translations/`：配置流翻译资源；当前配置流未启用，文案不等于有效配置 schema。
- `.github/workflows/`：发布自动化，不是测试流水线。仓库没有独立 `tests/`、`scripts/` 或构建产物目录。

## 开发命令（Development Commands）

以下命令均从仓库根目录执行；是直接调用现有工具，不是仓库预设任务。

```bash
# Python 语法检查；不验证 Home Assistant API 兼容性
python3 -m compileall -q custom_components/peacefair

# 无需 Home Assistant 或硬件的 CRC 冒烟检查
python3 -B -c 'import sys; sys.path.insert(0, "custom_components/peacefair"); import pzwifi as p; assert p.check_crc(p.MSG); bad = bytearray(p.MSG); bad[3] ^= 1; assert not p.check_crc(bad)'
```

- **构建**：无需编译。发布工作流在集成目录执行 `zip <archive> -r ./`，产物为 `peacefair.zip`，压缩包根目录直接包含集成文件。
- **测试 / lint**：没有配置测试运行器、formatter 或 lint 命令；不要声称存在 `pytest`、`ruff`、`npm test` 等项目任务。
- **运行**：将集成目录放入 HA 配置目录下的 `custom_components/peacefair/`，在 `configuration.yaml` 的现有 `sensor:` 列表中添加以下配置并重启 HA。示例由当前代码读取字段推导，需在目标 HA 实例验证：

```yaml
sensor:
  - platform: peacefair
    host: 192.168.1.89  # 改为 ESP32 地址
    port: 9000         # 改为透传服务实际端口；不是代码默认值
```

`host`、`port` 均无默认值，应显式填写。`python3 custom_components/peacefair/pzwifi.py` 会连接源码硬编码的 `192.168.1.89:9000`，不是离线测试，勿在未知网络环境直接运行。

## 代码约定与常用模式（Code Conventions & Common Patterns）

- 沿用 Python 四空格缩进、函数/变量 `snake_case`、类名 `PascalCase`、常量 `UPPER_SNAKE_CASE`；没有统一格式化配置，避免顺手重排无关代码。
- 实体定义集中在 `SENSOR_TYPES` 的 `SensorEntityDescription`；字段名必须与 `PzSensorResult` 一致。现有拼写 **`freqency`** 同时用于结果字段、实体 key 和 `sensor.peacefair_freqency`，不能只改一处而忽略实体 ID 兼容性。
- 保持寄存器高低字顺序和缩放规则；电能使用 kWh 与 `TOTAL_INCREASING`，其他实体沿用各自单位和状态类别。
- 协议错误使用 `CRCError`、`BadValue`；目前 `poll` 仅重试接收超时和 CRC 错误，共最多六次尝试，耗尽后返回 `None`。连接错误和 `BadValue` 不在此重试范围内。
- 异步函数不代表非阻塞：当前更新回调直接调用同步 socket，首次刷新调用也缺少 `await`。修改轮询时应核对 HA 事件循环与首次刷新生命周期，不要复制这些问题。
- 当前无数据时电压/频率返回 220/50，其余返回 `None`；这些是回退值，不是真实测量。实体 ID 也没有设备标识，改多设备支持或离线行为时必须考虑已有实体。
- 日志已有 `_LOGGER = logging.getLogger(__name__)`，新增诊断优先复用它；现有 `print` 是遗留调试输出，不是推荐规范。

## 重要文件（Important Files）

- `sensor.py`、`pzwifi.py`（均在集成目录）：分别是平台入口/实体定义与 TCP/CRC/寄存器解析的主要修改点。
- `custom_components/peacefair/const.py`：集成域 `DOMAIN = "peacefair"`。
- `custom_components/peacefair/manifest.json` 与 `manifest.json.tpl`：运行时元数据及发布模板；修改共同元数据时同步两者，保留模板的 `%%%VERSION%%%` 占位符，发布时模板会覆盖 manifest。
- `hacs.json`：HACS 兼容性与 ZIP 安装约定；`strings.json`、`translations/en.json` 位于集成目录，仍含未启用配置流的模板文案。
- `.github/workflows/release.yml`：main 推送或手动触发，按 Conventional Commits 生成版本/变更说明，再更新 manifest、打标签并发布 ZIP；会写回仓库，不要当作本地验证命令执行。
- `README.md`：硬件用途说明；`info.md`：简短 HACS 描述；`LICENSE`：MIT 许可。

## 运行时与工具偏好（Runtime/Tooling Preferences）

- 运行于 Home Assistant 的 Python 环境；`hacs.json` 声明最低 HA 版本 `2022.3.0`，但不代表已验证所有新版兼容性。源码使用旧版 HA 单位常量，升级 API 前先确认目标 HA 版本。
- 仓库未固定 Python 版本、包管理器或开发环境；使用与目标 HA 兼容的 Python。无 Node/Bun 工具链，无需添加前端依赖。
- manifest 的 `requirements`、`dependencies` 均为空：没有声明额外安装依赖，但集成层仍依赖 HA 及其环境；只有 `pzwifi.py` 可仅用标准库独立运行。

## 测试与质量检查（Testing & QA）

- 当前无自动化测试框架、覆盖率门槛或 CI 质量关卡；发布成功不等于功能验证。上面的语法与 CRC 命令只提供最小离线检查。
- 修改协议逻辑时，增加针对真实行为的最小回归检查：正常帧单位转换、错误 CRC、短帧、零功率及异常读数。注意当前零功率参与除法、帧长检查被注释，不能把这些边界视为已支持。
- 修改实体/轮询后，在兼容 HA 与可控设备环境检查六个实体、首次读数、约 5 秒更新、断线/超时后的状态及日志；涉及多设备时检查实体 ID 是否冲突。
- 无 HA 或硬件时，明确记录只完成了离线验证；不要以语法通过代替网络通信或 HA 加载验证。
