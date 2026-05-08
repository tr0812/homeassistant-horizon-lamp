"""Horizon Lamp 集成入口"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT
from .switch import HorizonLampService

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """设置集成入口（Config Entry 方式）"""
    # 从配置中获取设备信息
    host = entry.data.get("host", DEFAULT_HOST)
    port = entry.data.get("port", DEFAULT_PORT)
    
    # 存储配置信息
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "host": host,
        "port": port,
    }
    
    _LOGGER.info(f"设置积光鱼缸灯: {host}:{port}")
    
    # 设置平台
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载集成入口"""
    # 获取服务实例并停止
    host = entry.data.get("host", DEFAULT_HOST)
    port = entry.data.get("port", DEFAULT_PORT)
    key = f"{host}:{port}"
    
    if key in HorizonLampService._instances:
        service = HorizonLampService._instances[key]
        await service.stop()
        del HorizonLampService._instances[key]
        _LOGGER.info(f"停止轮询服务: {key}")
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    
    return unload_ok
