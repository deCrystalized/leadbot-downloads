"""Dependency-free event logger for the shared parser snapshot; never logs values."""
import logging


class _Logger:
    def warning(self, event, **_fields):
        logging.getLogger("leadbot.contact").warning("%s", event)

    def info(self, event, **_fields):
        logging.getLogger("leadbot.contact").info("%s", event)


def get_logger():
    return _Logger()
