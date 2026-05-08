#!/usr/bin/env python3
"""
Horizon Lamp Switch - 积光鱼缸灯 Home Assistant 集成
基于订阅-发布模式的状态同步架构

架构设计：
- HorizonLampService: 异步轮询服务，持续检测灯状态，状态变化时通知订阅者
- HorizonLampSwitch: 开关实体，订阅状态变化通知

命令格式:
  ON:       ee 00 06 01 02 02 01 1e 18 cc
  OFF:      ee 00 06 01 02 02 01 1f 19 cc
  DISCOVER: ee 00 06 00 00 00 02 04 cc (设备发现/状态检测)
  TIME:     ee 00 0c 01 02 02 01 03 [YY] [MM] [DD] [HH] [MM] [SS] [CS] cc

状态检测逻辑:
  - 使用 DISCOVER 命令 (0x00 类型)
  - 有响应 → 灯开着
  - 无响应 → 灯关闭
"""

import asyncio
import socket
import logging
from datetime import datetime
from typing import Callable, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    COMMANDS,
    DEVICE_INFO,
    DEFAULT_HOST,
    DEFAULT_PORT,
    build_time_sync_command,
)

_LOGGER = logging.getLogger(__name__)

# 调试开关
_DEBUG_MODE = True

# 命令重试次数
MAX_RETRIES = 3

# 轮询间隔（秒）
POLL_INTERVAL = 10

# 手动操作后忽略轮询通知的时间（秒）
COOLDOWN_AFTER_MANUAL = 30


class HorizonLampService:
    """积光鱼缸灯服务 - 管理异步轮询任务"""

    _instances: dict[str, 'HorizonLampService'] = {}

    def __init__(self, hass: HomeAssistant, host: str, port: int):
        self._hass = hass
        self._host = host
        self._port = port
        self._task: Optional[asyncio.Task] = None
        self._subscribers: list[Callable[[bool], None]] = []
        self._current_state: Optional[bool] = None
        self._running = False

    @classmethod
    def get_instance(cls, hass: HomeAssistant, host: str, port: int) -> 'HorizonLampService':
        """获取或创建服务实例"""
        key = f"{host}:{port}"
        if key not in cls._instances:
            cls._instances[key] = HorizonLampService(hass, host, port)
        return cls._instances[key]

    def subscribe(self, callback: Callable[[bool], None]) -> None:
        """订阅状态变化通知"""
        if callback not in self._subscribers:
            self._subscribers.append(callback)
            _LOGGER.info(f"[服务] 新订阅者, 当前状态={self._current_state}")
            # 立即通知当前状态
            if self._current_state is not None:
                callback(self._current_state)

    def unsubscribe(self, callback: Callable[[bool], None]) -> None:
        """取消订阅"""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify_subscribers(self, state: bool) -> None:
        """通知所有订阅者状态变化"""
        for callback in self._subscribers:
            try:
                callback(state)
            except Exception as e:
                _LOGGER.error(f"[服务] 通知订阅者失败: {e}")

    async def start(self) -> None:
        """启动轮询服务"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        _LOGGER.info(f"[服务] 启动轮询服务, 间隔={POLL_INTERVAL}秒")

    async def stop(self) -> None:
        """停止轮询服务"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        _LOGGER.info("[服务] 停止轮询服务")

    async def _poll_loop(self) -> None:
        """轮询循环"""
        while self._running:
            try:
                # 在线程池中执行阻塞的网络操作
                state = await self._hass.async_add_executor_job(
                    get_lamp_status, self._host, self._port
                )
                
                # 状态变化时通知订阅者
                if state != self._current_state:
                    _LOGGER.info(f"[服务] 状态变化: {'开启' if state else '关闭'}")
                    self._current_state = state
                    self._notify_subscribers(state)
                
            except Exception as e:
                _LOGGER.error(f"[服务] 轮询错误: {e}")
            
            # 等待下一次轮询
            await asyncio.sleep(POLL_INTERVAL)

    @property
    def current_state(self) -> Optional[bool]:
        """获取当前状态"""
        return self._current_state


def send_command(cmd_bytes, host, port, label=""):
    """发送命令到设备，timeout时自动重发"""
    for attempt in range(1, MAX_RETRIES + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        retry_info = f" (尝试 {attempt}/{MAX_RETRIES})" if attempt > 1 else ""
        if _DEBUG_MODE:
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
            if _DEBUG_MODE:
                _LOGGER.debug(f"  RX: {' '.join(f'{b:02x}' for b in data)}")
            sock.close()
            sock2.close()
            return data
        except socket.timeout:
            if attempt < MAX_RETRIES:
                if _DEBUG_MODE:
                    _LOGGER.debug(f"RX: timeout, 重新发送...")
                sock.close()
                sock2.close()
                import time
                time.sleep(0.3)
                continue
            else:
                if _DEBUG_MODE:
                    _LOGGER.debug(f"RX: timeout (设备无响应)")
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
        
        # 解析设备信息
        if len(data) >= 14:
            device_id = data[8:14].decode('ascii', errors='ignore').strip()
            if _DEBUG_MODE:
                _LOGGER.debug(f"状态检测: 灯开着 (收到响应, 设备ID: {device_id})")
        else:
            if _DEBUG_MODE:
                _LOGGER.debug(f"状态检测: 灯开着 (收到响应)")
        
        return True  # 有响应 = 灯开着
    except socket.timeout:
        sock.close()
        if _DEBUG_MODE:
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
    
    # 获取或创建服务实例
    service = HorizonLampService.get_instance(hass, host, port)
    
    # 启动轮询服务
    await service.start()
    
    # 创建开关实体
    switch = HorizonLampSwitch(hass, host, port, service)
    async_add_entities([switch], update_before_add=True)
    
    _LOGGER.info(f"积光鱼缸灯集成已设置: {host}:{port}")


class HorizonLampSwitch(SwitchEntity):
    """鱼缸灯开关 - 基于订阅-发布模式"""

    def __init__(self, hass: HomeAssistant, host: str, port: int, service: HorizonLampService):
        self._hass = hass
        self._host = host
        self._port = port
        self._service = service
        self._attr_is_on = False
        self._last_manual_time: Optional[float] = None  # 上次手动操作时间

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

    async def async_added_to_hass(self) -> None:
        """实体添加到 Home Assistant 时调用"""
        # 订阅状态变化通知
        self._service.subscribe(self._on_state_changed)
        # 初始化当前状态
        self._attr_is_on = self._service.current_state if self._service.current_state is not None else False
        _LOGGER.info(f"[实体] 已订阅状态变化, 当前状态={self._attr_is_on}")

    async def async_will_remove_from_hass(self) -> None:
        """实体从 Home Assistant 移除时调用"""
        self._service.unsubscribe(self._on_state_changed)
        _LOGGER.info("[实体] 已取消订阅状态变化")

    def _on_state_changed(self, state: bool) -> None:
        """状态变化回调（从轮询服务调用）"""
        # 检查冷却时间
        import time
        current_time = time.time()
        if self._last_manual_time is not None:
            elapsed = current_time - self._last_manual_time
            if elapsed < COOLDOWN_AFTER_MANUAL:
                _LOGGER.info(f"[实体] 忽略轮询通知 (冷却中, 剩余 {COOLDOWN_AFTER_MANUAL - elapsed:.1f}秒)")
                return
        
        _LOGGER.info(f"[实体] 收到状态变化通知: {'开启' if state else '关闭'}")
        self._attr_is_on = state
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """打开灯（异步版本）"""
        _LOGGER.info(f"[turn_on] 开始开灯, 当前状态={self._attr_is_on}")
        
        # 记录手动操作时间
        import time
        self._last_manual_time = time.time()
        
        # 在线程池中执行网络操作
        result = await self._hass.async_add_executor_job(
            power_on, self._host, self._port
        )
        
        if result is not None:
            # 命令发送成功，立即更新状态
            self._attr_is_on = True
            self.async_write_ha_state()
            _LOGGER.info("[turn_on] 开灯成功")
            
            # 同步时间
            await self._hass.async_add_executor_job(
                time_sync, self._host, self._port
            )
        else:
            _LOGGER.warning("[turn_on] 开灯命令发送失败或设备无响应")

    async def async_turn_off(self, **kwargs) -> None:
        """关闭灯（异步版本）"""
        _LOGGER.info(f"[turn_off] 开始关灯, 当前状态={self._attr_is_on}")
        
        # 记录手动操作时间
        import time
        self._last_manual_time = time.time()
        
        # 在线程池中执行网络操作
        result = await self._hass.async_add_executor_job(
            power_off, self._host, self._port
        )
        
        if result is not None:
            # 命令发送成功，立即更新状态
            self._attr_is_on = False
            self.async_write_ha_state()
            _LOGGER.info("[turn_off] 关灯成功")
        else:
            _LOGGER.warning("[turn_off] 关灯命令发送失败或设备无响应")

    # 同步版本的 turn_on/turn_off 供兼容性使用
    def turn_on(self, **kwargs) -> None:
        """打开灯"""
        self._hass.create_task(self.async_turn_on(**kwargs))

    def turn_off(self, **kwargs) -> None:
        """关闭灯"""
        self._hass.create_task(self.async_turn_off(**kwargs))
