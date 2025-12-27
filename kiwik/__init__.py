from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, CONF_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_UID
from .kiwik_api import KiwikClient

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Kiwik component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Set up Kiwik from a config entry."""
    uid = entry.data[CONF_UID]
    password = entry.data[CONF_PASSWORD]
    device_id = entry.data[CONF_DEVICE_ID]
    
    # 获取之前保存的 token (如果有)
    # 也可以存放在 entry.data 中，但为了频繁更新 refresh_token，使用 hass.data 或者一个持久化文件更好。
    # 这里简单起见，每次启动让 Client 自己管理文件，或者直接存到 entry options 里。
    # 为了简化，我们让 Client 内部管理 kiwik_token.json (默认在运行目录下，HA里可能需要指定 path)
    
    # 更好做法：把 Token 存进 entry data
    token_data = entry.data.get("token_data", {})

    client = KiwikClient(uid, password, device_id, token_data=token_data)
    
    # 尝试登录/验证 (在 executor 中运行，因为 client 是同步的 request)
    logged_in = await hass.async_add_executor_job(client.login)
    
    if not logged_in:
        _LOGGER.error("Kiwik 登录失败，请检查配置")
        return False

    # 更新 token 到 entry，以便下次使用
    if client.access_token:
        new_data = entry.data.copy()
        new_data["token_data"] = {
            "access_token": client.access_token,
            "refresh_token": client.refresh_token
        }
        hass.config_entries.async_update_entry(entry, data=new_data)

    hass.data[DOMAIN][entry.entry_id] = client

    # 启动后台监听
    client.start()

    # 加载 Lock 和 Sensor 平台
    platforms = ["lock", "sensor"]
    await hass.config_entries.async_forward_entry_setups(entry, platforms)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Unload a config entry."""
    client = hass.data[DOMAIN][entry.entry_id]
    client.stop()
    
    platforms = ["lock", "sensor"]
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
