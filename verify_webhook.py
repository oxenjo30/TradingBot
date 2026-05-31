import os, sys, hashlib, hmac, json
sys.path.insert(0, '.')
os.environ['LEMON_SQUEEZY_SIGNING_SECRET'] = 'test-secret-for-verify'
os.environ['TRADEBOT_LICENSE_SECRET'] = 'test-seller-secret-32-chars-long!'
os.environ['LICENSE_DURATION_DAYS'] = '36500'
os.environ['LICENSE_DOWNLOAD_URL'] = 'https://lemonsqueezy.com/test'

# Patch DB to temp
import tempfile, server.db as db_mod
tmp = tempfile.mkdtemp()
db_mod.DB_PATH = tmp + '/test.db'
db_mod.init_db()

from fastapi.testclient import TestClient
from server.main import app
client = TestClient(app)

SIGNING_SECRET = 'test-secret-for-verify'
payload = json.dumps({
    'meta': {'event_name': 'order_created'},
    'data': {
        'id': 'verify_order_001',
        'attributes': {'user_email': 'verifybuyer@example.com', 'status': 'paid'}
    }
}).encode()

sig = hmac.new(SIGNING_SECRET.encode(), payload, hashlib.sha256).hexdigest()

# Test 1: valid webhook
resp = client.post('/api/lemon/webhook', content=payload,
                   headers={'X-Signature': sig, 'Content-Type': 'application/json'})
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
data = resp.json()
assert data['order_id'] == 'verify_order_001', f"Wrong order_id: {data}"
assert data['duplicate'] == False, f"Should not be duplicate: {data}"
assert 'license_key' in data and len(data['license_key']) > 10, f"No license key: {data}"
print('Test 1 PASS: valid webhook -> license generated')

# Test 2: duplicate idempotency
resp2 = client.post('/api/lemon/webhook', content=payload,
                    headers={'X-Signature': sig, 'Content-Type': 'application/json'})
assert resp2.status_code == 200
assert resp2.json()['duplicate'] == True, f"Should be duplicate: {resp2.json()}"
print('Test 2 PASS: duplicate order_id -> skipped')

# Test 3: bad signature
resp3 = client.post('/api/lemon/webhook', content=payload,
                    headers={'X-Signature': 'badsig', 'Content-Type': 'application/json'})
assert resp3.status_code == 401, f"Expected 401, got {resp3.status_code}"
print('Test 3 PASS: bad signature -> 401')

# Test 4: not paid
not_paid = json.dumps({
    'meta': {'event_name': 'order_created'},
    'data': {'id': 'order_x', 'attributes': {'user_email': 'x@x.com', 'status': 'pending'}}
}).encode()
sig4 = hmac.new(SIGNING_SECRET.encode(), not_paid, hashlib.sha256).hexdigest()
resp4 = client.post('/api/lemon/webhook', content=not_paid,
                    headers={'X-Signature': sig4, 'Content-Type': 'application/json'})
assert resp4.status_code == 200 and resp4.json().get('skipped') == True, f"Should skip: {resp4.json()}"
print('Test 4 PASS: not-paid order -> skipped gracefully')

# Test 5: verify key in DB
rows = db_mod.list_issued_licenses()
assert len(rows) == 1, f"Expected 1 row in DB, got {len(rows)}"
assert rows[0]['order_id'] == 'verify_order_001'
assert rows[0]['revoked'] == 0
print('Test 5 PASS: license stored in DB correctly')

print()
print('ALL VERIFICATION TESTS PASSED')
