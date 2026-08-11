"""Accept a missing trailing slash WITHOUT a 301 redirect.

The frontend is served behind a Next.js proxy that strips the trailing slash when
forwarding to this backend (e.g. ``POST /auth/generate-otp`` instead of
``…/generate-otp/``). Django's ``APPEND_SLASH`` would answer that with a 301, which
drops the POST body and breaks login/OTP.

This middleware instead **internally rewrites** the path to its slashed form when
that form resolves to a view — no redirect, so POST bodies survive. It runs before
``CommonMiddleware`` so the APPEND_SLASH 301 never triggers.
"""

from django.urls import resolve
from django.urls.exceptions import Resolver404


class ProxyAppendSlashMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if path and not path.endswith("/"):
            last_segment = path.rsplit("/", 1)[-1]
            # Skip things that look like files (static assets, .json, etc.).
            if "." not in last_segment:
                try:
                    resolve(path + "/")
                except Resolver404:
                    pass
                else:
                    request.path_info = path + "/"
                    if not request.path.endswith("/"):
                        request.path = request.path + "/"
        return self.get_response(request)
