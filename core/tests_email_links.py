"""What URLs we put in front of users, pinned.

Both doors are in real use (roughly 65/35 by request count) and both stay. The
point of these tests is that the set of URLs is decided by settings in one
place, so a host move is an env change - not a code change, and not a
hardcoded IP in a signal handler like it used to be.
"""
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from core.email_links import (
    access_links_block,
    frontend_urls,
    primary_url,
    reset_links_block,
)

PUB = "https://ceo.hfcb.co.ke"
LAN = "http://128.2.1.25:5400"


@override_settings(FRONTEND_PUBLIC_URL=PUB, FRONTEND_LAN_URL="")
class SingleUrlTests(TestCase):
    """Only reachable by deliberately blanking the LAN URL; not the prod shape.

    Prod sets both - see TwoUrlTests. This covers the degenerate case so the
    emails never print a label with nothing after it.
    """

    def test_only_the_hostname_is_offered(self):
        self.assertEqual(frontend_urls(), [PUB])
        self.assertEqual(primary_url(), PUB)

    def test_access_block_names_one_link_and_drops_the_labels(self):
        block = access_links_block()
        self.assertEqual(block, f"Access the tool here: {PUB}")
        # The labels are a choice the reader no longer has to make.
        self.assertNotIn("Off-network", block)
        self.assertNotIn("On-network", block)

    def test_no_raw_ip_anywhere_in_the_reset_link(self):
        block = reset_links_block("tok123")
        self.assertEqual(block, f"{PUB}/reset_password/confirm/tok123")
        self.assertNotIn("128.2.1.25", block)


@override_settings(FRONTEND_PUBLIC_URL=PUB, FRONTEND_LAN_URL=LAN)
class TwoUrlTests(TestCase):
    """The production shape: two doors, both advertised, both labelled."""

    def test_both_are_listed_and_labelled(self):
        block = access_links_block()
        self.assertIn(f"Off-network (internet): {PUB}", block)
        self.assertIn(f"On-network (office LAN): {LAN}", block)

    def test_both_reset_links_carry_the_token(self):
        block = reset_links_block("tok123")
        self.assertIn(f"{PUB}/reset_password/confirm/tok123", block)
        self.assertIn(f"{LAN}/reset_password/confirm/tok123", block)

    def test_primary_is_the_public_one(self):
        self.assertEqual(primary_url(), PUB)


class HygieneTests(TestCase):
    @override_settings(FRONTEND_PUBLIC_URL=f"  {PUB}/  ", FRONTEND_LAN_URL="")
    def test_whitespace_and_trailing_slash_are_stripped(self):
        # An env file written as "  FRONTEND_LAN_URL=http://..." yields a leading
        # space, and " http://host" is a dead link in every mail client.
        self.assertEqual(primary_url(), PUB)

    @override_settings(FRONTEND_PUBLIC_URL=PUB, FRONTEND_LAN_URL=f"{PUB}/")
    def test_the_same_url_twice_is_offered_once(self):
        self.assertEqual(frontend_urls(), [PUB])
        self.assertEqual(access_links_block(), f"Access the tool here: {PUB}")

    @override_settings(FRONTEND_PUBLIC_URL="", FRONTEND_LAN_URL="")
    def test_nothing_configured_yields_no_block_rather_than_a_dangling_label(self):
        self.assertEqual(access_links_block(), "")
        self.assertEqual(reset_links_block("tok"), "")
        self.assertEqual(primary_url(), "")


@override_settings(
    FRONTEND_PUBLIC_URL=PUB,
    FRONTEND_LAN_URL="",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class AccountCreationEmailTests(TestCase):
    """The first email a user ever gets - and the one that was hardcoded."""

    def test_new_account_email_uses_the_hostname_not_the_ip(self):
        User.objects.create(username="jdoe", email="jdoe@example.com", first_name="J")
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        bodies = [sent.body] + [b for b, _ in sent.alternatives]
        for body in bodies:
            self.assertIn(f"{PUB}/login", body)
            self.assertNotIn("128.2.1.25", body)

    def test_still_never_emails_a_password(self):
        User.objects.create(username="jdoe2", email="jdoe2@example.com", first_name="J")
        self.assertIn("no password is sent by email", mail.outbox[0].body)

    @override_settings(FRONTEND_PUBLIC_URL="", FRONTEND_LAN_URL="")
    def test_with_no_url_configured_the_email_still_sends_without_a_broken_link(self):
        User.objects.create(username="jdoe3", email="jdoe3@example.com", first_name="J")
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        # The account details must survive; only the link sentence drops out.
        self.assertIn("Username: jdoe3", body)
        self.assertNotIn("To access the site click", body)

    def test_no_email_without_an_address(self):
        User.objects.create(username="noaddr")
        self.assertEqual(len(mail.outbox), 0)


@override_settings(
    FRONTEND_PUBLIC_URL=PUB,
    FRONTEND_LAN_URL="http://10.51.181.25:5400",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class RepointingTheLanDoorTests(TestCase):
    """Moving LAN users to another app tier must be an env change, nothing more.

    This is the property that makes a staged migration possible: set
    FRONTEND_LAN_URL to the new host and every email follows, with no edit to
    the signal handler that used to carry the IP in a string literal.
    """

    def test_emails_follow_the_setting_to_the_new_host(self):
        self.assertEqual(frontend_urls(), [PUB, "http://10.51.181.25:5400"])
        self.assertIn("10.51.181.25:5400", access_links_block())
        self.assertIn("10.51.181.25:5400", reset_links_block("tok"))

    def test_the_public_url_is_untouched_by_repointing_the_lan_one(self):
        self.assertEqual(primary_url(), PUB)
        self.assertIn(f"Off-network (internet): {PUB}", access_links_block())

    def test_the_account_email_is_branded_hfcb_not_hf(self):
        User.objects.create(username="brand1", email="b@example.com", first_name="B")
        body = mail.outbox[0].body
        self.assertIn("HFCB Portfolio Tool", body)
        self.assertNotIn("HF Portfolio Tool", body)
