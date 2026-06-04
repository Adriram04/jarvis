SAFE_ACTIONS = {
    "check_status",
    "read_conversation",
    "search_items",
    "list_calendar_events",
    "prepare_social_post",
    "draft_content",
    "list_social_posts",
    "list_messages",
    "get_autopilot_rules",
    "get_pending_actions",
    "openclaw_status",
    "openclaw_directory_self",
    "openclaw_directory_peers",
    "openclaw_directory_groups",
    "openclaw_list_targets",
    "openclaw_resolve_target",
    "openclaw_read_conversation",
    "openclaw_list_events",
    "openclaw_list_messages",
    "openclaw_list_new_messages",
    "openclaw_import_contacts",
    "openclaw_send_dry_run",
    "openclaw_resolve_alias",
    "openclaw_add_target_alias",
    "openclaw_remove_target_alias",
    # Automation actions (read-only / local state, safe to run unattended).
    "notify",
    "summarize_day",
    "list_calendar_today",
    "list_whatsapp_unread",
    "prepare_whatsapp_reply",
    "create_pending_action",
    "play_music",
    "open_project",
    "activate_simulation",
    "check_integrations",
}

CONFIRMATION_REQUIRED_ACTIONS = {
    "send_message",
    "send_whatsapp_message",
    "send_channel_message",
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
    "openclaw_send_message",
    "openclaw_send_pending",
    "openclaw_mark_target_allowed",
    "openclaw_create_autopilot_rule",
    "openclaw_enable_autopilot_rule",
    "openclaw_delete_autopilot_rule",
    "openclaw_execute_workflow",
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
    "spam",
    "bulk_message",
    "mass_dm",
    "expose_secret",
    "delete_all",
    "publish_without_review",
    "send_without_confirmation",
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
