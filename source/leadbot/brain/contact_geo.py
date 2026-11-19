"""Pure canonical helpers used by the shared address parser; no geocoder calls."""
import re

_ТИПЫ_УЛИЦ = re.compile(
    r"(?i)\b(?:улица|ул\.?|проспект|пр-т|переулок|пер\.?|проезд|шоссе|бульвар|площадь|набережная)\b"
)


def house_key(value):
    return re.sub(r"\s+", "", str(value or "").lower().replace("ё", "е"))
