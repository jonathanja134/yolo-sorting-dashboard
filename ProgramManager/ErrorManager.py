"""
ErrorManager.py – Centralized error definitions and handlers for the sorting system.

Severity rules (dashboard):
  INFO     → log sidebar only (system_log)
  WARNING+ → banner (cumulative single line) + log sidebar (system_error)
"""

from enum import Enum
from datetime import datetime
from ProgramManager.ErrorLibrary import ERROR_CATALOG, ErrorSeverity



def _severity_value(severity) -> str:
    return severity.value if isinstance(severity, ErrorSeverity) else severity


# ══════════════════════════════════════════════════════════════════════════════
# Error Manager Class
# ══════════════════════════════════════════════════════════════════════════════

class ErrorManager:
    """Central error handler and tracker."""

    def __init__(self, emit_fn=None):
        self.emit_fn = emit_fn
        self.active_errors = {}   # error_key -> error_dict
        self.error_history = []
        self._pending = []        # [(event, payload), ...] before emit_fn is set

    def set_emit_fn(self, emit_fn):
        """Attach dashboard emit callback and flush queued events."""
        self.emit_fn = emit_fn
        self.replay_pending()

    def get_error_def(self, error_code: str) -> dict:
        return ERROR_CATALOG.get(error_code, ERROR_CATALOG["UNKNOWN_ERROR"])

    def _build_error_obj(self, error_code: str, details=None) -> dict:
        if error_code not in ERROR_CATALOG:
            error_code = "UNKNOWN_ERROR"

        error_def = ERROR_CATALOG[error_code]
        message = error_def["message"]
        if details and details.get("message"):
            message = details["message"]

        return {
            "error_key": error_code,
            "code": error_def["code"],
            "title": error_def["title"],
            "message": message,
            "action": error_def["action"],
            "severity": _severity_value(error_def["severity"]),
            "source": error_def["source"].value,
            "timestamp": datetime.now().isoformat(),
            "details": details or {},
        }

    def _emit_or_queue(self, event: str, payload: dict):
        if self.emit_fn:
            self.emit_fn(event, payload)
        else:
            self._pending.append((event, payload))

    def replay_pending(self):
        """Emit queued events and refresh active banner errors after connect."""
        if not self.emit_fn:
            return

        pending = list(self._pending)
        self._pending.clear()
        replayed_keys = set()
        for event, payload in pending:
            self.emit_fn(event, payload)
            if event == "system_error":
                replayed_keys.add(payload.get("error_key"))

        for key, err in self.active_errors.items():
            if (
                err["severity"] != ErrorSeverity.INFO.value
                and key not in replayed_keys
            ):
                self.emit_fn("system_error", err)

    def raise_error(self, error_code: str, details: dict = None) -> dict:
        """Raise WARNING+ / ERROR / CRITICAL — banner + log."""
        if error_code not in ERROR_CATALOG:
            error_code = "UNKNOWN_ERROR"

        error_def = ERROR_CATALOG[error_code]
        if error_def["severity"] == ErrorSeverity.INFO:
            return self.log_info(error_code, details)

        error_obj = self._build_error_obj(error_code, details)
        self.active_errors[error_code] = error_obj
        self.error_history.append(error_obj)
        self._emit_or_queue("system_error", error_obj)
        print(f"[ERROR] {error_obj['code']} - {error_obj['title']}: {error_obj['message']}")
        return error_obj

    def log_info(self, error_code: str, details: dict = None) -> dict:
        """Log INFO severity — sidebar only, not banner."""
        if error_code not in ERROR_CATALOG:
            error_code = "UNKNOWN_ERROR"

        error_obj = self._build_error_obj(error_code, details)
        self.error_history.append(error_obj)
        self._emit_or_queue("system_log", error_obj)
        print(f"[INFO] {error_obj['code']} - {error_obj['title']}: {error_obj['message']}")
        return error_obj

    def resolve_error(self, error_code: str):
        if error_code in self.active_errors:
            self.active_errors.pop(error_code)
            self._emit_or_queue("error_resolved", {
                "error_key": error_code,
                "code": ERROR_CATALOG.get(error_code, ERROR_CATALOG["UNKNOWN_ERROR"])["code"],
                "timestamp": datetime.now().isoformat(),
            })
            print(f"[RESOLVED] {error_code}")

    def has_critical_error(self) -> bool:
        for error in self.active_errors.values():
            if error["severity"] == ErrorSeverity.CRITICAL.value:
                return True
        return False

    def get_active_errors(self) -> list:
        return list(self.active_errors.values())

    def get_error_history(self, limit: int = 100) -> list:
        return self.error_history[-limit:]


_global_error_manager = None


def get_error_manager(emit_fn=None) -> ErrorManager:
    global _global_error_manager
    if _global_error_manager is None:
        _global_error_manager = ErrorManager(emit_fn)
    elif emit_fn:
        _global_error_manager.set_emit_fn(emit_fn)
    return _global_error_manager
