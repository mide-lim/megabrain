import hashlib,json
from pathlib import Path

def test_paperclip_fixture_manifest_and_required_families():
 p=Path(__file__).parent/'fixtures/paperclip/ap0-v1-control-plane-export.json';m=Path(str(p).replace('.json','.sha256')).read_text().strip().split()[0]
 assert hashlib.sha256(p.read_bytes()).hexdigest()==m
 d=json.loads(p.read_text()); assert {'tasks','resource_leases','audit_events','heartbeats','gates','checkpoints'}<=set(d)
 assert any(x['state']=='ALLOCATED' for x in d['resource_leases']) and any(x['status']=='CONSUMED' for x in d['gates'])
