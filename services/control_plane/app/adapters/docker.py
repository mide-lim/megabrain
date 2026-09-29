from dataclasses import dataclass
@dataclass(frozen=True)
class DockerObservation:
 container_identity:str|None; container_name:str|None; compose_project:str|None; compose_service:str|None; image_digest:str|None; state:str|None; health:str|None; restart_policy:str|None; networks:tuple[str,...]; mounts:tuple[dict,...]; published_ports:tuple[dict,...]; approved_labels:dict; status:str
class DockerAdapter:
 def observe(self,scope:dict)->DockerObservation: raise NotImplementedError
