"""Horizon Lamp 开关实体"""

import socket
import time
import logging
from datetime import datetime

from homeassistant.components.switch import SwitchEntity

from .const import (
    DOMAIN,
    COMMANDS,
    DEVICE_INFO,
    DEFAULT_HOST,
    DEFAULT_PORT,
    build_time_sync_command,
)

_LOGGER = logging.getLogger(__name__)

MAX_RETRIES = 3


def send_command(cmd_bytes, host, port, label=""):
    """发送命令到设备，timeout时自动重发"""
    for attempt in range(1, MAX_RETRIES + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        retry_info = f" (尝试 {attempt}/{MAX_RETRIES})" if attempt > 1 else ""
        _LOGGER.debug(f"[{label}]{retry_info}")
        _LOGGER.debug(f"  TX: {' '.join(f'{b:02x}' for b in cmd_bytes)}")
        
        try:
            sock.sendto(cmd_bytes, (host, port))
        except Exception as e:
            _LOGGER.error(f"发送失败: {e}")
            sock.close()
            continue
        
        # 监听响应
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock2.bind(('', port))
        sock2.settimeout(2)
        
        try:
            data, addr = sock2.recvfrom(256)
            _LOGGER.debug(f"  RX: {' '.join(f'{b:02x}' for b in data)}")
            sock.close()
            sock2.close()
            return data
        except socket.timeout:
            if attempt < MAX_RETRIES:
                _LOGGER.debug(f"RX: timeout, 重新发送...")
                sock.close()
                sock2.close()
                time.sleep(0.3)
                continue
            else:
                _LOGGER.warning(f"RX: timeout (设备无响应)")
                sock.close()
                sock2.close()
                return None
        except Exception as e:
            _LOGGER.error(f"接收错误: {e}")
            sock.close()
            sock2.close()
            return None
        finally:
            sock.close()
            sock2.close()
    
    return None


def power_off(host, port):
    """关闭灯"""
    return send_command(COMMANDS["off"], host, port, "Power OFF")


def power_on(host, port):
    """打开灯"""
    return send_command(COMMANDS["on"], host, port, "Power ON")


def time_sync(host, port):
    """同步时间"""
    now = datetime.now()
    cmd = build_time_sync_command(now.year, now.month, now.day, now.hour, now.minute, now.second)
    _LOGGER.info(f"Time Sync ({now.strftime('%Y-%m-%d %H:%M:%S')})")
    return send_command(cmd, host, port, "Time Sync")


class HorizonLampSwitch(SwitchEntity):
    """鱼缸灯开关"""

    def __init__(self, host, port):
        self._host = host
        self._port = port
        self._state = False  # 初始状态未知
        self._attr_is_on = False

    @property
    def name(self):
        return "鱼缸灯"

    @property
    def unique_id(self):
        return f"{DOMAIN}_switch"

    @property
    def device_info(self):
        return DEVICE_INFO

    @property
    def icon(self):
        return "mdi:fishbowl" if self._attr_is_on else "mdi:fishbowl-outline"

    def turn_on(self, **kwargs):
        """打开灯并同步时间"""
        # 1. 先开灯（设备进入可通讯状态）
        result = power_on(self._host, self._port)
        
        if result is not None:
            self._attr_is_on = True
            self.schedule_update_ha_state()
            
            # 2. 再同步时间
            time.sleep(0.5)  # 等待设备稳定
            time_sync(self._host, self._port)
        else:
            _LOGGER.warning("开灯命令发送失败或设备无响应")

    def turn_off(self, **kwargs):
        """关闭灯"""
        result = power_off(self._host, self._port)
        
        if result is not None:
            self._attr_is_on = False
            self.schedule_update_ha_state()
        else:
            _LOGGER.warning("关灯命令发送失败或设备无响应")
