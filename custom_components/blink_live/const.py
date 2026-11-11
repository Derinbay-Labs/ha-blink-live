"""Constants for Blink Live View."""

from homeassistant.const import Platform

DOMAIN = "blink_live"
CONF_CAMERAS = "cameras"
PLATFORMS = [Platform.CAMERA]

# The login state kept in the config entry: what a token refresh needs, never the
# password. blinkpy's login_attributes returns Auth.data itself, which holds the
# password during login, so entry data is always built from these named keys.
ENTRY_DATA_KEYS = (
    "username",
    "token",
    "expires_in",
    "expiration_date",
    "refresh_token",
    "host",
    "region_id",
    "client_id",
    "account_id",
    "user_id",
    "hardware_id",
    "uid",
    "device_id",
)
