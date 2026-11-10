"""Constants for the Makera Z1 integration."""
from datetime import timedelta
import logging

DOMAIN = "makera_z1"
LOGGER = logging.getLogger(__package__)

IDLE_INTERVAL = timedelta(seconds=10)
BUSY_INTERVAL = timedelta(seconds=2)
OFFLINE_INTERVAL = timedelta(seconds=30)
