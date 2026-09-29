from dataclasses import dataclass
@dataclass(frozen=True)
class GitWorktreeObservation:
 repository_identity:str|None; worktree_path:str|None; registered_state:str; branch:str|None; head:str|None; base:str|None; dirty:str; lock_state:str; status:str
class GitWorktreeAdapter:
 def observe(self,expected_identity:dict)->GitWorktreeObservation: raise NotImplementedError
