"""16 Nov 2026: 229 active users had no usable password and never got a reset
mail - the library skipped them without a word."""
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from rest_framework.test import APIClient


class ResetWithoutUsablePasswordTests(TestCase):
    def test_a_user_without_a_password_still_gets_the_mail(self):
        user = get_user_model().objects.create_user("nopass", email="no.pass@hfcb.co.ke")
        user.set_unusable_password()
        user.save()
        reply = APIClient().post("/auth/api/password_reset/",
                                 {"email": "no.pass@hfcb.co.ke"}, format="json")
        self.assertEqual(reply.status_code, 200, reply.content)
        resets = [m for m in mail.outbox if "password reset" in m.subject]
        self.assertEqual(len(resets), 1, [m.subject for m in mail.outbox])
        self.assertEqual(resets[0].to, ["no.pass@hfcb.co.ke"])
