from typing import Optional


def get_cookie_value(cookie: str, cookie_name: str) -> Optional[str]:
    """Return the value of the cookie named ``cookie_name``.

    The name match is case-insensitive and also accepts a suffix appended with
    ``-`` (for example a server port). This tolerates the two DT cookie layouts:

    * ``z-auth-code=xxx`` / ``forgerydefense=xxx``                 (no port)
    * ``z-auth-code-28001=xxx`` / ``forgerydefense-28001=xxx``     (port in domain)

    When both an exact-name and a suffixed cookie are present, the exact name
    wins.
    """
    if not cookie or not cookie_name:
        return None

    lower_name = cookie_name.lower()
    suffixed_value = None
    for item in cookie.split(';'):
        key, separator, value = item.strip().partition('=')
        if not separator:
            continue
        lower_key = key.strip().lower()
        if lower_key == lower_name:
            return value.strip()
        if suffixed_value is None and lower_key.startswith(lower_name + '-'):
            suffixed_value = value.strip()
    return suffixed_value
