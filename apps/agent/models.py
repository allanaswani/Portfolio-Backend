from django.db import models
from django.contrib.auth.models import User


class AgentConversation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="agent_conversations")
    title = models.CharField(max_length=255, blank=True, default="New Conversation")
    messages = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "agent_conversations"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user.username} — {self.title}"
