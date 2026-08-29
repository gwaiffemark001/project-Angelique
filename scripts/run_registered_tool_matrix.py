from __future__ import annotations
import json, subprocess, os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core.tools
from core.tools_adapter import migrate_registry
from core.tool_registry import GLOBAL_TOOL_REGISTRY
migrate_registry()
root=Path(__file__).resolve().parents[1]
names=GLOBAL_TOOL_REGISTRY.list()

def one(item):
    idx,name=item
    try:
        cp=subprocess.run(['python','-u',str(root/'scripts'/'invoke_registered_tool_one.py'),name],cwd=root,text=True,capture_output=True,timeout=8,env={**os.environ,'PYTHONUNBUFFERED':'1'})
        combined=(cp.stdout+'\n'+cp.stderr).strip()
        ok=cp.returncode==0 and 'RESULT ' in combined
        return {'idx':idx,'tool':name,'status':'PASS' if ok else 'FAIL','detail':combined[-1600:]}
    except subprocess.TimeoutExpired:
        return {'idx':idx,'tool':name,'status':'TIMEOUT','detail':'8 second isolated invocation timeout'}

results=[]
with ThreadPoolExecutor(max_workers=12) as ex:
    futures=[ex.submit(one,item) for item in enumerate(names,1)]
    for f in as_completed(futures):
        r=f.result(); results.append(r); print(f"[{r['idx']:03}/{len(names):03}] {r['status']} {r['tool']}",flush=True)
results.sort(key=lambda x:x['idx'])
out=Path('/mnt/data/registered_tool_matrix.json')
out.write_text(json.dumps({'total':len(results),'passed':sum(r['status']=='PASS' for r in results),'failed':sum(r['status']!='PASS' for r in results),'results':results},indent=2))
print('SUMMARY',len(results),sum(r['status']=='PASS' for r in results),sum(r['status']!='PASS' for r in results))
