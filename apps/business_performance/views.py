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
        """Rule-based brief when the LLM is unavailable — a genuine, number-rich
        read of the section (headline, delivery spread, momentum, KES gap-to-
        target, and a specific ask), not three generic lines."""
        if not metrics:
            return [f"No {section} metrics available for {period or 'this period'}."]
        scored = []
        for m in metrics:
            actual, target, growth = m.get("actual"), m.get("target"), m.get("growth")
            scored.append({
                "label": m["label"],
                "unit": m.get("unit", "number"),
                "actual": actual,
                "target": target,
                "growth": growth,
                "pct": (actual / target * 100) if (actual is not None and target) else None,
                "gap": (target - actual) if (actual is not None and target is not None) else None,
            })
        per = f" for {period}" if period else ""
        points = []

        # 1 — headline: the biggest number and where it stands vs plan.
        lead = max(scored, key=lambda s: abs(s["actual"] or 0))
        if lead["pct"] is not None:
            stance = "ahead of plan" if lead["pct"] >= 100 else \
                     "on plan" if lead["pct"] >= 95 else "behind plan"
            points.append(
                f"{lead['label']}{per} is {self._fmt(lead['actual'], lead['unit'])}, "
                f"{lead['pct']:.0f}% of target — {stance}.")
        elif lead["growth"] is not None:
            points.append(f"{lead['label']}{per} is {self._fmt(lead['actual'], lead['unit'])}, "
                          f"{lead['growth']:+.1f}% on the period.")
        else:
            points.append(f"{lead['label']}{per} is {self._fmt(lead['actual'], lead['unit'])}.")

        # 2 — delivery spread across everything carrying a target.
        with_t = [s for s in scored if s["pct"] is not None]
        if len(with_t) >= 2:
            best = max(with_t, key=lambda s: s["pct"])
            worst = min(with_t, key=lambda s: s["pct"])
            avg = sum(s["pct"] for s in with_t) / len(with_t)
            points.append(
                f"Delivery averages {avg:.0f}% of target: {best['label']} leads at "
                f"{best['pct']:.0f}%, {worst['label']} trails at {worst['pct']:.0f}%.")
        elif with_t:
            only = with_t[0]
            points.append(f"{only['label']} is at {only['pct']:.0f}% of its target.")

        # 3 — momentum, naming the strongest and weakest movers.
        movers = [s for s in scored if s["growth"] is not None]
        if len(movers) >= 2:
            up = max(movers, key=lambda s: s["growth"])
            dn = min(movers, key=lambda s: s["growth"])
            if up["label"] != dn["label"]:
                points.append(
                    f"Momentum: {up['label']} {up['growth']:+.1f}% versus "
                    f"{dn['label']} {dn['growth']:+.1f}% period-on-period.")
        elif movers:
            mv = movers[0]
            points.append(f"{mv['label']} moved {mv['growth']:+.1f}% on the period.")

        # 4 — the money: total KES still to find against target.
        gaps = [s for s in scored if s["unit"] == "currency" and s["gap"] and s["gap"] > 0]
        if gaps:
            total_gap = sum(s["gap"] for s in gaps)
            biggest = max(gaps, key=lambda s: s["gap"])
            points.append(
                f"Gap to target: {self._fmt(total_gap, 'currency')} to close, most of it "
                f"on {biggest['label']} ({self._fmt(biggest['gap'], 'currency')}).")

        # 5 — the ask / watch-out.
        if with_t:
            worst = min(with_t, key=lambda s: s["pct"])
            if worst["pct"] < 90:
                points.append(
                    f"Ask: prioritise {worst['label']} at {worst['pct']:.0f}% of target — "
                    f"the biggest risk to the {section.lower()} scorecard.")
            else:
                points.append(
                    f"All tracked {section.lower()} metrics sit near or above target — "
                    f"protect the momentum into the next period.")
        else:
            decl = [s for s in scored if s["growth"] is not None and s["growth"] < 0]
            if decl:
                wk = min(decl, key=lambda s: s["growth"])
                points.append(f"Watch {wk['label']} — down {abs(wk['growth']):.1f}%; "
                              f"understand the driver before it compounds.")
            else:
                points.append(f"No targets set for {section.lower()} yet — add them so the "
                              f"board sees delivery, not just levels.")
        return points
