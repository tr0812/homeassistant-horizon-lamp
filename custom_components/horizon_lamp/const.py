"""Horizon Lamp 集成常量定义"""

from datetime import datetime

# 设备配置
DEFAULT_HOST = "192.168.50.100"
DEFAULT_PORT = 8855
DOMAIN = "horizon_lamp"
MANUFACTURER = "积光"
MODEL = "鱼缸灯"

# 命令字节
COMMANDS = {
    "off": bytes.fromhex("ee0006010202011f19cc"),
    "on": bytes.fromhex("ee0006010202011e18cc"),
    "discover": bytes.fromhex("ee0006000000000204cc"),  # 设备发现/状态检测
}

# 设备信息
DEVICE_INFO = {
    "identifiers": {(DOMAIN, "horizon_lamp_001")},
    "name": "积光鱼缸灯",
    "manufacturer": MANUFACTURER,
    "model": MODEL,
}


def calculate_time_checksum(year, month, day, hour, minute, second):
    """计算时间同步校验和"""
    bcd = lambda x: ((x // 10) << 4) | (x % 10)
    y, m, d, h, mi, s = bcd(year), bcd(month), bcd(day), bcd(hour), bcd(minute), bcd(second)
    xor_val = y ^ m ^ d ^ h ^ mi ^ s
    return xor_val ^ 0x0f


def build_time_sync_command(year, month, day, hour, minute, second):
    """构建时间同步命令"""
    def to_bcd(x):
        return (((x // 10) & 0xFF) << 4) | ((x % 10) & 0xFF)
    
    y = to_bcd(int(year) % 100)
    m = to_bcd(int(month))
    d = to_bcd(int(day))
    h = to_bcd(int(hour))
    mi = to_bcd(int(minute))
    s = to_bcd(int(second))
    
    xor_val = y ^ m ^ d ^ h ^ mi ^ s
    cs = xor_val ^ 0x0f
    cs = cs & 0xFF
    
    cmd = bytes([
        0xee, 0x00, 0x0c, 0x01, 0x02, 0x02, 0x01,
        0x03,
        y, m, d, h, mi, s,
        cs,
        0xcc
    ])
    return cmd
