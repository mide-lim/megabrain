from dataclasses import dataclass
@dataclass(frozen=True)
class SecurityObservation:
 ssh:dict; firewall:dict; fail2ban:dict; status:str
class SecurityAdapter:
 def observe(self,scope:dict)->SecurityObservation: raise NotImplementedError
