import sys, pathlib, importlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget
from PySide6.QtCore import QTimer
app=QApplication([])
mode, dest=sys.argv[1:3]
pathlib.Path(dest).mkdir(parents=True,exist_ok=True)
steps=[]
def start():
    wins=[w for w in app.topLevelWidgets() if w.isVisible() and w.windowTitle().startswith('Ultron') and not w.isModal()]
    if not wins:
        QTimer.singleShot(1000,start); return
    w=wins[0]; w.raise_(); w.activateWindow()
    tabs=w.findChildren(QTabWidget)
    steps.append(('principal',None,None))
    if mode == 'main':
        steps.extend([('pequena',None,None), ('sistema',None,None), ('contexto',None,None)])
    for t in tabs:
        for i in range(t.count()): steps.append((t.tabText(i),t,i))
    def snap():
        if not steps: app.quit(); return
        name,t,i=steps.pop(0)
        if t: t.setCurrentIndex(i)
        if name == 'pequena': w.resize(900,620)
        if name == 'sistema':
            w.resize(1360,840); w.bt_sistema.click()
        if name == 'contexto':
            w.bt_sistema.click(); w.bt_contexto.click()
        if name == 'conversa':
            w.bt_contexto.click(); w.ch_falar.setChecked(False)
            w.campo.setText('Responda apenas: canal de comunicação operacional. Não use ferramentas.')
            w.enviar()
        def save():
            w.grab().save(str(pathlib.Path(dest)/(name.replace('/','-')+'.png')))
            print(name,flush=True); snap()
        QTimer.singleShot(20000 if name == 'conversa' else 800,save)
    snap()
QTimer.singleShot(3500,start)
if mode=='main':
    from core import registro
    registro.carregar()
    from interface.app import rodar
    rodar()
else:
    importlib.import_module({'modules':'interface.modulos','neural':'neuralink.janela','forge':'evolucao.forja', 'forge_classico':'evolucao.centro'}[mode]).abrir()
