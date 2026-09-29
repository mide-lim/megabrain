"""JCS audit envelope hashing and recovery validation."""
from __future__ import annotations
import hashlib
from .sqlite import immediate
from ..ids import generate_id
from ..models import canonical_json,utc_now
from ..errors import fail
ENVELOPE_KEYS=("actor","correlation_id","event_id","event_type","occurred_at","payload","prior_event_hash","resource_id","schema_version","sequence","task_id")
def event_envelope(**values): return {key:values.get(key) for key in ENVELOPE_KEYS}
def hash_envelope(envelope: dict)->str: return hashlib.sha256(canonical_json(envelope).encode()).hexdigest()
def append_event(con,event_type,actor,correlation_id,payload,task_id=None,resource_id=None,occurred_at=None,event_id=None):
    head=con.execute("SELECT metadata_value FROM registry_metadata WHERE metadata_key='event_chain_head_sequence'").fetchone(); seq=int(head[0])+1
    prior=con.execute("SELECT metadata_value FROM registry_metadata WHERE metadata_key='event_chain_head_hash'").fetchone()[0] or None
    event_id=event_id or generate_id("evt"); occurred_at=occurred_at or utc_now()
    envelope=event_envelope(actor=actor,correlation_id=correlation_id,event_id=event_id,event_type=event_type,occurred_at=occurred_at,payload=payload,prior_event_hash=prior,resource_id=resource_id,schema_version="1.0.0",sequence=seq,task_id=task_id); digest=hash_envelope(envelope)
    con.execute("INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(event_id,seq,"1.0.0",event_type,occurred_at,task_id,resource_id,canonical_json(actor),correlation_id,canonical_json(payload),prior,digest))
    now=utc_now(); con.execute("UPDATE registry_metadata SET metadata_value=?,updated_at=? WHERE metadata_key='event_chain_head_sequence'",(str(seq),now)); con.execute("UPDATE registry_metadata SET metadata_value=?,updated_at=? WHERE metadata_key='event_chain_head_hash'",(digest,now)); return event_id,seq,digest
def validate_chain(con):
    prior=None; sequence=0
    for row in con.execute("SELECT * FROM audit_events ORDER BY sequence"):
        sequence+=1
        if row["sequence"] != sequence or row["prior_event_hash"] != prior: return False
        envelope=event_envelope(actor=__import__('json').loads(row['actor']),correlation_id=row['correlation_id'],event_id=row['event_id'],event_type=row['event_type'],occurred_at=row['occurred_at'],payload=__import__('json').loads(row['payload']),prior_event_hash=prior,resource_id=row['resource_id'],schema_version=row['schema_version'],sequence=row['sequence'],task_id=row['task_id'])
        if hash_envelope(envelope)!=row['event_hash']: return False
        prior=row['event_hash']
    metadata={r[0]:r[1] for r in con.execute("SELECT metadata_key,metadata_value FROM registry_metadata")}
    return metadata.get("event_chain_head_sequence")==str(sequence) and metadata.get("event_chain_head_hash","")== (prior or "")
