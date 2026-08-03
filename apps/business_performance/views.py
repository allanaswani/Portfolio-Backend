"""Strategy & Business Performance API.

Two things the executive cockpit needs that don't exist elsewhere:

1. **Targets** — CRUD + a compact per-year *matrix* the frontend can index in
   O(1) when it renders target-vs-actual RAG tiles. All bank-wide actuals come
   from the existing GCEO/analytics endpoints; this only supplies the targets.
2. **AI executive brief** — turns a section's computed figures into three plain
   talking points the director can read verbatim in a meeting. Reuses the same
   Anthropic setup as ``apps.agent``; if the key is missing or the call fails it
   falls back to a deterministic rule-based brief so the panel never breaks.
"""

from collections import defaultdict

from django.conf import settings
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .models import StrategyTarget
from .serializers import StrategyTargetSerializer, ExecBriefRequestSerializer

WRITE_GROUPS = {"business_performance", "ceo", "exco"}


class CanEditTargets(BasePermission):
    """Anyone signed in may *read* targets; only the strategy team, EXCO, the
    CEO's office, or staff/superusers may create or change them."""

    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return request.user and request.user.is_authenticated
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if u.is_superuser or u.is_staff:
            return True
        return bool(set(u.groups.values_list("name", flat=True)) & WRITE_GROUPS)


@extend_schema(tags=["Business Performance — Targets"])
class TargetListCreateView(generics.ListCreateAPIView):
    serializer_class = StrategyTargetSerializer
    permission_classes = [CanEditTargets]

    def get_queryset(self):
        qs = StrategyTarget.objects.all()
        p = self.request.query_params
        for field in ("metric", "scope_type", "scope_value", "period_type"):
            val = p.get(field)
            if val:
                qs = qs.filter(**{field: val})
        year = p.get("year")
        if year:
            qs = qs.filter(year=year)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


@extend_schema(tags=["Business Performance — Targets"])
class TargetDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = StrategyTarget.objects.all()
    serializer_class = StrategyTargetSerializer
    permission_classes = [CanEditTargets]


@extend_schema(tags=["Business Performance — Targets"])
class TargetsMatrixView(APIView):
    """Compact lookup for the cockpit: for a given year, every bank-wide target
    keyed by metric → period. Shape::

        {"year": 2026,
         "targets": {"deposits": {"annual": 1.2e11,
                                  "quarterly": {"1": .., "2": ..},
                                  "monthly":   {"1": .., ...}},
                     ...}}
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import date
        year = request.query_params.get("year") or date.today().year
        scope_type = request.query_params.get("scope_type", "bank")
        scope_value = request.query_params.get("scope_value", "")

        rows = StrategyTarget.objects.filter(
            year=year, scope_type=scope_type, scope_value=scope_value,
        )
        out = defaultdict(lambda: {"annual": None, "quarterly": {}, "monthly": {}})
        for r in rows:
            val = float(r.target_value)
            bucket = out[r.metric]
            if r.period_type == StrategyTarget.Period.ANNUAL:
                bucket["annual"] = val
            elif r.period_type == StrategyTarget.Period.QUARTERLY and r.quarter:
                bucket["quarterly"][str(r.quarter)] = val
            elif r.period_type == StrategyTarget.Period.MONTHLY and r.month:
                bucket["monthly"][str(r.month)] = val
        return Response({"year": int(year), "scope_type": scope_type,
                         "scope_value": scope_value, "targets": out})


# ── AI executive brief ────────────────────────────────────────────────────────

MODEL = "claude-opus-4-8"

BRIEF_SYSTEM = (
    "You are the analyst briefing the HF Group Director of Strategy & Business "
    "Performance right before a leadership meeting. You are given a section of the "
    "executive scorecard with each metric's actual, target and growth. Write EXACTLY "
    "three short talking points (max ~22 words each) the director can say out loud: "
    "point 1 = the headline (what the numbers say), point 2 = why it matters / what is "
    "driving it, point 3 = the watch-out or the ask. Be specific with the figures. No "
    "preamble, no markdown headers. Return only the three points, each on its own line, "
    "no bullet characters. All money is Kenyan Shillings (KES)."
)


@extend_schema(tags=["Business Performance — AI Brief"], request=ExecBriefRequestSerializer)
class ExecBriefView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = ExecBriefRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        section = data["section"]
        period = data.get("period_label") or ""
        metrics = data["metrics"]

        api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
        if api_key:
            try:
                points = self._run_claude(api_key, section, period, metrics)
                if points:
                    return Response({"section": section, "points": points, "source": "ai"})
            except Exception:
                pass  # fall through to deterministic brief — panel must never break
        return Response({"section": section,
                         "points": self._fallback(section, period, metrics),
                         "source": "rule"})

    # ── helpers ──
    @staticmethod
    def _fmt(v, unit):
        if v is None:
            return "n/a"
        if unit == "currency":
            a = abs(v)
            if a >= 1e9:  return f"KES {v/1e9:.2f}B"
            if a >= 1e6:  return f"KES {v/1e6:.1f}M"
            if a >= 1e3:  return f"KES {v/1e3:.0f}K"
            return f"KES {v:.0f}"
        if unit == "percent":
            return f"{v:.1f}%"
        return f"{v:,.0f}"

    def _lines(self, section, period, metrics):
        head = f"Section: {section}" + (f" ({period})" if period else "")
        rows = []
        for m in metrics:
            unit = m.get("unit", "number")
            parts = [f"{m['label']}: actual {self._fmt(m.get('actual'), unit)}"]
            if m.get("target") is not None:
                pct = (m["actual"] / m["target"] * 100) if m.get("actual") and m["target"] else None
                parts.append(f"target {self._fmt(m['target'], unit)}"
                             + (f" ({pct:.0f}% achieved)" if pct is not None else ""))
            if m.get("growth") is not None:
                parts.append(f"growth {m['growth']:+.1f}%")
            rows.append("; ".join(parts))
        return head, rows

    def _run_claude(self, api_key, section, period, metrics):
        import anthropic
        _, rows = self._lines(section, period, metrics)
        user = "Here is the section data:\n" + "\n".join(f"- {r}" for r in rows)
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=[{"type": "text", "text": BRIEF_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        points = [ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()]
        return points[:3]

    def _fallback(self, section, period, metrics):
        """Rule-based brief when the LLM is unavailable — still meeting-ready."""
        if not metrics:
            return [f"No {section} metrics available for {period or 'this period'}."]
        scored = []
        for m in metrics:
            unit = m.get("unit", "number")
            actual, target, growth = m.get("actual"), m.get("target"), m.get("growth")
            pct = (actual / target * 100) if (actual is not None and target) else None
            scored.append((m["label"], unit, actual, target, growth, pct))

        # 1 — headline: the metric with the largest absolute actual.
        lead = max(scored, key=lambda s: abs(s[2] or 0))
        p1 = f"{lead[0]} stands at {self._fmt(lead[2], lead[1])}" + (
            f", {lead[5]:.0f}% of target." if lead[5] is not None else
            (f", {lead[4]:+.1f}% vs last period." if lead[4] is not None else "."))

        # 2 — why it matters: strongest grower (or best achiever).
        movers = [s for s in scored if s[4] is not None]
        if movers:
            mv = max(movers, key=lambda s: s[4])
            p2 = f"{mv[0]} is the strongest mover at {mv[4]:+.1f}%, driving the {section.lower()} trend."
        else:
            ach = [s for s in scored if s[5] is not None]
            mv = max(ach, key=lambda s: s[5]) if ach else lead
            p2 = (f"{mv[0]} leads on delivery at {mv[5]:.0f}% of target."
                  if mv[5] is not None else f"{mv[0]} anchors the {section.lower()} book.")

        # 3 — watch-out: worst achiever, or the sharpest decline.
        risks = [s for s in scored if s[5] is not None]
        if risks:
            wk = min(risks, key=lambda s: s[5])
            p3 = (f"Watch {wk[0]} — only {wk[5]:.0f}% of target; needs a push to close the gap."
                  if wk[5] < 100 else
                  f"All tracked metrics are at or above target — hold the momentum on {wk[0]}.")
        else:
            decl = [s for s in scored if s[4] is not None and s[4] < 0]
            if decl:
                wk = min(decl, key=lambda s: s[4])
                p3 = f"Watch {wk[0]} — down {abs(wk[4]):.1f}%; understand the driver before it compounds."
            else:
                p3 = f"No targets set for {section.lower()} yet — add them to track delivery, not just growth."
        return [p1, p2, p3]
