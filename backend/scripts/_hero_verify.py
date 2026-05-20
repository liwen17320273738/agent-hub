"""Verify hero path delivery for a task."""
import json, subprocess, sys

BASE = 'http://localhost:8000'
TASK_ID = sys.argv[1] if len(sys.argv) > 1 else 'b1fac4b2-1d84-4d1f-8c73-ad704f74dfc8'

def curl(path, method='GET', body=None):
    cmd = ['curl', '-s', f'{BASE}{path}', '-H', f'Authorization: Bearer {TOKEN}']
    if method == 'POST' and body:
        cmd += ['-X', 'POST', '-H', 'Content-Type: application/json', '-d', json.dumps(body)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)

# Login
result = subprocess.run(
    ['curl', '-s', f'{BASE}/api/auth/login', '-X', 'POST',
     '-H', 'Content-Type: application/json',
     '-d', '{"email":"admin@example.com","password":"changeme"}'],
    capture_output=True, text=True)
TOKEN = json.loads(result.stdout)['access_token']

# Contract
contract = curl(f'/api/pipeline/tasks/{TASK_ID}/artifact-contract')
print(json.dumps(contract, indent=2, ensure_ascii=False))

# Share
share = curl('/api/share/generate', 'POST', {'task_id': TASK_ID, 'ttl_days': 7})
print(f"\nShare token: {share.get('token', share.get('detail', '?'))[:50]}...")

# ZIP
zip_resp = subprocess.run(
    ['curl', '-s', '-o', '/tmp/hero_test_deliverables.zip', '-w', '%{http_code}',
     f'{BASE}/api/tasks/{TASK_ID}/deliverables.zip',
     '-H', f'Authorization: Bearer {TOKEN}'],
    capture_output=True, text=True)
print(f"ZIP download: HTTP {zip_resp.stdout}")
import os
size = os.path.getsize('/tmp/hero_test_deliverables.zip')
print(f"ZIP size: {size} bytes")
