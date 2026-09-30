"""Surfaces API — ask for a view, get a live one.

Two endpoints do the real work:

``POST surfaces/generate/``
    The person describes what they want. Claude is given the same read-only
    warehouse tools as ``apps.agent`` plus one terminal tool, ``render_surface``,
    whose input schema *is* the layout. Forcing the answer through a tool schema
    means the layout is validated by the API before it reaches us — no parsing
    JSON out of prose, no half-formed spec reaching the database.

``GET surfaces/<id>/data/``
    Re-runs each panel's recorded tool call and returns fresh figures. No model
    call, so it is fast and free, and the frontend can poll it.

That split is the whole design. Generation is the expensive, creative step and
happens once; refresh is mechanical and happens forever.
"""

import json
import logging

from django.conf import settings
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.agent.agent_tools import run_tool, tool_definitions
from .models import Surface
from .serializers import (SurfaceSerializer, GenerateRequestSerializer,
                          RefineRequestSerializer)

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_TOOL_ROUNDS = 8

# One panel kind per way of reading a number, not one per chart library widget.
# Keeping this list short is what makes a generated layout predictable.
PANEL_KINDS = ["kpi", "bar", "line", "area", "donut", "table", "note"]

SURFACE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short name for this surface, 2-5 words."},
        "subtitle": {"type": "string", "description": "One line saying what it shows."},
        "panels": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Short slug, unique on this surface."},
                    "kind": {"type": "string", "enum": PANEL_KINDS},
                    "title": {"type": "string"},
                    "span": {
                        "type": "integer", "minimum": 1, "maximum": 3,
                        "description": "Columns out of 3. A headline number is 1; a table is 3.",
                    },
                    "tool": {
                        "type": "string",
                        "description": "The data tool to re-run on refresh. Omit only for kind=note.",
                    },
                    "tool_input": {"type": "object", "description": "Arguments for that tool."},
                    "data_path": {
                        "type": "string",
                        "description": "Dot path to the rows or value inside the tool result, e.g. 'results' or 'summary.total'. Empty means the whole result.",
                    },
                    "x_field": {"type": "string", "description": "Row key for the category or date axis."},
                    "y_field": {"type": "string", "description": "Row key for the numeric value."},
                    "columns": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Row keys to show, for kind=table.",
                    },
                    "unit": {"type": "string", "enum": ["kes", "number", "percent"]},
                    "body": {"type": "string", "description": "Text, for kind=note only."},

                    # ── How it is drawn ──────────────────────────────────
                    # Display instructions, not data. They exist because
                    # people ask for the chart they want - "rank it", "top
                    # ten", "show us against them" - and with nowhere to put
                    # that, the request was simply ignored.
                    "sort": {
                        "type": "string", "enum": ["none", "asc", "desc"],
                        "description": "Order rows by the y value. 'desc' for a league table.",
                    },
                    "limit": {
                        "type": "integer", "minimum": 1, "maximum": 50,
                        "description": "Keep only the first N rows after sorting - 'the top ten'.",
                    },
                    "compare_field": {
                        "type": "string",
                        "description": (
                            "A second numeric row key drawn behind the bars, for "
                            "actual-against-target. Only for kind=bar."
                        ),
                    },
                    "target": {
                        "type": "number",
                        "description": "Draw a reference line at this value. For line and area.",
                    },
                    "highlight_field": {
                        "type": "string",
                        "description": (
                            "Row key marking the row to emphasise, e.g. 'is_us' on "
                            "get_market_position so HF Group stands out from competitors."
                        ),
                    },
                    "highlight_value": {
                        "description": "The value of highlight_field that means 'emphasise this row'.",
                    },
                },
                "required": ["id", "kind", "title", "span"],
            },
        },
    },
    "required": ["title", "subtitle", "panels"],
}

RENDER_TOOL = {
    "name": "render_surface",
    "description": (
        "Return the finished surface layout. Call this exactly once, last, after "
        "you have used the data tools to confirm the figures exist and to learn "
        "the real field names. Every panel except a note must name the tool and "
        "arguments that produced it, because refreshing re-runs them."
    ),
    "input_schema": SURFACE_SCHEMA,
}

SYSTEM = (
    "You design dashboards for HF Group, a Kenyan bank. Somebody describes the view "
    "they need; you build it from the bank's live data tools.\n\n"
    "Work in this order. First call the data tools you think are relevant and LOOK at "
    "what comes back — you need the real field names, and you need to know a figure "
    "exists before you build a panel on it. Then call render_surface once with the "
    "layout.\n\n"
    "Rules that matter:\n"
    "- Never invent a tool name, a field name or a figure. If the data for something "
    "the person asked for does not exist, leave it out and add a note panel saying "
    "plainly what is missing and which tool you checked.\n"
    "- Lead with the headline: the two or three numbers that answer the question go "
    "first, as kpi panels, before any table.\n"
    "- data_path must point at what you actually saw in the tool result.\n"
    "- Money is Kenyan Shillings; use unit 'kes' for money, 'number' for counts.\n"
    "- Between three and six panels. A wall of panels is not a dashboard."
) + """

On how a panel is drawn:
- If the person says how they want it - ranked, top ten, as a line, against
  target, us against the competition - do exactly that, using sort, limit,
  compare_field, target and highlight_field. An explicit instruction about the
  chart is not a preference to weigh; it is the request.
- kind 'donut' is for composition - how a whole splits - and only when the
  parts sum to something meaningful. Six slices at most.
- kind 'area' is a line with the volume beneath it filled: use it for a
  balance or a book over time, and plain 'line' for a rate or a ratio.
- Ranked lists read best sorted 'desc' with a limit. An unordered bar chart of
  forty branches tells nobody anything.
- On get_market_position set highlight_field 'is_us' and highlight_value true,
  so our own bank is visibly marked against its competitors.
"""


def _dig(obj, path):
    """Walk a dot path into a tool result, tolerating a missing branch."""
    if not path:
        return obj
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit():
            obj = obj[int(part)] if int(part) < len(obj) else None
        else:
            return None
        if obj is None:
            return None
    return obj


def resolve_panel(panel, user):
    """Run one panel's recorded tool call and return just what it renders."""
    tool = panel.get("tool")
    if panel.get("kind") == "note" or not tool:
        return {"ok": True, "body": panel.get("body", "")}
    try:
        raw = json.loads(run_tool(tool, panel.get("tool_input") or {}, user=user))
    except Exception as exc:  # noqa: BLE001 — a dead panel must not kill the page
        logger.warning("surface panel %s: tool %s failed", panel.get("id"), tool, exc_info=True)
        return {"ok": False, "error": f"{tool} could not be read: {exc}"}
    if isinstance(raw, dict) and raw.get("error"):
        return {"ok": False, "error": raw["error"]}
    value = _dig(raw, panel.get("data_path", ""))
    if value is None:
        return {"ok": False,
                "error": f"{tool} returned nothing at '{panel.get('data_path') or '(root)'}'."}
    return {"ok": True, "data": value}


@extend_schema(tags=["Surfaces"])
class SurfaceListCreateView(generics.ListCreateAPIView):
    serializer_class = SurfaceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from django.db.models import Q
        u = self.request.user
        qs = Surface.objects.filter(Q(visibility=Surface.Visibility.SHARED) | Q(created_by=u))
        return qs.distinct()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


@extend_schema(tags=["Surfaces"])
class SurfaceDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SurfaceSerializer
    permission_classes = [IsAuthenticated]
    queryset = Surface.objects.all()

    def get_object(self):
        obj = super().get_object()
        if not obj.visible_to(self.request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("This surface is private.")
        return obj


@extend_schema(tags=["Surfaces"])
class SurfaceDataView(APIView):
    """Fresh figures for every panel. No model call — this is the live path."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            surface = Surface.objects.get(pk=pk)
        except Surface.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not surface.visible_to(request.user):
            return Response({"detail": "This surface is private."},
                            status=status.HTTP_403_FORBIDDEN)
        panels = (surface.spec or {}).get("panels", [])
        return Response({
            "surface": surface.id,
            "panels": {p.get("id"): resolve_panel(p, request.user) for p in panels},
        })


@extend_schema(tags=["Surfaces"], request=GenerateRequestSerializer)
class SurfaceGenerateView(APIView):
    """Plain-language request in, saved live surface out."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = GenerateRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        prompt = ser.validated_data["prompt"]

        api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
        if not api_key:
            return Response(
                {"detail": "Surfaces need ANTHROPIC_API_KEY set on the server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            spec = self._design(api_key, prompt, request.user)
        except Exception as exc:  # noqa: BLE001
            logger.exception("surface generation failed")
            return Response({"detail": f"Could not build that surface: {exc}"},
                            status=status.HTTP_502_BAD_GATEWAY)
        if spec is None:
            return Response(
                {"detail": "Claude did not return a layout. Try describing the view "
                           "in terms of the figures you want to see."},
                status=status.HTTP_502_BAD_GATEWAY)

        surface = Surface.objects.create(
            title=spec.get("title") or "Untitled surface",
            prompt=prompt,
            spec=spec,
            created_by=request.user,
        )
        data = {p.get("id"): resolve_panel(p, request.user)
                for p in spec.get("panels", [])}
        return Response({"surface": SurfaceSerializer(surface).data, "panels": data},
                        status=status.HTTP_201_CREATED)

    def _design(self, api_key, prompt, user, system=None):
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        tools = list(tool_definitions()) + [RENDER_TOOL]
        messages = [{"role": "user", "content": prompt}]

        for _ in range(MAX_TOOL_ROUNDS):
            resp = client.messages.create(
                model=MODEL,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=[{"type": "text", "text": system or SYSTEM,
                         "cache_control": {"type": "ephemeral"}}],
                tools=tools,
                messages=messages,
            )
            if resp.stop_reason != "tool_use":
                return None

            # render_surface is terminal: the API has already validated its input
            # against SURFACE_SCHEMA, so this is a finished layout.
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use" and block.name == "render_surface":
                    return dict(block.input)

            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": run_tool(block.name, block.input, user=user),
                })
            if not results:
                return None
            messages.append({"role": "user", "content": results})

        return None


REFINE_SYSTEM = SYSTEM + """

You are ADJUSTING a surface that already exists, not building a new one. You
are given its current layout and one instruction.

Change only what the instruction asks for. Every panel the person did not
mention keeps its tool, its tool_input, its data_path and its fields exactly as
they are - somebody is looking at this dashboard, and silently re-deciding a
panel they were happy with is a worse failure than refusing.

If the instruction is only about how something is drawn - rank it, top ten,
make it a line, mark us against the others - change the display fields alone
and leave every tool call untouched, so the figures do not move. Call the data
tools again only if the instruction asks for a figure that is not on the
surface yet. Then call render_surface once with the complete layout, including
the panels you did not change.
"""


@extend_schema(tags=["Surfaces"], request=RefineRequestSerializer)
class SurfaceRefineView(APIView):
    """Adjust a surface in place: "rank that by value and show the top ten"."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        ser = RefineRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        instruction = ser.validated_data["instruction"]

        try:
            surface = Surface.objects.get(pk=pk)
        except Surface.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not surface.visible_to(request.user):
            return Response({"detail": "This surface is private."},
                            status=status.HTTP_403_FORBIDDEN)
        # Seeing a shared surface is not permission to rewrite it for everyone.
        if surface.created_by_id != request.user.id and not request.user.is_superuser:
            return Response(
                {"detail": "Only the person who made this surface can change it. "
                           "Build your own from its description instead."},
                status=status.HTTP_403_FORBIDDEN)

        api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
        if not api_key:
            return Response(
                {"detail": "Surfaces need ANTHROPIC_API_KEY set on the server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE)

        brief = (
            "Here is the surface as it stands:\n\n"
            + json.dumps(surface.spec or {}, indent=2, default=str)
            + "\n\nThe instruction is:\n"
            + instruction
        )
        try:
            spec = self._design(api_key, brief, request.user, system=REFINE_SYSTEM)
        except Exception as exc:  # noqa: BLE001
            logger.exception("surface refine failed")
            return Response({"detail": f"Could not apply that change: {exc}"},
                            status=status.HTTP_502_BAD_GATEWAY)
        if spec is None:
            return Response(
                {"detail": "Claude did not return an updated layout. Try naming the "
                           "panel and what should change about it."},
                status=status.HTTP_502_BAD_GATEWAY)

        surface.spec = spec
        if spec.get("title"):
            surface.title = spec["title"]
        # The prompt is the surface's history: keep what it was asked to be.
        surface.prompt = f'{surface.prompt}\n\n> {instruction}'.strip()
        surface.save(update_fields=["spec", "title", "prompt", "updated_at"])

        data = {p.get("id"): resolve_panel(p, request.user)
                for p in spec.get("panels", [])}
        return Response({"surface": SurfaceSerializer(surface).data, "panels": data})

    # The loop is identical to generation; only the system prompt differs.
    _design = SurfaceGenerateView._design
