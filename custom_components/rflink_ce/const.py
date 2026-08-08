"""Constants for the RFLink CE integration."""

DOMAIN = "rflink_ce"

SUBENTRY_TYPE_DEVICE = "device"

CONF_UP_TIME = "up_time"
CONF_DOWN_TIME = "down_time"
CONF_ALIASES = "aliases"
CONF_GROUP_ALIASES = "group_aliases"
CONF_NOGROUP_ALIASES = "nogroup_aliases"
CONF_FIRE_EVENT = "fire_event"
CONF_SIGNAL_REPETITIONS = "signal_repetitions"
CONF_ENTITY_DOMAIN = "entity_domain"
CONF_IGNORE_PATTERNS = "ignore_patterns"
CONF_WAIT_FOR_ACK = "wait_for_ack"
CONF_RECONNECT_INTERVAL = "reconnect_interval"

DEFAULT_SIGNAL_REPETITIONS = 1
DEFAULT_RECONNECT_INTERVAL = 10
DEFAULT_WAIT_FOR_ACK = True

ENTITY_DOMAIN_COVER = "cover"
ENTITY_DOMAIN_SENSOR = "sensor"
ENTITY_DOMAINS = [ENTITY_DOMAIN_COVER, ENTITY_DOMAIN_SENSOR]

EVENT_KEY_ID = "id"
EVENT_KEY_COMMAND = "command"
EVENT_KEY_SENSOR = "sensor"
EVENT_KEY_UNIT = "unit"
EVENT_KEY_VALUE = "value"

SIGNAL_AVAILABILITY = "rflink_ce_available_{}"
SIGNAL_HANDLE_EVENT = "rflink_ce_handle_event_{}_{}"
SIGNAL_NEW_SENSOR_FIELD = "rflink_ce_new_sensor_field_{}"
SIGNAL_NEW_DEVICE = "rflink_ce_new_device_{}"

ISSUE_ID_UNCLASSIFIED_DEVICE = "unclassified_device_{}_{}"
