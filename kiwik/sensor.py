import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kiwik sensor."""
    client = hass.data[DOMAIN][entry.entry_id]
    sensor = KiwikEventSensor(client, hass)
    async_add_entities([sensor])

class KiwikEventSensor(SensorEntity):
    """Representation of a Kiwik Event Sensor."""

    def __init__(self, client, hass):
        self._client = client
        self._hass = hass
        self._attr_name = "Kiwik Last Event"
        self._attr_unique_id = f"kiwik_event_{client.device_id}"
        self._state = "Waiting..."
        self._attr_extra_state_attributes = {}
        self._attr_icon = "mdi:history"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.device_id)},
            "name": "Kiwik Smart Lock",
            "manufacturer": "Kiwik",
        }

    async def async_added_to_hass(self):
        """Register callbacks."""
        self._client.add_sensor_callback(self._handle_client_event)

    @callback
    def _handle_client_event(self, event_type, data):
        """Handle events from the client (Running in background thread)."""
        self._hass.loop.call_soon_threadsafe(self._process_event, event_type, data)

    @callback
    def _process_event(self, event_type, data):
        """Process event in HA loop."""
        if event_type == "EVENT":
            # 尝试提取有用的信息
            # 假设 payload 中可能有 event, name, type 等字段
            event_name = data.get("event") or data.get("name") or data.get("type") or "Unknown"
            self._state = str(event_name)
            self._attr_extra_state_attributes = data
            self.async_write_ha_state()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state
