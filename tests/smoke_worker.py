import os, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
os.environ['SCOOBY_DATA']=tempfile.mkdtemp(prefix='scooby-worker-smoke-')
from store import db,job
with db() as c: jid=job(c,'scan','bounded-empty','smoke')
p=subprocess.Popen([sys.executable,'-m','huey.bin.huey_consumer','worker.huey','-w','1','-q'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
try:
 from worker import wake
 wake()
 for _ in range(100):
  with db() as c: state=c.execute('SELECT state,error FROM jobs WHERE id=?',(jid,)).fetchone()
  if state['state']=='done': break
  time.sleep(.1)
 assert state['state']=='done',dict(state)
 print('PASS: separate Huey worker processed persisted scan:',state['error'])
finally:
 p.terminate()
 try: p.wait(timeout=10)
 except subprocess.TimeoutExpired: p.kill(); p.wait()
 print('Worker stopped')

