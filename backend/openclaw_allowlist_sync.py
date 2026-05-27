import json
import os
import re
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


PLUGIN_ID = "jarvis-whatsapp-forwarder"
DEFAULT_FORWARDER_ENDPOINT = "http://127.0.0.1:8000/api/openclaw/inbound"


def _now_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _clean(value):
    return str(value or "").strip()


def resolve_openclaw_config_path(path=None):
    raw_path = (
        path
        or os.getenv("JARVIS_OPENCLAW_CONFIG")
        or os.getenv("OPENCLAW_CONFIG")
        or ""
    )
    if raw_path:
        return Path(os.path.expandvars(os.path.expanduser(raw_path))).resolve()
    return (Path.home() / ".openclaw" / "openclaw.json").resolve()


def normalize_openclaw_phone(value):
    """Return the compact E.164-ish value OpenClaw stores in allowFrom."""

    text = _clean(value)
    if not text or "@" in text:
        return None
    digits = re.sub(r"\D+", "", text)
    if not 6 <= len(digits) <= 15:
        return None
    return digits


def is_group_target(value):
    text = _clean(value).lower()
    return text.endswith("@g.us") or text.endswith("@newsletter")


def _target_value(target):
    return (
        _clean(target.get("canonical_target"))
        or _clean(target.get("raw_target"))
        or _clean(target.get("target"))
    )


def collect_allowed_whatsapp_targets(targets_manager):
    allowed = targets_manager.list_allowed_targets(channel="whatsapp")
    direct_numbers = set()
    group_targets = set()
    skipped = []

    for target in allowed:
        value = _target_value(target)
        kind = _clean(target.get("kind")).lower()
        if not value:
            skipped.append({
                "display_name": target.get("display_name"),
                "reason": "missing_target",
            })
            continue

        if kind == "group" or is_group_target(value):
            if is_group_target(value):
                group_targets.add(value)
            else:
                skipped.append({
                    "display_name": target.get("display_name"),
                    "target": value,
                    "reason": "invalid_group_target",
                })
            continue

        phone = normalize_openclaw_phone(value)
        if phone:
            direct_numbers.add(phone)
        else:
            skipped.append({
                "display_name": target.get("display_name"),
                "target": value,
                "reason": "invalid_phone",
            })

    return {
        "direct_numbers": sorted(direct_numbers),
        "group_targets": sorted(group_targets),
        "skipped": skipped,
        "allowed_count": len(allowed),
    }


def _load_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _build_backup(path):
    if not path.exists():
        return None
    backup_path = path.with_name(f"{path.name}.jarvis-backup-{_now_stamp()}")
    shutil.copy2(path, backup_path)
    return str(backup_path)


def _plugin_config(endpoint=None, timeout_ms=None, block_openclaw_replies=True):
    return {
        "endpoint": endpoint or os.getenv("JARVIS_OPENCLAW_FORWARDER_ENDPOINT") or DEFAULT_FORWARDER_ENDPOINT,
        "timeoutMs": int(timeout_ms or os.getenv("JARVIS_OPENCLAW_FORWARDER_TIMEOUT_MS") or 2000),
        "blockOpenClawReplies": bool(block_openclaw_replies),
    }


def apply_openclaw_whatsapp_allowlist(config, targets, endpoint=None, timeout_ms=None, block_openclaw_replies=True):
    """Return a patched OpenClaw config plus a compact summary."""

    next_config = deepcopy(config or {})
    channels = next_config.setdefault("channels", {})
    whatsapp = channels.setdefault("whatsapp", {})
    whatsapp["enabled"] = True
    whatsapp["dmPolicy"] = "allowlist"
    whatsapp["allowFrom"] = targets["direct_numbers"]
    whatsapp["groupPolicy"] = "allowlist"
    whatsapp["groupAllowFrom"] = targets["group_targets"]
    whatsapp.setdefault("actions", {})["sendMessage"] = True
    whatsapp.pop("pluginHooks", None)

    if targets["group_targets"]:
        groups = whatsapp.setdefault("groups", {})
        for group_target in targets["group_targets"]:
            group_cfg = groups.setdefault(group_target, {})
            group_cfg["requireMention"] = False

    plugins = next_config.setdefault("plugins", {}).setdefault("entries", {})
    entry = plugins.setdefault(PLUGIN_ID, {})
    entry["enabled"] = True
    entry["config"] = _plugin_config(
        endpoint=endpoint,
        timeout_ms=timeout_ms,
        block_openclaw_replies=block_openclaw_replies,
    )
    hooks = entry.setdefault("hooks", {})
    hooks["allowConversationAccess"] = True
    timeouts = hooks.setdefault("timeouts", {})
    timeouts.setdefault("message_received", 2000)
    timeouts.setdefault("before_dispatch", 1000)

    return next_config


def sync_openclaw_whatsapp_allowlist(
    targets_manager,
    config_path=None,
    endpoint=None,
    timeout_ms=None,
    block_openclaw_replies=True,
    dry_run=False,
):
    path = resolve_openclaw_config_path(config_path)
    targets = collect_allowed_whatsapp_targets(targets_manager)
    if not path.exists() and not dry_run:
        return {
            "success": False,
            "skipped": True,
            "reason": "missing_openclaw_config",
            "config_path": str(path),
            **targets,
        }

    current_config = _load_json(path)
    next_config = apply_openclaw_whatsapp_allowlist(
        current_config,
        targets,
        endpoint=endpoint,
        timeout_ms=timeout_ms,
        block_openclaw_replies=block_openclaw_replies,
    )
    changed = current_config != next_config
    backup_path = None

    if changed and not dry_run:
        backup_path = _build_backup(path)
        _write_json(path, next_config)

    return {
        "success": True,
        "changed": changed,
        "dry_run": bool(dry_run),
        "config_path": str(path),
        "backup_path": backup_path,
        "plugin_id": PLUGIN_ID,
        "forwarder_endpoint": (next_config.get("plugins", {}).get("entries", {}).get(PLUGIN_ID, {}).get("config", {}) or {}).get("endpoint"),
        **targets,
    }
