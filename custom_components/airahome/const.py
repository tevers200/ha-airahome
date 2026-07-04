"""Constants for the Aira Heat Pump integration."""
DOMAIN = "airahome"

# Configuration
CONF_MAC_ADDRESS = "mac_address"
CONF_CLOUD_EMAIL = "cloud_email"
CONF_CLOUD_PASSWORD = "cloud_password"
CONF_NUM_ZONES = "num_zones"
CONF_NUM_PHASES = "num_phases"
CONF_CERTIFICATE = "certificate"
CONF_INSTALLATION = "installation"
CONF_DEVICE_UUID = "device_uuid"
CONF_DEVICE_NAME = "device_name"
CONF_SCAN_INTERVAL = "scan_interval"

# Default values
DEFAULT_SHORT_NAME = "Aira HP"
DEFAULT_NAME = "Aira Heat Pump"
DEFAULT_SCAN_INTERVAL = 30  # seconds - coordinator waits for completion before next cycle
DEFAULT_NUM_ZONES = 1
DEFAULT_NUM_PHASES = 3
STALE_DATA_THRESHOLD = 600  # seconds (10 minutes) - keep old data if fresher than this

# BLE connection timeouts (increased for poor connectivity scenarios)
BLE_CONNECT_TIMEOUT = 30  # seconds - timeout for establishing BLE connection
BLE_DISCOVERY_TIMEOUT = 20  # seconds - timeout for BLE device discovery
BLE_COMMAND_SLEEP = 1.5  # seconds - delay between BLE commands to avoid overwhelming the device
BLE_RECONNECT_BACKOFF = (30, 60, 120, 240)  # seconds to wait after each reconnect attempt before the next

# Attributes
ATTR_MAC_ADDRESS = "mac_address"
ATTR_DEVICE_UUID = "device_uuid"
ATTR_FIRMWARE_VERSION = "firmware_version"
ATTR_MODEL = "model"
ATTR_CONNECTION_TYPE = "connection_type"

# Cooling dew-point safety net (Phase 1: read-only observation)
DEFAULT_DEW_POINT_MARGIN_C = 2.0  # hold cooling supply this far above the dew point
# Zone cooling supply limits taken from the commissioned CCV config. Phase 3 will
# read these live from the device configuration instead of assuming defaults.
DEFAULT_COOLING_SUPPLY_MIN_C = 10.0
DEFAULT_COOLING_SUPPLY_MAX_C = 20.0

# Supported device types
SUPPORTED_DEVICE_TYPES = ["heat_pump"]

# Default data structure
DEFAULT_DATA = {
    "state": {},
    "system_check_state": {},
    "connected": False,
    "rssi": None,
}