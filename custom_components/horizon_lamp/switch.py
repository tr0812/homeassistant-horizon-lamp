"""Horizon Lamp 开关实体"""

import asyncio
import socket
import time
import logging
from datetime import datetime

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta

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
UPDATE_INTERVAL = 30  # 状态轮询间隔（秒）


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
        sock2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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


def get_lamp_status(host, port):
    """获取灯状态 - 有响应返回True，无响应返回False"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', port))
    sock.settimeout(2)
    
    try:
        sock.sendto(COMMANDS["discover"], (host, port))
        data, addr = sock.recvfrom(256)
        sock.close()
        _LOGGER.debug(f"状态检测: 灯开着 (收到响应)")
        return True  # 有响应 = 灯开着
    except socket.timeout:
        sock.close()
        _LOGGER.debug(f"状态检测: 灯关闭 (无响应)")
        return False  # 无响应 = 灯关闭


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """设置开关实体"""
    host = entry.data.get("host", DEFAULT_HOST)
    port = entry.data.get("port", DEFAULT_PORT)
    
    switch = HorizonLampSwitch(hass, host, port)
    async_add_entities([switch], update_before_add=True)
    
    # 初始化时查询当前灯状态
    initial_state = await hass.async_add_executor_job(get_lamp_status, host, port)
    switch._attr_is_on = initial_state
    # 使用延迟调用确保实体已添加到 HA
    hass.async_create_task(switch.async_update())
    _LOGGER.info(f"初始化状态: {'开启' if initial_state else '关闭'}")
    
    # 启动定时轮询
    switch.start_polling(hass)


class HorizonLampSwitch(SwitchEntity):
    """鱼缸灯开关"""

    def __init__(self, hass, host, port):
        self._hass = hass
        self._host = host
        self._port = port
        self._attr_is_on = False
        self._unsub_poller = None
        self._is_controlling = False  # 用户正在操作中

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

    def start_polling(self, hass):
        """启动定时轮询状态"""
        if self._unsub_poller is None:
            self._unsub_poller = async_track_time_interval(
                hass,
                self._async_update_status,
                timedelta(seconds=UPDATE_INTERVAL)
            )
            _LOGGER.info(f"启动状态轮询，间隔 {UPDATE_INTERVAL} 秒")

    def stop_polling(self):
        """停止定时轮询"""
        if self._unsub_poller is not None:
            self._unsub_poller()
            self._unsub_poller = None
            _LOGGER.info("停止状态轮询")

    async def _async_update_status(self, now=None):
        """定时更新状态回调"""
        # 如果正在执行控制命令，跳过本次状态更新
        if self._is_controlling:
            _LOGGER.debug("正在控制中，跳过本次状态更新")
            return
        
        # 在线程池中执行阻塞的网络操作
        new_state = await self._hass.async_add_executor_job(
            get_lamp_status, self._host, self._port
        )
        
        # 状态变化时更新
        if new_state != self._attr_is_on:
            _LOGGER.info(f"状态变化: {'开启' if new_state else '关闭'}")
            self._attr_is_on = new_state
            self.async_write_ha_state()

    def turn_on(self, **kwargs):
        """打开灯并同步时间"""
        self._is_controlling = True
        try:
            # 1. 先开灯（设备进入可通讯状态）
            result = power_on(self._host, self._port)
            
            if result is not None:
                self._attr_is_on = True
                self.schedule_update_ha_state()
                
                # 2. 再同步时间
                time_sync(self._host, self._port)
            else:
                _LOGGER.warning("开灯命令发送失败或设备无响应")
        finally:
            # 操作后等待 10 秒再允许轮询
            self._hass.loop.call_later(10, self._delayed_unblock_callback)

    def turn_off(self, **kwargs):
        """关闭灯"""
        self._is_controlling = True
        try:
            result = power_off(self._host, self._port)
            
            if result is not None:
                self._attr_is_on = False
                self.schedule_update_ha_state()
                _LOGGER.info("关灯命令已发送")
            else:
                _LOGGER.warning("关灯命令发送失败或设备无响应")
        finally:
            # 操作后等待 10 秒再允许轮询
            self._hass.loop.call_later(10, self._delayed_unblock_callback)

    def _delayed_unblock_callback(self):
        """延迟解除控制状态的回调"""
        self._is_controlling = False
        _LOGGER.debug("控制状态已解除，轮询恢复")
    
    async def async_update(self):
        """实体更新时获取状态"""
        new_state = await self._hass.async_add_executor_job(
            get_lamp_status, self._host, self._port
        )
        self._attr_is_on = new_state