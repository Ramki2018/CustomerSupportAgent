"""Simple smoke test for the deployed FastAPI app.

Sends requests to /health, /chat, /feedback, /validate and prints results.
"""
import json
import sys
import time
from urllib import request, error

def do_get(url):
    try:
        with request.urlopen(url, timeout=10) as resp:
            return resp.getcode(), resp.read().decode('utf-8')
    except error.HTTPError as e:
        return e.code, e.read().decode('utf-8')
    except Exception as e:
        return None, str(e)


def do_post_json(url, payload):
    data = json.dumps(payload).encode('utf-8')
    req = request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with request.urlopen(req, timeout=20) as resp:
            return resp.getcode(), resp.read().decode('utf-8')
    except error.HTTPError as e:
        return e.code, e.read().decode('utf-8')
    except Exception as e:
        return None, str(e)


BASE = 'http://127.0.0.1:8000'

print('\n1) GET /health')
code, out = do_get(f'{BASE}/health')
print('status:', code)
print(out)

print('\n2) POST /chat')
code, out = do_post_json(f'{BASE}/chat', {'session_id': 'smoke-test', 'message': 'hello'})
print('status:', code)
print(out)

print('\n3) POST /feedback')
code, out = do_post_json(f'{BASE}/feedback', {'session_id': 'smoke-test', 'rating': 5, 'comment': 'looks good'})
print('status:', code)
print(out)

print('\n4) POST /validate (short timeout)')
# validate endpoint accepts timeout_seconds query param; use POST with ?timeout_seconds=10
code, out = do_post_json(f'{BASE}/validate?timeout_seconds=10', {})
print('status:', code)
print(out)

print('\nSmoke test complete')
