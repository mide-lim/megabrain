from dataclasses import dataclass
@dataclass(frozen=True)
class PreviewObservation:
 bind_address:str|None; port:int|None; backing_identity:dict|None; health_result:str; task_id:str|None; resource_id:str|None; branch:str|None; head:str|None; status:str
class PreviewAdapter:
 def observe(self,expected_identity:dict)->PreviewObservation: raise NotImplementedError
