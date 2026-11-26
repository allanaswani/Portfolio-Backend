"""Stops two unauthenticated denial-of-service requests before DRF parses them.

DRF 3.17.2 has both bugs (CVE-2026-114138, CVE-2026-114136). The fix,
DRF 3.18.2, needs Django 5.2, and Django 5.2 needs PostgreSQL 14; both
database hosts run PostgreSQL 12. Until the database moves, this guard closes
the two doors:

* **Accept header.** DRF parses every Accept token several times and Django's
  header parser is quadratic on a crafted value: one 780 KB header held a
  worker for 19 seconds. Browsers and our own scripts send well under 1 KB.
* **Content-Type charset.** DRF decodes a JSON body with the charset the
  client names, and Python accepts compression codecs there
  (``charset=zlib_codec``): a 108-byte body became 50 million characters.
  Only text charsets are let through.
"""
from django.http import HttpResponse

MAX_ACCEPT_BYTES = 2048

TEXT_CHARSETS = frozenset({
    "utf-8", "utf8", "us-ascii", "ascii", "iso-8859-1", "latin-1", "latin1",
    "windows-1252", "cp1252",
})


def _charset(content_type):
    for part in content_type.split(";")[1:]:
        name, _, value = part.partition("=")
        if name.strip().lower() == "charset":
            return value.strip().strip('"').strip("'").lower()
    return None


class RequestGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if len(request.META.get("HTTP_ACCEPT", "")) > MAX_ACCEPT_BYTES:
            return HttpResponse("Accept header too large.", status=400,
                                content_type="text/plain")
        charset = _charset(request.META.get("CONTENT_TYPE", ""))
        if charset is not None and charset not in TEXT_CHARSETS:
            return HttpResponse("Unsupported charset.", status=415,
                                content_type="text/plain")
        return self.get_response(request)
