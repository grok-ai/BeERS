import logging
from datetime import datetime
from typing import Optional

import dotenv
from rich.console import ConsoleRenderable
from rich.logging import RichHandler
from rich.traceback import Traceback


# TODO: not working properly :]
class NNRichHandler(RichHandler):
    def render(
        self,
        *,
        record: logging.LogRecord,
        traceback: Optional[Traceback],
        message_renderable: ConsoleRenderable,
    ) -> ConsoleRenderable:
        # Hack to display the logger name instead of the filename in the rich logs
        path = record.name  # str(Path(record.pathname))
        level = self.get_level_text(record)
        time_format = None if self.formatter is None else self.formatter.datefmt
        log_time = datetime.fromtimestamp(record.created)

        log_renderable = self._log_render(
            self.console,
            [message_renderable] if not traceback else [message_renderable, traceback],
            log_time=log_time,
            time_format=time_format,
            level=level,
            path=path,
            line_no=record.lineno,
            link_path=record.pathname if self.enable_link_path else None,
        )
        return log_renderable


handler = NNRichHandler(
    rich_tracebacks=True,
    show_level=True,
    show_path=True,
    show_time=True,
    omit_repeated_times=True,
)
FORMAT = "%(message)s"
logging.basicConfig(
    format=FORMAT,
    level=logging.DEBUG,
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[handler],
)

# Remove all handlers associated with the fastapi logger.
# try:
#     from fastapi.logger import logger as fastapi_logger
#
#     fastapi_logger.handlers = [handler]
#     fastapi_logger.propagate = True
# except Exception:
#     pass

dotenv.load_dotenv(dotenv_path=None, override=True)

try:
    from ._version import __version__ as __version__
except ImportError:
    import sys

    print(
        "Project not installed in the current env, activate the correct env or install it with:\n\tpip install -e .",
        file=sys.stderr,
    )
    __version__ = "unknown"
