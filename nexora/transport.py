import json
import mimetypes
import secrets
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class RemoteError(Exception):
    def __init__(self, code=0, retry_after=0):
        # Never expose request URL (contains credentials) or user content in logs.
        self.code, self.retry_after = code, retry_after
        super().__init__(f'Remote request failed (code {code})')


def request_json(url, data=None, timeout=20):
    req = Request(url, data=json.dumps(data).encode() if data is not None else None,
                  headers={'Content-Type': 'application/json', 'User-Agent': 'Nexora/1.0'})
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            result = json.load(exc)
        except (ValueError, OSError):
            result = {}
        raise RemoteError(exc.code, result.get('parameters', {}).get('retry_after', 0)) from None
    except (URLError, TimeoutError, ValueError, OSError):
        raise RemoteError() from None


class Telegram:
    def __init__(self, token):
        self.base = 'https://api.telegram.org/bot' + token + '/'
        self.last = {}

    def call(self, method, **data):
        if method.startswith(('send', 'copy', 'forward')) and 'chat_id' in data:
            chat = str(data['chat_id'])
            delay = (3.1 if chat.startswith('-') else 1.05) - (time.monotonic() - self.last.get(chat, 0))
            if delay > 0:
                time.sleep(delay)
            self.last[chat] = time.monotonic()
        result = request_json(self.base + method, data, timeout=40)
        if not result.get('ok'):
            raise RemoteError(result.get('error_code', 0), result.get('parameters', {}).get('retry_after', 0))
        return result['result']

    def photo(self, chat, png, **fields):
        boundary = secrets.token_hex(16)
        parts = []
        for k, v in {'chat_id': chat, **fields}.items():
            val = json.dumps(v) if isinstance(v, (dict, list, bool)) else str(v)
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{val}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="captcha.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + png + b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        try:
            req = Request(self.base + 'sendPhoto', data=b''.join(parts),
                          headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
            with urlopen(req, timeout=20) as r:
                value = json.load(r)
            if not value.get('ok'):
                raise RemoteError(value.get('error_code', 0))
            return value['result']
        except (URLError, OSError, ValueError):
            raise RemoteError() from None
