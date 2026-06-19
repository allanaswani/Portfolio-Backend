"""AI Agent API — Claude-powered, data-grounded chat across all HF Group modules.

``AgentChatView`` runs a manual tool-use loop against the Anthropic Messages API
(``claude-opus-4-8``, adaptive thinking). The model can call the tools in
``agent_tools`` to read live figures from every module — mortgages, leads,
collections & recovery, HFDI projects, the rights issue, EXCO initiatives, staff
performance, insurance, trade finance, bank-wide deposits/loans, and AI insights
& analytics — so its answers are grounded in real data rather than guesses.
"""

from django.conf import settings
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .models import AgentConversation
from .serializers import AgentConversationSerializer
from .agent_tools import TOOL_DEFINITIONS, run_tool

MODEL = "claude-opus-4-8"
MAX_TOOL_ROUNDS = 8  # safety cap on the agentic loop (broader tool surface now)

SYSTEM_PROMPT = (
    "You are the HF Group enterprise assistant — a single data-grounded co-pilot for the "
    "whole HF Group platform, used by relationship managers, mortgage officers, collections "
    "and recovery, finance, HFDI project managers, branch and zonal managers, EXCO and the "
    "Group CEO's office.\n\n"
    "You have tools that read the live system across ALL modules:\n"
    "• Mortgages — portfolio KPIs, lead funnel, field-agent leaderboard, loans, borrowers, "
    "leads, applications.\n"
    "• Collections & recovery — case status, promised-to-pay, officer activity.\n"
    "• HFDI — project sales (MTD/YTD volume, value, income).\n"
    "• Rights issue — applications, payments, allotments, refunds.\n"
    "• EXCO initiatives — status, priority, budget, progress.\n"
    "• Staff performance — monthly scorecards and top performers.\n"
    "• Client briefs — HFCB memos by status.\n"
    "• Insurance & trade finance books.\n"
    "• Bank-wide (GCEO) deposit and loan movement by segment.\n"
    "• AI business insights and analytics snapshots.\n\n"
    "When a question concerns figures, performance, or specific records, CALL A TOOL FIRST and "
    "base your answer strictly on what it returns — never invent numbers. Choose the tool whose "
    "description best matches the question; you may call several. If a tool returns an error or "
    "no data, say so plainly rather than guessing. Note that mortgage-specific tools cover only "
    "the new Mortgages module, while the bank-wide tools cover the wider HF book.\n\n"
    "All monetary values are Kenyan Shillings (KES). Be concise and professional: lead with the "
    "answer, then the supporting figures. Use short tables or bullet lists for multiple rows. If "
    "a question is ambiguous, make a reasonable assumption and state it rather than asking a "
    "clarifying question."
)


def _role_context(user):
    """A short line giving the model the current user's identity and role groups,
    so it can tailor focus without changing what data is accessible."""
    name = user.get_full_name() or user.username
    groups = list(user.groups.values_list("name", flat=True))
    role = ", ".join(groups) if groups else "no specific module group"
    scope = "full access (superuser)" if user.is_superuser else role
    return (f"\n\nCurrent user: {name}. Role groups: {scope}. Tailor your emphasis to this "
            f"user's likely focus, but you may answer cross-module questions they ask.")


@extend_schema(tags=["AI Agent — Conversations"])
class ConversationListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AgentConversationSerializer

    def get_queryset(self):
        return AgentConversation.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


@extend_schema(tags=["AI Agent — Conversations"])
class ConversationDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AgentConversationSerializer

    def get_queryset(self):
        return AgentConversation.objects.filter(user=self.request.user)


@extend_schema(tags=["AI Agent — Chat"])
class AgentChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        user_message = (request.data.get("message") or "").strip()
        if not user_message:
            return Response({"detail": "Message is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            conversation = AgentConversation.objects.get(pk=conversation_id, user=request.user)
        except AgentConversation.DoesNotExist:
            return Response({"detail": "Conversation not found."},
                            status=status.HTTP_404_NOT_FOUND)

        # Stored history is text-only {role, content} — clean and re-sendable.
        history = conversation.messages or []

        api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
        if not api_key:
            reply = ("The AI assistant isn't configured yet. Set ANTHROPIC_API_KEY in the "
                     "backend environment to enable it.")
            return self._persist_and_respond(conversation, history, user_message, reply,
                                              configured=False)

        try:
            reply = self._run_claude(api_key, history, user_message,
                                     role_context=_role_context(request.user))
        except Exception as exc:  # network/auth/etc — keep the UI usable
            return Response(
                {"detail": f"The assistant is temporarily unavailable: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return self._persist_and_respond(conversation, history, user_message, reply)

    # ── Claude agentic loop ──────────────────────────────────────────────────
    def _run_claude(self, api_key, history, user_message, role_context=""):
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        # working[] carries the full turn including tool_use/tool_result blocks;
        # only the final text is persisted to the conversation.
        working = [{"role": m["role"], "content": m["content"]} for m in history]
        working.append({"role": "user", "content": user_message})

        # Static instructions are cached; the per-user role line is appended after
        # so it doesn't bust the prompt cache for the shared system text.
        system = [{"type": "text", "text": SYSTEM_PROMPT,
                   "cache_control": {"type": "ephemeral"}}]
        if role_context:
            system.append({"type": "text", "text": role_context})

        response = None
        for _ in range(MAX_TOOL_ROUNDS):
            response = client.messages.create(
                model=MODEL,
                max_tokens=16000,
                # Adaptive thinking; effort defaults to "high" (the quality setting).
                thinking={"type": "adaptive"},
                system=system,
                tools=TOOL_DEFINITIONS,
                messages=working,
            )
            if response.stop_reason != "tool_use":
                break

            working.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": run_tool(block.name, block.input),
                    })
            working.append({"role": "user", "content": tool_results})

        return self._text_of(response)

    @staticmethod
    def _text_of(response):
        if response is None:
            return "I couldn't produce a response. Please try again."
        parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        return "\n".join(p for p in parts if p).strip() or \
            "I wasn't able to find an answer for that."

    @staticmethod
    def _persist_and_respond(conversation, history, user_message, reply, configured=True):
        history = history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reply},
        ]
        conversation.messages = history
        if conversation.title in ("", "New Conversation") and user_message:
            conversation.title = user_message[:60]
            conversation.save(update_fields=["messages", "title", "updated_at"])
        else:
            conversation.save(update_fields=["messages", "updated_at"])

        return Response({
            "message": reply,
            "conversation_id": conversation.id,
            "configured": configured,
        })
