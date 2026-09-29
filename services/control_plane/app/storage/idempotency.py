"""Mutation idempotency persistence."""
from __future__ import annotations
import hashlib,json
from ..models import canonical_json,utc_now
from ..errors import fail
def fingerprint(protocol_version,operation,caller_id,capability_id,expected_revision,body): return hashlib.sha256(canonical_json({"protocol_version":protocol_version,"operation":operation,"caller_id":caller_id,"capability_id":capability_id,"expected_revision":expected_revision,"body":body}).encode()).hexdigest()
def begin(con,caller_id,key,operation,digest):
    row=con.execute("SELECT * FROM idempotency_requests WHERE caller_id=? AND idempotency_key=?",(caller_id,key)).fetchone()
    if row:
        if row['operation']!=operation or row['request_fingerprint']!=digest: raise fail("IDEMPOTENCY_CONFLICT","idempotency key reused for a different request")
        if row['status']=="IN_PROGRESS": raise fail("REGISTRY_UNAVAILABLE","operation in progress",True)
        return json.loads(row['response_body']),True
    con.execute("INSERT INTO idempotency_requests VALUES(?,?,?,?,?,NULL,'IN_PROGRESS',NULL,NULL,NULL)",(caller_id,key,operation,digest,utc_now())); return None,False
def finalize(con,caller_id,key,response,result_reference=None,code="OK"):
    con.execute("UPDATE idempotency_requests SET finalized_at=?,status='SUCCEEDED',result_reference=?,response_code=?,response_body=? WHERE caller_id=? AND idempotency_key=?",(utc_now(),result_reference,code,canonical_json(response),caller_id,key))
