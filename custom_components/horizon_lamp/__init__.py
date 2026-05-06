"""Horizon Lamp 集成入口"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT
from .switch import HorizonLampSwitch

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """设置集成入口（支持 YAML 配置）"""
    # 检查 YAML 配置
    if DOMAIN in config:
        conf = config[DOMAIN]
        host = conf.get("host", DEFAULT_HOST)
        port = conf.get("port", DEFAULT_PORT)
        
        _LOGGER.info(f"配置积光鱼缸灯: {host}:{port}")
        
        # 存储配置信息
        hass.data.setdefault(DOMAIN, {})["config"] = {
            "host": host,
            "port": port,
        }
        
        # 创建开关实体
        switch = HorizonLampSwitch(host, port)
        hass.data[DOMAIN]["switch"] = switch
        
        # 设置平台
        hass.async_add_job(
            hass.config_entries.async_forward_entry_setup(
                {"entry_id": "yaml", "data": {"host": host, "port": port}}, 
                "switch"
            )
        )
    
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """设置集成入口（Config Entry 方式）"""
    # 从配置中获取设备信息
    host = entry.data.get("host", DEFAULT_HOST)
    port = entry.data.get("port", DEFAULT_PORT)
    
    # 创建设开关实体
    switch = HorizonLampSwitch(host, port)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "switch": switch,
        "host": host,
        "port": port,
    }
    
    # 注册设备
    hass.data[DOMAIN]["switch"] = switch
    
    # 设置平台
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载集成入口"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    
    return unload_ok
