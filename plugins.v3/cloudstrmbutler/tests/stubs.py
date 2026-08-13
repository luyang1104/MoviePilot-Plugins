"""Shared MoviePilot and Watchdog stubs for standard-library tests."""

from __future__ import annotations

import datetime
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakeLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class FakeSystemMessage:
    def __init__(self):
        self.messages = []

    def put(self, message):
        self.messages.append(message)


class FakeSettings:
    TZ = "UTC"

    @staticmethod
    def MP_DOMAIN(*args, **kwargs):
        return "http://localhost"


class FakeChain:
    def recognize_media(self, **kwargs):
        return None


class FakePluginBase:
    def __init__(self):
        self.systemmessage = FakeSystemMessage()
        self.chain = FakeChain()
        self.config = None

    def get_config(self, name=None):
        return None

    def get_data_path(self):
        return ROOT / "tests" / "tmp" / "plugin_data"

    def update_config(self, config):
        self.config = dict(config)

    def post_message(self, **kwargs):
        return None


class FakeEvent:
    def __init__(self, event_data=None):
        self.event_data = event_data


class FakeEventType:
    PluginAction = "plugin_action"


class FakeNotificationType:
    Plugin = "plugin"


class FakeMediaType:
    MOVIE = "movie"
    TV = "tv"


class FakeEventManager:
    @staticmethod
    def register(event_type):
        return lambda func: func


class FakeMetaInfoPath:
    def __init__(self, path):
        self.path = path
        self.cn_name = None
        self.year = None
        self.season = None
        self.begin_episode = None
        self.tmdbid = None


class FakeStringUtils:
    @staticmethod
    def format_ep(episodes):
        return str(episodes)


class FakeRequestUtils:
    def __init__(self, content_type=None):
        self.content_type = content_type

    def post(self, **kwargs):
        response = types.SimpleNamespace(status_code=200)
        return response


class FakeMediaServerHelper:
    def get_services(self, name_filters=None, type_filter=None):
        return {}

    def get_configs(self):
        return {}


class FakeBackgroundScheduler:
    def __init__(self, timezone=None):
        self.timezone = timezone
        self.jobs = []
        self.running = False

    def add_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))
        return self.jobs[-1]

    def get_jobs(self):
        return self.jobs

    def remove_all_jobs(self):
        self.jobs.clear()

    def print_jobs(self):
        pass

    def start(self):
        self.running = True

    def shutdown(self):
        self.running = False


class FakePollingObserver:
    def __init__(self, timeout=10):
        self.timeout = timeout
        self.handlers = []
        self.running = False

    def schedule(self, handler, path, recursive=True):
        self.handlers.append(handler)
        return handler

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def join(self, timeout=None):
        pass


class FakeFileSystemEventHandler:
    pass


class FakeWatchdogEvent:
    def __init__(self, src_path, dest_path=None, is_directory=False):
        self.src_path = src_path
        self.dest_path = dest_path or src_path
        self.is_directory = is_directory


class FakeTimezone(datetime.tzinfo):
    def utcoffset(self, dt):
        return datetime.timedelta(0)

    def dst(self, dt):
        return datetime.timedelta(0)

    def tzname(self, dt):
        return "UTC"


def _module(name, **attrs):
    module = types.ModuleType(name)
    module.__path__ = []
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def install_stubs():
    pytz = _module("pytz", timezone=lambda name: FakeTimezone())

    apscheduler = _module("apscheduler")
    apscheduler_schedulers = _module("apscheduler.schedulers")
    apscheduler_background = _module(
        "apscheduler.schedulers.background",
        BackgroundScheduler=FakeBackgroundScheduler,
    )
    apscheduler_schedulers.background = apscheduler_background
    apscheduler.schedulers = apscheduler_schedulers

    watchdog = _module("watchdog")
    watchdog_events = _module(
        "watchdog.events", FileSystemEventHandler=FakeFileSystemEventHandler
    )
    watchdog_observers = _module("watchdog.observers")
    watchdog_polling = _module(
        "watchdog.observers.polling", PollingObserver=FakePollingObserver
    )
    watchdog_observers.polling = watchdog_polling
    watchdog.events = watchdog_events
    watchdog.observers = watchdog_observers

    app = _module("app")
    app_core = _module("app.core")
    app_core_config = _module("app.core.config", settings=FakeSettings())
    app_core_event = _module(
        "app.core.event",
        eventmanager=FakeEventManager(),
        Event=FakeEvent,
    )
    app_core_metainfo = _module("app.core.metainfo", MetaInfoPath=FakeMetaInfoPath)
    app_helper = _module("app.helper")
    app_helper_mediaserver = _module(
        "app.helper.mediaserver", MediaServerHelper=FakeMediaServerHelper
    )
    app_log = _module("app.log", logger=FakeLogger())
    app_plugins = _module("app.plugins", _PluginBase=FakePluginBase)
    app_schemas = _module("app.schemas", MediaInfo=type("MediaInfo", (), {}))
    app_schemas_types = _module(
        "app.schemas.types",
        EventType=FakeEventType(),
        NotificationType=FakeNotificationType(),
        MediaType=FakeMediaType(),
    )
    app_utils = _module("app.utils")
    app_utils_http = _module("app.utils.http", RequestUtils=FakeRequestUtils)
    app_utils_string = _module("app.utils.string", StringUtils=FakeStringUtils())

    app.core = app_core
    app_core.config = app_core_config
    app_core.event = app_core_event
    app_core.metainfo = app_core_metainfo
    app.helper = app_helper
    app_helper.mediaserver = app_helper_mediaserver
    app.log = app_log
    app.plugins = app_plugins
    app.schemas = app_schemas
    app_schemas.types = app_schemas_types
    app.utils = app_utils
    app_utils.http = app_utils_http
    app_utils.string = app_utils_string

    modules = {
        "pytz": pytz,
        "apscheduler": apscheduler,
        "apscheduler.schedulers": apscheduler_schedulers,
        "apscheduler.schedulers.background": apscheduler_background,
        "watchdog": watchdog,
        "watchdog.events": watchdog_events,
        "watchdog.observers": watchdog_observers,
        "watchdog.observers.polling": watchdog_polling,
        "app": app,
        "app.core": app_core,
        "app.core.config": app_core_config,
        "app.core.event": app_core_event,
        "app.core.metainfo": app_core_metainfo,
        "app.helper": app_helper,
        "app.helper.mediaserver": app_helper_mediaserver,
        "app.log": app_log,
        "app.plugins": app_plugins,
        "app.schemas": app_schemas,
        "app.schemas.types": app_schemas_types,
        "app.utils": app_utils,
        "app.utils.http": app_utils_http,
        "app.utils.string": app_utils_string,
    }
    sys.modules.update(modules)
    return modules


def load_plugin_module():
    install_stubs()
    if "cloudstrmbutler" in sys.modules:
        return sys.modules["cloudstrmbutler"]
    spec = importlib.util.spec_from_file_location(
        "cloudstrmbutler",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["cloudstrmbutler"] = module
    spec.loader.exec_module(module)
    return module
