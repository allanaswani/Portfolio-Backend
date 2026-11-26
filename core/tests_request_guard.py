"""The two DRF 3.17 denial-of-service requests are refused before DRF parses
them; ordinary requests pass (26 Nov 2026)."""
import zlib

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

LOGIN = "/auth/api/token/"


class RequestGuardTests(TestCase):
    def setUp(self):
        User.objects.create_user("rm", password="pw-123456")
        self.client = APIClient()

    def test_a_huge_accept_header_is_refused(self):
        token = 'text/html;q="' + ";" * 4000 + '"'
        got = self.client.get(LOGIN, HTTP_ACCEPT=", ".join([token] * 3))
        self.assertEqual(got.status_code, 400)

    def test_a_compression_charset_is_refused_without_parsing(self):
        body = zlib.compress(b'{"username": "' + b"a" * 1_000_000 + b'"}')
        got = self.client.generic("POST", LOGIN, body,
                                  content_type="application/json; charset=zlib_codec")
        self.assertEqual(got.status_code, 415)

    def test_an_ordinary_login_still_works(self):
        got = self.client.post(LOGIN, {"username": "rm", "password": "pw-123456"},
                               format="json",
                               HTTP_ACCEPT="application/json, text/plain, */*")
        self.assertNotIn(got.status_code, (400, 415), got.content[:200])

    def test_utf8_json_passes(self):
        got = self.client.generic("POST", LOGIN, b'{"username":"rm","password":"x"}',
                                  content_type="application/json; charset=UTF-8")
        self.assertNotIn(got.status_code, (400, 415))
