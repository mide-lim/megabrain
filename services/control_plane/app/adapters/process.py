"""Typed, read-only observability adapter contracts."""
from dataclasses import dataclass
from typing import Literal
Status=Literal['MATCHED','MISSING','IDENTITY_MISMATCH','ACCESS_DENIED','INCONCLUSIVE']
@dataclass(frozen=True)
class ProcessObservation: pid:int|None; start_time:str|None; boot_id:str|None; process_group:int|None; parent_pid:int|None; user:str|None; cwd:str|None; executable:str|None; cgroup:str|None; status:Status
class ProcessAdapter:
 def observe(self,expected_identity:dict)->ProcessObservation: raise NotImplementedError
