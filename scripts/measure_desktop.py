import sys,time,json,resource
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QMainWindow
from PySide6.QtCore import QTimer
app=QApplication([])
result=[]
def measure():
    w=next((w for w in app.topLevelWidgets() if isinstance(w,QMainWindow) and hasattr(w,'reator')),None)
    if w is None: QTimer.singleShot(1000,measure); return
    states=['idle','reduzido','minimizado']
    def step():
        if not states:
            print(json.dumps(result),flush=True); app.quit(); return
        state=states.pop(0)
        if state=='reduzido': w.ch_reduzido.setChecked(True)
        if state=='minimizado': w.showMinimized()
        cpu=time.process_time(); clock=time.monotonic()
        def finish():
            result.append({'modo':state,'cpu_um_nucleo_pct':round(100*(time.process_time()-cpu)/(time.monotonic()-clock),1),
              'rss_max_mb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1)})
            step()
        QTimer.singleShot(6000,finish)
    step()
QTimer.singleShot(5000,measure)
from interface.app import rodar
rodar()
