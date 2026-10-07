"""The one place that decides which URL we tell users to use.

Before this, three places did it independently: ``apps/authentication/views.py``
(OTP, reset, provisioning), ``apps/authentication/management/commands/
grant_c360_access.py``, and ``apps/portfolio/models.py``, where the URL was
hardcoded to ``http://128.2.1.25:5400`` and ignored the settings entirely. That
last one sends the first email a new account ever receives, which is how a third
of our traffic learned to arrive on a raw IP.

Two URLs are offered only when there are genuinely two. When
``FRONTEND_LAN_URL`` is unset, or is the same host as ``FRONTEND_PUBLIC_URL``,
the emails name one link and drop the "off-network / on-network" labels, which
only mean anything when a reader has to choose.
"""
from django.conf import settings


def brand():
    return getattr(settings, "APP_BRAND_NAME", "HFCB")


def _clean(name):
    # .strip() first: an env file written as "  FRONTEND_LAN_URL=http://..."
    # yields a leading space, and " http://host" is a dead link in every mail
    # client.
    return (getattr(settings, name, "") or "").strip().rstrip("/")


def frontend_urls():
    """Distinct frontend URLs, public first, in the order to show them."""
    urls = []
    for name in ("FRONTEND_PUBLIC_URL", "FRONTEND_LAN_URL"):
        url = _clean(name)
        if url and url not in urls:
            urls.append(url)
    return urls


def primary_url():
    """The single URL to use where only one will fit (a button, an href)."""
    urls = frontend_urls()
    return urls[0] if urls else ""


def _block(intro, paths):
    """`paths` maps a URL to the full link to print for it."""
    urls = frontend_urls()
    if not urls:
        return ""
    if len(urls) == 1:
        line = paths(urls[0])
        return f"{intro} {line}" if intro else line
    labels = ("Off-network (internet)", "On-network (office LAN)")
    lines = [intro] if intro else []
    lines += [f"  - {label}: {paths(url)}" for label, url in zip(labels, urls)]
    return "\n".join(lines)


def access_links_block():
    """Footer telling the reader where to open the tool."""
    return _block("Access the tool here:", lambda url: url)


def reset_links_block(token):
    """Password-reset link(s) carrying the token."""
    return _block("", lambda url: f"{url}/reset_password/confirm/{token}")
