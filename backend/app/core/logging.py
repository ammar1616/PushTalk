import json
import logging

# Names that every LogRecord already has. Anything else on a record came
# from an extra={...} in a log call, so it belongs in the JSON output.
_STANDARD_KEYS = set(logging.LogRecord("n", 0, "p", 0, "m", (), None).__dict__)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_KEYS:
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger().handlers[0].setFormatter(JsonFormatter())