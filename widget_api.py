"""Dedicated persistent read-only access for the dorm/electricity widget (stdlib)."""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
from datetime import datetime, timezone

_LOCK = threading.RLock()
_SELECTION = ('elc_campus', 'elc_building', 'elc_floor', 'elc_room', 'elc_type')
_RESULT = ('remaining_kwh', 'balance_cny', 'checked_at', 'campus', 'building', 'floor',
           'room', 'electricity_type', 'page_location')


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class WidgetTokenFile:
    def __init__(self, path):
        self.path = Path(path)

    def status(self, account_key):
        with _LOCK:
            data = read_json(self.path)
        valid = data.get('accountKey') == account_key and bool(data.get('tokenHash'))
        return {'configured': valid, 'createdAt': data.get('createdAt') if valid else None,
                'scope': 'dorm-electricity:read', 'expiresAt': None}

    def rotate(self, account_key):
        token, created = 'dw_' + secrets.token_urlsafe(32), stamp()
        with _LOCK:
            write_json(self.path, {'schemaVersion': 1, 'accountKey': account_key,
                                  'tokenHash': hashlib.sha256(token.encode()).hexdigest(), 'createdAt': created})
        return {'token': token, 'createdAt': created, 'scope': 'dorm-electricity:read', 'expiresAt': None}

    def revoke(self):
        with _LOCK:
            write_json(self.path, {'schemaVersion': 1})
        return {'configured': False}

    def authenticate(self, authorization, account_key):
        if not isinstance(authorization, str) or len(authorization) > 128:
            return False
        match = re.fullmatch(r'Bearer[ \t]+(dw_[A-Za-z0-9_-]{43})', authorization, re.I)
        if not match:
            return False
        with _LOCK:
            data = read_json(self.path)
        expected = data.get('tokenHash')
        return (data.get('accountKey') == account_key and isinstance(expected, str)
                and hmac.compare_digest(expected, hashlib.sha256(match[1].encode()).hexdigest()))


def selection_key(monitor):
    selection = [monitor.account_key(), *[monitor.config.get(k, '') for k in _SELECTION]]
    return hashlib.sha256(json.dumps(selection, ensure_ascii=False).encode()).hexdigest()


def save_electricity(monitor, result):
    if not isinstance(result, dict):
        return
    write_json(monitor.data_dir / 'webui_widget_electricity.json', {
        'selectionKey': selection_key(monitor), 'result': {k: result.get(k) for k in _RESULT}})
    monitor.elc_widget_restored = False


def restore_electricity(monitor):
    data = read_json(monitor.data_dir / 'webui_widget_electricity.json')
    monitor.elc_widget_restored = False
    if monitor.config.get('sdut_user') and data.get('selectionKey') == selection_key(monitor) and isinstance(data.get('result'), dict):
        monitor.elc_result = data['result']
        monitor.elc_widget_restored = True


def clear_electricity(monitor):
    write_json(monitor.data_dir / 'webui_widget_electricity.json', {})
    monitor.elc_widget_restored = False


def number(value):
    if value is None or isinstance(value, bool) or str(value).strip() == '':
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (ValueError, TypeError):
        return None


def snapshot(monitor):
    # Reuse the monitor's lock; no collection, login, notification, or paid action.
    with monitor.lock:
        rows = [r for r in monitor.rows if isinstance(r, dict)]
        latest = max(rows, key=lambda r: (str(r.get('JCRQ') or ''), str(r.get('WID') or '')), default=None)
        inspection = None if latest is None else {
            'date': latest.get('JCRQ'), 'score': number(latest.get('FS')),
            'level': latest.get('DJMC'), 'building': latest.get('SSLMC'),
            'room': latest.get('FJH'), 'checkType': latest.get('JCLXDM_DISPLAY')}
        result = monitor.elc_result or {}
        restored = bool(getattr(monitor, 'elc_widget_restored', False))
        # The existing manual-query flow clears its UI result while querying.
        # Keep the widget's last successful result during that gap or an error.
        if not result:
            cached = read_json(monitor.data_dir / 'webui_widget_electricity.json')
            if cached.get('selectionKey') == selection_key(monitor) and isinstance(cached.get('result'), dict):
                result = cached['result']
                restored = True
        remaining = number(result.get('remaining_kwh'))
        if remaining is not None and remaining < 0:
            remaining = None
        electricity = {'remainingKwh': remaining, 'unit': 'kWh', 'checkedAt': result.get('checked_at'),
                       'campus': result.get('campus'), 'building': result.get('building'),
                       'floor': result.get('floor'), 'room': result.get('room'),
                       'type': result.get('electricity_type'),
                       'stale': bool(monitor.elc_error or restored),
                       'state': 'error' if monitor.elc_error else 'ok' if remaining is not None else 'unavailable'}
        return {'schemaVersion': 1, 'generatedAt': stamp(), 'timezone': 'Asia/Shanghai',
                'inspection': inspection, 'electricity': electricity,
                'monitor': {'running': bool(monitor.config.get('enabled')), 'collecting': bool(monitor.busy or monitor.elc_busy),
                            'lastSuccess': monitor.last_success, 'hasError': bool(monitor.last_error)}}
