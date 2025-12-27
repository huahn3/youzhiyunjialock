import logging
import threading
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_STATE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, EVENT_KIWIK_NOTIFICATION

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kiwik lock."""
    client = hass.data[DOMAIN][entry.entry_id]
    lock = KiwikLock(client, hass, entry)
    async_add_entities([lock])

class KiwikLock(LockEntity):
    """Representation of a Kiwik Lock."""

    def __init__(self, client, hass, entry):
        self._client = client
        self._hass = hass
        self._entry = entry
        self._attr_name = "Kiwik Smart Lock"
        self._attr_unique_id = f"kiwik_lock_{client.device_id}"
        self._is_locked = True # 默认为锁状态
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.device_id)},
            "name": "Kiwik Smart Lock",
            "manufacturer": "Kiwik",
        }

    async def async_added_to_hass(self):
        """Register callbacks."""
        self._client.set_callback(self._handle_client_event)

    def _handle_client_event(self, event_type, data):
        """Handle events from the client (Running in background thread)."""
        # 必须调度到主循环执行，否则 async_call_later 和状态更新会失败
        self._hass.loop.call_soon_threadsafe(self._process_event, event_type, data)

    @callback
    def _process_event(self, event_type, data):
        """Process event in HA loop."""
        _LOGGER.debug(f"收到客户端事件: {event_type} - {data}")
        
        if event_type == "STATE_UPDATE":
            if data == "UNLOCKED":
                if self._is_locked:
                    self._is_locked = False
                    self.async_write_ha_state()
                
                # 3秒后自动恢复为 LOCKED (模拟自动上锁)
                # 先取消可能的现有计时器 (当前实现暂不存储 cancel 回调，因为逻辑简单)
                async_call_later(self._hass, 3, self._auto_lock_callback)
                
            elif data == "LOCKED":
                if not self._is_locked:
                    self._is_locked = True
                    self.async_write_ha_state()

        elif event_type == "EVENT":
            # 触发 Home Assistant 事件
            self._hass.bus.async_fire(EVENT_KIWIK_NOTIFICATION, data)

    @callback
    def _auto_lock_callback(self, *args):
        """Auto lock callback."""
        _LOGGER.info("执行自动上锁逻辑")
        self._is_locked = True
        self.async_write_ha_state()

    @property
    def is_locked(self) -> bool:
        """Return true if lock is locked."""
        return self._is_locked

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the device."""
        # API 不支持远程关锁，仅更新状态
        self._is_locked = True
        self.async_write_ha_state()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the device."""
        await self._hass.async_add_executor_job(self._client.unlock)

