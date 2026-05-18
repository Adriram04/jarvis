SAFE_ACTIONS = {
    "check_status",
    "read_conversation",
    "search_items",
    "search_email",
    "read_email",
    "list_calendar_events",
    "prepare_social_post",
    "draft_content",
    "draft_email",
    "list_social_posts",
    "list_messages",
    "get_autopilot_rules",
    "get_pending_actions",
}

CONFIRMATION_REQUIRED_ACTIONS = {
    "send_message",
    "send_whatsapp_message",
    "send_channel_message",
    "send_email",
    "reply_email",
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
    "schedule_social_post",
    "publish_social_post",
    "run_workflow",
    "create_autopilot_rule",
    "enable_autopilot_rule",
    "disable_autopilot_rule",
    "update_autopilot_rule",
    "delete_autopilot_rule",
}

FORBIDDEN_ACTIONS = {
    "mass_message",
    "spam_message",
    "send_secret",
    "expose_tokens",
    "upload_credentials",
    "execute_shell",
    "delete_all_emails",
    "delete_all_events",
    "post_without_review",
    "auto_reply_everywhere",
    "impersonate_sensitive_identity",
    "bypass_confirmation",
}


class PermissionsManager:
    """Classifies OpenClaw actions before Jarvis executes or queues them."""

    def classify(self, action_type):
        action = self._normalize(action_type)
        if action in FORBIDDEN_ACTIONS:
            return "forbidden"
        if action in SAFE_ACTIONS:
            return "safe"
        if action in CONFIRMATION_REQUIRED_ACTIONS:
            return "confirmation_required"
        return "confirmation_required"

    def requires_confirmation(self, action_type):
        return self.classify(action_type) == "confirmation_required"

    def is_forbidden(self, action_type):
        return self.classify(action_type) == "forbidden"

    def explain(self, action_type):
        action = self._normalize(action_type)
        classification = self.classify(action)
        if classification == "safe":
            return f"Action '{action}' is safe and can run without extra confirmation."
        if classification == "forbidden":
            return f"Action '{action}' is blocked by Jarvis safety policy."
        return f"Action '{action}' changes external state and requires confirmation."

    def _normalize(self, action_type):
        return str(action_type or "").strip().lower().replace(" ", "_")


permissions_manager = PermissionsManager()


def classify(action_type):
    return permissions_manager.classify(action_type)


def requires_confirmation(action_type):
    return permissions_manager.requires_confirmation(action_type)


def is_forbidden(action_type):
    return permissions_manager.is_forbidden(action_type)


def explain(action_type):
    return permissions_manager.explain(action_type)

