"""Constants for the xTool O1 Omni integration."""

DOMAIN = "xtool_omni"
MANUFACTURER = "xTool"
DEFAULT_PORT = 28900
DEFAULT_NAME = "xTool O1 Omni"

CONF_HOST = "host"
CONF_PORT = "port"

# Protocol
WS_MAGIC = b"\xba\xbe"
WS_TYPE_JSON = 0x04
GUEST_USER_ID = "mk-guest"
GUEST_USER_KEY = "bWFrZWJsb2NrLXh0b29s"  # base64("makeblock-xtool")

PING_INTERVAL = 5          # seconds between /v1/user/ping keep-alives
POLL_INTERVAL = 30         # seconds between full status polls
REQUEST_TIMEOUT = 10
RECONNECT_MIN = 5
RECONNECT_MAX = 120

# Endpoints
EP_PARITY = "/v1/user/parity"
EP_PING = "/v1/user/ping"
EP_MACHINE_INFO = "/v1/platform/device/machine-info"
EP_WIFI = "/v1/platform/wifi/connected-info"
EP_STATE_SYNC = "/v1/platform/device/state/sync"
EP_TEMP_HUMIDITY = "/v1/project/device/temp-humity"
EP_PERIPHERAL = "/v1/project/device/peripheral-status"
EP_INK_TANK = "/v1/project/device/ink-tank"
EP_MAINT_TANK = "/v1/project/device/maintenance-tank"
EP_HEAD_PARAM = "/v1/project/device/printer-head-param"
EP_TASK_LIST = "/v1/project/task/list"
EP_CONFIG = "/v1/platform/device/config"
EP_HOME = "/v1/project/control/home"
EP_MEASURE = "/v1/project/measure/start"

CONFIG_KEYS = [
    "processCount",
    "processTotalTime",
    "uvLampRunTime",
    "airPurifierRunTime",
    "airPurifierSpeed",
    "opticalPathRunTime",
    "beepEnable",
    "head1StandardCleanCount",
    "head1FlashCleanCount",
    "head1DeepCleanCount",
    "head2StandardCleanCount",
    "head2FlashCleanCount",
    "head2DeepCleanCount",
    "inkPadCleanedAt",
    "inkPadReplacedAt",
    "wiperBladeCleanedAt",
    "wiperBladeReplacedAt",
]

# Ink tank names by position, as the device reports them in /v1/project/device/info
INK_TANK_FALLBACK_NAMES = {
    1: "Cyan",
    2: "Magenta",
    3: "Yellow",
    4: "Black",
    5: "Varnish",
    6: "White",
}
