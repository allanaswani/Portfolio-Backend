"""Find out why the assistant is returning 502, in one command.

    docker exec hf-backend python manage.py agent_selftest

``AgentChatView`` turns any exception from the Anthropic call into a 502 with
the reason in the response body — which is exactly where nobody looks. This
runs the same call the view runs and prints what actually happened.

It exists as a command rather than a pasted one-liner because a multi-line
``manage.py shell -c`` is indented by the terminal's continuation prompt and
dies on ``IndentationError`` before it reaches the problem.

Checks, in the order that isolates the cause:

1. configuration — key present, model, SDK version
2. the tool definitions — shape, names, duplicates
3. a live call with ONLY the bank's own tools
4. a live call with the external lookups added

Step 3 passing and step 4 failing means the external tool definitions are the
problem. Both failing means it is the key, the model or the SDK, and predates
them. Steps 3 and 4 each spend a few tokens; nothing is written anywhere.
"""

import json
import traceback

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Diagnose the AI assistant's connection to the Anthropic API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-call", action="store_true",
            help="Check configuration and tool shapes only; make no API call.")

    def handle(self, *args, **options):
        ok = self.configuration()
        tools_internal, tools_all = self.tools()

        if options["no_call"]:
            return
        if not ok:
            self.stdout.write(self.style.ERROR(
                "\nNo API key, so there is nothing to call. Set ANTHROPIC_API_KEY "
                "in /etc/hf/prod.env and recreate the container."))
            return

        self.stdout.write("")
        internal_ok = self.call("the bank's own tools only", tools_internal)
        external_ok = self.call("with the external lookups", tools_all) \
            if len(tools_all) != len(tools_internal) else None

        self.verdict(internal_ok, external_ok)

    # ── 1. Configuration ─────────────────────────────────────────────────────

    def configuration(self):
        from apps.agent import views

        key = str(getattr(settings, "ANTHROPIC_API_KEY", "") or "")
        self.stdout.write(self.style.MIGRATE_HEADING("Configuration"))
        if key:
            # Never print a key. Its length and prefix are enough to tell a real
            # one from an empty string or a pasted placeholder.
            self.stdout.write(
                f"  ANTHROPIC_API_KEY  set ({len(key)} chars, starts {key[:7]}…)")
        else:
            self.stdout.write(self.style.ERROR("  ANTHROPIC_API_KEY  NOT SET"))

        self.stdout.write(f"  model              {views.MODEL}")
        try:
            import anthropic
            self.stdout.write(f"  anthropic SDK      {anthropic.__version__}")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(f"  anthropic SDK      {exc}"))

        from apps.agent import web_lookup
        self.stdout.write(
            f"  external lookup    {'on' if web_lookup.enabled() else 'off'}")
        return bool(key)

    # ── 2. Tool shapes ───────────────────────────────────────────────────────

    def tools(self):
        from apps.agent.agent_tools import TOOL_DEFINITIONS, tool_definitions

        every = tool_definitions()
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Tools"))
        self.stdout.write(
            f"  {len(TOOL_DEFINITIONS)} internal, {len(every)} offered in total")

        names = [t.get("name") for t in every]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            self.stdout.write(self.style.ERROR(
                f"  DUPLICATE NAMES: {', '.join(sorted(duplicates))} — the API "
                f"rejects the whole request for this."))

        for tool in every:
            problem = self.malformed(tool)
            if problem:
                self.stdout.write(self.style.ERROR(
                    f"  {tool.get('name', '?')}: {problem}"))
        return TOOL_DEFINITIONS, every

    @staticmethod
    def malformed(tool):
        """What the API would reject about this definition, if anything."""
        import re

        name = tool.get("name")
        if not name or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", str(name)):
            return f"name {name!r} is not 1-64 chars of [a-zA-Z0-9_-]"
        if not tool.get("description"):
            return "no description"
        schema = tool.get("input_schema")
        if not isinstance(schema, dict):
            return "input_schema is missing or not an object"
        if schema.get("type") != "object":
            return f"input_schema.type is {schema.get('type')!r}, must be 'object'"
        if not isinstance(schema.get("properties"), dict):
            return "input_schema.properties is missing or not an object"
        for field in schema.get("required", []):
            if field not in schema["properties"]:
                return f"required names {field!r}, which is not in properties"
        try:
            json.dumps(tool)
        except Exception as exc:  # noqa: BLE001
            return f"is not JSON-serialisable: {exc}"
        return None

    # ── 3 & 4. Live calls ────────────────────────────────────────────────────

    def call(self, label, tools):
        import anthropic

        from apps.agent import views

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Calling the API — {label} ({len(tools)} tools)"))
        try:
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=views.MODEL,
                max_tokens=64,
                thinking={"type": "adaptive"},
                tools=tools,
                messages=[{"role": "user", "content": "Reply with the word ok."}],
            )
            self.stdout.write(self.style.SUCCESS(
                f"  OK — stop_reason={response.stop_reason}"))
            return True
        except Exception as exc:  # noqa: BLE001 — the whole point is to show it
            self.stdout.write(self.style.ERROR(f"  FAILED — {type(exc).__name__}"))
            for line in str(exc).splitlines()[:6]:
                self.stdout.write(self.style.ERROR(f"    {line}"))
            self.stdout.write("")
            self.stdout.write(traceback.format_exc()[-1500:])
            return False

    # ── What it means ────────────────────────────────────────────────────────

    def verdict(self, internal_ok, external_ok):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Verdict"))
        if internal_ok and external_ok is not False:
            self.stdout.write(self.style.SUCCESS(
                "  The API call works. If the chat endpoint still 502s, the fault "
                "is later in the loop — a tool raising, or the reply being "
                "persisted. Check the backend log for the traceback."))
        elif internal_ok and external_ok is False:
            self.stdout.write(self.style.ERROR(
                "  The external lookup tool definitions are the problem. Unset "
                "TINYFISH_API_KEY in /etc/hf/prod.env and recreate the container "
                "to restore the assistant, and send me the error above."))
        else:
            self.stdout.write(self.style.ERROR(
                "  The call fails with the bank's own tools alone, so this is not "
                "the external lookups. It is the key, the model or the SDK "
                "version — the error above says which."))
