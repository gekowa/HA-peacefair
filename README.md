# Peacefair 电能测量
自制的通过 Wi-Fi 通信的电能测量仪.

硬件解决方案简述:

1. 采用 Peacefair 品牌的电能测量模块, 通过钳流(开合式CT) 火线, 可以测得目标火线上的电流, 电压等数据, 计算得出电功率.
2. Peacefiar 通过TTL串口通信方式输出
3. 在 Peacefiar 的输出端接上 ESP32 主板, 实现把TTL信号透传到 Wi-Fi

本插件的作用就是通过配置 IP 地址, 可以读取 Peacefair 电能测量模块的数值.
