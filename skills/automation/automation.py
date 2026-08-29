from __future__ import annotations
import threading,uuid,time
from datetime import datetime,timezone
_jobs={}; _lock=threading.RLock()

def schedule(command:str,delay_seconds:float=0,repeat_seconds:float|None=None)->str:
    job_id=str(uuid.uuid4())
    def run():
        from brain.cognitive_loop import process_command
        try: process_command(command,session_id=f'job:{job_id}')
        finally:
            if repeat_seconds and job_id in _jobs:
                timer=threading.Timer(float(repeat_seconds),run);timer.daemon=True;_jobs[job_id]=timer;timer.start()
            else:_jobs.pop(job_id,None)
    timer=threading.Timer(max(0,float(delay_seconds)),run);timer.daemon=True
    with _lock:_jobs[job_id]=timer
    timer.start();return job_id

def cancel(job_id:str)->bool:
    with _lock:t=_jobs.pop(job_id,None)
    if t:t.cancel();return True
    return False

def list_schedules()->list[dict]:
    with _lock:return [{"id":k,"alive":v.is_alive()} for k,v in _jobs.items()]
