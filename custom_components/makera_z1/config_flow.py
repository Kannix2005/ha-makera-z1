"""Config flow: enter the machine's IP address; it is checked with one status query."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST

from .const import DOMAIN
from .protocol import MakeraClient, MakeraError


class MakeraConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(host.lower())
            self._abort_if_unique_id_configured()
            try:
                status = await MakeraClient(host).status()
            except MakeraError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=f"Makera {status.model or 'Z1'}", data={CONF_HOST: host})
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required(CONF_HOST): str}), errors=errors)
