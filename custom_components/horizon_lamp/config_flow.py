"""Horizon Lamp 配置流程"""

import ipaddress
import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT

_LOGGER = logging.getLogger(__name__)

# 用户配置数据Schema
DATA_SCHEMA = vol.Schema({
    vol.Required("host", default=DEFAULT_HOST): str,
    vol.Required("port", default=DEFAULT_PORT): vol.Coerce(int),
})


class HorizonLampConfigFlow(ConfigFlow, domain=DOMAIN):
    """积光鱼缸灯配置流程"""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """处理用户配置步骤"""
        errors = {}

        if user_input is not None:
            # 验证 IP 地址格式
            try:
                ipaddress.ip_address(user_input["host"])
            except ValueError:
                errors["host"] = "invalid_ip_address"
            
            # 验证端口范围
            if not (1 <= user_input["port"] <= 65535):
                errors["port"] = "invalid_port"

            if not errors:
                # 创建配置条目
                return self.async_create_entry(
                    title="积光鱼缸灯",
                    data={
                        "host": user_input["host"],
                        "port": user_input["port"],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "default_host": DEFAULT_HOST,
                "default_port": DEFAULT_PORT,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """获取选项配置流程"""
        return HorizonLampOptionsFlow(config_entry)


class HorizonLampOptionsFlow(OptionsFlow):
    """积光鱼缸灯选项流程"""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """处理选项配置步骤"""
        if user_input is not None:
            # 更新配置
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    "host": user_input["host"],
                    "port": user_input["port"],
                },
            )
            return self.async_create_entry(title="", data={})

        # 显示当前配置
        current_data = self.config_entry.data
        options_schema = vol.Schema({
            vol.Required("host", default=current_data.get("host", DEFAULT_HOST)): str,
            vol.Required("port", default=current_data.get("port", DEFAULT_PORT)): vol.Coerce(int),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
