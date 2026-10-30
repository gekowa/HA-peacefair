# Peacefair 电能测量

自制的通过 Wi-Fi 通信的电能测量仪.

硬件解决方案简述:

1. 采用 Peacefair 品牌的电能测量模块, 通过钳流(开合式CT) 火线, 可以测得目标火线上的电流, 电压等数据, 计算得出电功率.
2. Peacefiar 通过TTL串口通信方式输出
3. 在 Peacefiar 的输出端接上 ESP32 主板, 实现把TTL信号透传到 Wi-Fi

本插件的作用就是通过配置 IP 地址, 可以读取 Peacefair 电能测量模块的数值.

## 安装与 UI 配置

面向 Home Assistant Core 2026。将本仓库的 `custom_components/peacefair/`
完整复制到 HA 配置目录下的同名目录，然后重启 Home Assistant。

首次安装：进入 **设置 → 设备与服务 → 添加集成**，搜索 **Peacefair Electricity**，
填写 ESP32 的 IP 地址（也支持主机名）和 TCP 透传端口。端口提示值为 `9000`，
请以设备实际配置为准。保存前会读取一次计量数据；无法连接或响应无效时会显示错误。

修改连接：在该集成条目的菜单中选择 **重新配置**，修改 IP 或端口。
保存成功后自动重新加载，无需删除集成或重建实体。提供简体中文和英文配置界面。

## 从旧版升级

1. 替换集成文件，暂时保留原来的 YAML 配置并重启 HA：

   ```yaml
   sensor:
     - platform: peacefair
       host: 192.168.1.89  # 改为自己的 ESP32 地址
       port: 9000         # 改为设备实际端口
   ```

2. 插件会将旧配置自动导入 **设置 → 设备与服务**。即使设备暂时离线，也会保存配置，
   并由 HA 重试连接。设备恢复后自动加载实体。
3. 确认集成已出现后，删除 YAML 中对应的 Peacefair 条目；保留其他 `sensor:` 配置。
   之后在 UI 中修改连接。遗留 YAML 不会覆盖已保存的 UI 配置。

升级沿用以下六个实体 ID；`freqency` 保留旧版拼写，避免影响已有引用：

| 实体 ID | 含义 | 单位 |
| --- | --- | --- |
| `sensor.peacefair_voltage` | 电压 | V |
| `sensor.peacefair_current` | 电流 | A |
| `sensor.peacefair_power` | 有功功率 | W |
| `sensor.peacefair_power_consumption` | 累计电量 | kWh |
| `sensor.peacefair_freqency` | 频率 | Hz |
| `sensor.peacefair_power_factor` | 功率因数 | 无单位，0–1 |

另外提供 `sensor.peacefair_power_rounded`，将当前有功功率四舍五入到整数 W
（小数部分为 0.5 时向上取整，例如 282.5 W → 283 W），原始 `power` 读数保持不变。

沿用原插件的单设备模式，每个 HA 实例只配置一个 Peacefair 集成条目。
修改 IP 和端口会保留实体的唯一标识，以及升级后在实体注册表中自定义的名称和 ID。

## 读数与异常处理

- 七个实体共享一次 TCP 读取，正常情况下约每 5 秒更新。
- 同步 TCP 操作在线程池运行，不阻塞 HA 事件循环。
- 保持原寄存器顺序、缩放和累计电量 `total_increasing` 状态类别。
- 零负载及低功率因数是合法读数；断线后实体显示“不可用”，不再用 220V／50Hz 代替实测数据。
- 检查响应长度、地址、功能码和 CRC，支持 TCP 分段接收；超时、CRC 错误或无效数据共用最多六次尝试，空解析结果也会重试，每次连接始终关闭。耗尽后抛出最后一次错误，实体显示不可用。

## 开发验证

发布工作流默认按 Conventional Commits 计算版本。需要指定更高的补丁版本时，
可先更新 `custom_components/peacefair/manifest.json` 的 `version`，工作流取该版本
与自动计算版本中的较高者。模板保留 `%%%VERSION%%%`。例如 manifest 指定 `1.0.1`
而自动计算为 `1.0.0` 时，发布 `1.0.1`；自动计算为 `1.1.0` 时则发布 `1.1.0`。
发布流程在版本文件准备好后创建标签，已有标签不会被强制覆盖。

仅协议层的离线回归检查（标准库，不需要安装 HA，不连接真实设备；包含本机 TCP 模拟）：

```bash
python3 -B -m unittest discover -s tests -p test_pzwifi.py
```

HA 配置流与生命周期测试使用真实 HA 测试实例，替换外部计量设备：

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements-test.txt
.venv/bin/python -m pytest -q
```

测试依赖固定到 Home Assistant 2026.10.4。早期 2026 版本可在独立环境中验证：

```bash
uv venv --python 3.13 /tmp/peacefair-ha2026-early
uv pip install --python /tmp/peacefair-ha2026-early/bin/python \
  --exclude-newer 2026-01-25 pytest-homeassistant-custom-component==0.13.308
/tmp/peacefair-ha2026-early/bin/python -m pytest -q
```

该环境使用 HA 2026.1.3，并将传递依赖限制到当时已发布的版本，避免旧测试环境引入未来的不兼容依赖。
自动化测试覆盖配置、YAML 导入、实体 ID、重新配置、轮询、断线恢复及协议边界；
仍需在实际 HA 实例和 ESP32/计量模块上确认设备通信。
