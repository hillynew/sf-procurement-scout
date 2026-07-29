"""Optional vendor-portal credentials, read from the environment only.

Some portal data is visible only to a signed-in vendor. Bonfire's
`getMyOpportunitiesSectionData` returns the solicitations an agency has invited
you to or you have chosen to follow, and returns nothing at all to an anonymous
caller.

Bonfire issues a browser session cookie rather than an API token, so that
cookie is what this reads. Nothing is stored in the repo and nothing is written
back; set the variable in a `.env` (gitignored) or the deploy environment:

    SF_SCOUT_BONFIRE_COOKIE=<the whole Cookie header from a signed-in session>

To use different accounts per agency, add a host-specific override. The suffix
is the host's first label, uppercased, with non-alphanumerics as underscores:

    SF_SCOUT_BONFIRE_COOKIE_BROWARD=...      # broward.bonfirehub.com
    SF_SCOUT_BONFIRE_COOKIE_TRI_RAIL=...     # tri-rail.bonfirehub.com

Session cookies expire; when one does the source reports `inactive` again
rather than failing, and you re-paste a fresh value.
"""

from __future__ import annotations

import os
import re
from typing import Optional

ENV_BONFIRE_COOKIE = "SF_SCOUT_BONFIRE_COOKIE"


def host_suffix(host: str) -> str:
    """`broward.bonfirehub.com` -> `BROWARD`, `tri-rail...` -> `TRI_RAIL`."""
    label = (host or "").split(".")[0]
    return re.sub(r"[^A-Za-z0-9]", "_", label).upper()


def bonfire_cookie(host: str) -> Optional[str]:
    """The session cookie for this Bonfire tenant, if one is configured.

    A host-specific variable wins over the shared one, so a single account can
    cover most agencies while a second covers one.
    """
    specific = os.environ.get(f"{ENV_BONFIRE_COOKIE}_{host_suffix(host)}", "").strip()
    if specific:
        return specific
    shared = os.environ.get(ENV_BONFIRE_COOKIE, "").strip()
    return shared or None


def has_bonfire_cookie(host: str) -> bool:
    return bonfire_cookie(host) is not None


def describe_bonfire(host: str) -> str:
    """A short, credential-free description of what is configured."""
    suffix = host_suffix(host)
    if os.environ.get(f"{ENV_BONFIRE_COOKIE}_{suffix}", "").strip():
        return f"{ENV_BONFIRE_COOKIE}_{suffix}"
    if os.environ.get(ENV_BONFIRE_COOKIE, "").strip():
        return ENV_BONFIRE_COOKIE
    return "not set"
