from __future__ import annotations
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_DEVICE_ID
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_UID

_LOGGER = logging.getLogger(__name__)

class KiwikConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kiwik."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # 可以在这里尝试连接验证
            return self.async_create_entry(
                title=f"Kiwik Lock {user_input[CONF_DEVICE_ID]}", 
                data=user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_UID): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_DEVICE_ID): str,
            }),
            errors=errors,
        )
