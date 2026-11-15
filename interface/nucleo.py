"""Núcleo de processamento do Ultron: um conjunto de anéis mecânicos em carmesim e aço com um núcleo branco no centro, desenhado com QPainter.

Cada anel é um dado real; nada aqui é decorativo fingindo ser medição:
  anel de barras externo   CPU do notebook          (/proc/stat)
  anel de barras médio     RAM do notebook          (/proc/meminfo)
  anel de barras interno   CPU do desktop           (WMI via SSH)
  anel de pontos           GPU do desktop           (contadores de GPU do Windows)
  anel de pontos interno   VRAM do desktop
  núcleo                   estado do Ultron e volume da voz/microfone
Barras acesas = uso; as apagadas ficam como trilho. Desktop desligado = anéis
internos escuros.

Interação: passar o mouse sobre um anel mostra o valor e a fonte; clicar num anel
emite zona_clicada(chave) (a janela mostra os detalhes); clicar no núcleo emite
"nucleo" (a janela abre o microfone). O túnel se inclina na direção do mouse.

Movimento segue o estado real (animacao.atual()): em espera tudo gira devagar e o
quadro cai para ~12 fps; pensando/executando os anéis aceleram e rasgos de luz
cortam o túnel; ouvindo/falando o núcleo pulsa com o volume.
"""
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget

from interface import aura

LARANJA = (200, 16, 46)
QUENTE = (255, 36, 63)
OURO = (160, 169, 184)
BRASA = (150, 12, 35)
BRANCO = (230, 232, 236)
FONTE = "FiraCode Nerd Font"
OCIOSOS = aura.OCIOSOS

# (chave, raio interno, raio externo, rótulo, fonte)  raios em fração de R
ZONAS = [
    ("nucleo", 0.00, 0.235, "NÚCLEO", "clique para falar"),
    ("pc_vram", 0.235, 0.300, "VRAM · DESKTOP", "RX 6700 XT · contador do Windows"),
    ("pc_gpu", 0.300, 0.370, "GPU · DESKTOP", "RX 6700 XT · contador do Windows"),
    ("pc_cpu", 0.370, 0.470, "CPU · DESKTOP", "Ryzen 5 5600GT · WMI por SSH"),
    ("nb_ram", 0.470, 0.600, "RAM · NOTEBOOK", "/proc/meminfo"),
    ("nb_cpu", 0.760, 0.980, "CPU · NOTEBOOK", "/proc/stat"),
]


def _c(rgb, alfa=255):
    return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(max(0, min(255, alfa))))


def _mistura(a, b, k):
    return tuple(x + (y - x) * k for x, y in zip(a, b))


def _caneta(rgb, largura, alfa, ponta=Qt.FlatCap):
    p = QPen(_c(rgb, alfa), largura)
    p.setCapStyle(ponta)
    return p


class Nucleo(QWidget):
    zona_clicada = Signal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 320)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.est = aura.Estado()
        self.estado = ""
        self.t0 = time.time()
        self.t_ult = 0.0
        self.tempo_visual = 0.0
        # métricas reais (0-100); None = indisponível
        self.cpu = self.ram = 0.0
        self.ram_txt = ""
        self.desktop = None          # dict de computacao.carga_desktop() ou None
        self.vis = {k: 0.0 for k, *_ in ZONAS}
        # interação
        self.mouse = None            # QPointF dentro do widget
        self.tilt = QPointF(0, 0)    # inclinação suavizada
        self.zona = None
        self.ondas = []              # (t_início, raio_fração) das ondas de clique
        # efeitos
        self.rasgos = []             # rasgos de luz: (t0, ângulo, raio, comprimento, vida)
        self.rastros = [self._novo_rastro(True) for _ in range(18)]
        self.giro = {"a": 0.0, "b": 0.0, "c": 0.0}
        self._cache = {}
        self.erro_ate = 0.0
        self.onda, self.ferramentas = [], {}     # amplitude recente; ferramentas em atividade
        from core.config import ajuste
        self.reduzido = bool(ajuste("visual.movimento_reduzido", False))

    # ------------------------------------------------------------ dados
    def valores(self):
        d = self.desktop or {}
        return {
            "nb_cpu": self.cpu, "nb_ram": self.ram,
            "pc_cpu": d.get("cpu"), "pc_gpu": d.get("gpu"),
            "pc_vram": 100 * d["vram"] / d["vram_total"] if d.get("vram_total") else None,
        }

    def texto_zona(self, chave):
        d = self.desktop
        v = self.valores()
        if chave == "nucleo":
            return {"": "em espera", 'aguardando "Ultron"': 'diga "Ultron"'}.get(self.estado, self.estado)
        if chave.startswith("pc_") and not d:
            return "desktop desligado ou sem resposta"
        if chave == "nb_ram":
            return f"{v['nb_ram']:.0f}%  ({self.ram_txt})"
        if chave == "pc_vram":
            return f"{v['pc_vram']:.0f}%  ({d['vram']:.1f}/{d['vram_total']:.0f} GB)"
        if chave == "pc_cpu":
            return f"{v['pc_cpu']:.0f}%  · RAM {d['ram']:.1f}/{d['ram_total']:.0f} GB"
        return f"{v[chave]:.0f}%"

    # ------------------------------------------------------------ animação
    def _ativo(self):
        return self.estado not in OCIOSOS

    def evento_ferramenta(self, nome, tipo):
        """A janela repassa tool.started/completed/failed reais: o anel externo mostra a atividade."""
        if not nome:
            return
        self.ferramentas[nome] = (time.time(), tipo)
        if len(self.ferramentas) > 12:
            del self.ferramentas[min(self.ferramentas, key=lambda k: self.ferramentas[k][0])]

    def em_erro(self):
        return time.time() < self.erro_ate

    def marcar_erro(self, segundos=4.0):
        self.erro_ate = time.time() + segundos

    def passo(self, estado, nivel):
        """Chamado pelo timer da janela (~30 Hz). Desenha a ~30 fps ativo e ~12 fps em espera."""
        self.estado = estado
        self.est.passo(estado, nivel)
        agora = time.time()
        intervalo = 0.024 if (self._ativo() or self.mouse is not None or self.em_erro()) else 0.083
        if self.reduzido:
            intervalo = 0.2
        jan = self.window()
        if jan.isMinimized():
            return                      # minimizada: nada é desenhado
        if not jan.isActiveWindow() and not self.em_erro():
            intervalo = max(intervalo, 0.066)    # sem foco: ~15 fps
        if not self.isVisible() or agora - self.t_ult < intervalo:
            return
        dt = min(0.1, agora - self.t_ult) if self.t_ult else 0.016
        self.t_ult = agora
        if not hasattr(self, "onda"):
            self.onda, self.ferramentas = [], getattr(self, "ferramentas", {})
        self.onda = (self.onda + [nivel if estado in ("ouvindo", "falando") else 0.0])[-72:]   # amplitude real
        for k, v in self.valores().items():
            alvo = 0.0 if v is None else max(0.0, min(100.0, v))
            self.vis[k] += (alvo - self.vis[k]) * min(1.0, dt * 3)
        esperando = estado == "aguardando aprovação"
        pensando = self._ativo() and estado not in ("ouvindo", "falando", "aguardando aprovação")
        executando = pensando and estado not in ("pensando", "preparando o briefing")   # ferramenta rodando
        vel = 1.0 + (2.6 if pensando else 0.8 if self._ativo() else 0.0) + 2.0 * self.est.nivel
        if esperando:
            vel = 0.2
        if self.reduzido:
            vel = 0.0
        else:
            self.tempo_visual += dt
        if "pesquis" in estado or "busca" in estado:
            vel *= 1.35
        self.giro["a"] += dt * 6 * vel
        self.giro["b"] -= dt * 11 * vel
        self.giro["c"] += dt * 24 * vel
        # rasgos de luz: raros em espera, frequentes processando
        taxa = 0.25 + (9.0 if executando else 4.0 if pensando else 1.2 if self._ativo() else 0) + self.vis["nb_cpu"] / 40
        if self.em_erro():
            taxa = 6.0
        if not self.reduzido and not esperando and random.random() < taxa * dt:
            self.rasgos.append((agora, random.uniform(0, 2 * math.pi), random.uniform(0.35, 0.95),
                                random.uniform(0.18, 0.42), random.uniform(0.35, 0.8)))
        self.rasgos = [r for r in self.rasgos if agora - r[0] < r[4]]
        # rastros de velocidade saindo do centro
        for r in self.rastros:
            r[1] += dt * r[2] * vel * (0.6 + r[1])
            if r[1] > 1.9:
                r[:] = self._novo_rastro()
        self.ondas = [o for o in self.ondas if agora - o[0] < 0.9]
        # inclinação do túnel na direção do mouse
        alvo = QPointF(0, 0)
        if self.mouse is not None:
            alvo = QPointF((self.mouse.x() - self.width() / 2) / self.width(),
                           (self.mouse.y() - self.height() / 2) / self.height())
        self.tilt += (alvo - self.tilt) * min(1.0, dt * 4)
        self.update()

    @staticmethod
    def _novo_rastro(espalhar=False):
        return [random.uniform(0, 2 * math.pi), random.uniform(0.3, 1.9) if espalhar else 0.3,
                random.uniform(0.15, 0.5), random.uniform(0.6, 1.8)]

    # ------------------------------------------------------------ interação
    def _zona_em(self, pos):
        cx, cy, R = self._geo()
        r = math.hypot(pos.x() - cx, pos.y() - cy) / R
        for chave, r0, r1, *_ in ZONAS:
            if r0 <= r < r1:
                return chave
        return None

    def mouseMoveEvent(self, ev):
        self.mouse = ev.position()
        z = self._zona_em(self.mouse)
        if z != self.zona:
            self.zona = z
            self.setCursor(Qt.PointingHandCursor if z else Qt.CrossCursor)

    def leaveEvent(self, _):
        self.mouse = None
        self.zona = None

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        z = self._zona_em(ev.position())
        if z:
            meio = next((a + b) / 2 for k, a, b, *_ in ZONAS if k == z)
            self.ondas.append((time.time(), meio))
            self.zona_clicada.emit(z)

    # ------------------------------------------------------------ desenho
    def _geo(self):
        """Centro e raio, deixando a faixa de baixo livre para o rótulo de estado."""
        w, h = self.width(), self.height() - 90
        return w / 2, 60 + h / 2, min(w, h) * 0.40

    def _camada(self, nome, chave, R, desenhar, bloom=True):
        """Pixmap quadrado (2R) de uma camada, refeito só quando 'chave' muda.
        O bloom (reduzir e ampliar suavizando, somado por cima) dá o brilho de neon."""
        k = (nome, int(R), chave)
        pm = self._cache.get(k)
        if pm is None:
            for velho in [c for c in self._cache if c[0] == nome]:
                del self._cache[velho]
            lado = int(R * 2.1)
            pm = QPixmap(lado, lado)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            q.translate(lado / 2, lado / 2)
            desenhar(q)
            q.end()
            if bloom:
                img = pm.toImage()
                for fator, forca in ((5, 0.15), (14, 0.08)):
                    borrada = img.scaled(max(1, lado // fator), max(1, lado // fator),
                                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation).scaled(
                        lado, lado, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    q = QPainter(pm)
                    q.setCompositionMode(QPainter.CompositionMode_Plus)
                    q.setOpacity(forca)
                    q.drawImage(0, 0, borrada)
                    q.end()
            self._cache[k] = pm
        return pm

    def _por(self, p, pm, cx, cy, giro=0.0):
        if giro:
            p.save()
            p.translate(cx, cy)
            p.rotate(giro)
            p.drawPixmap(QPointF(-pm.width() / 2, -pm.height() / 2), pm)
            p.restore()
        else:
            p.drawPixmap(QPointF(cx - pm.width() / 2, cy - pm.height() / 2), pm)

    def _fundo(self, w, h):
        k = ("fundo", w, h)
        if k not in self._cache:
            for velho in [c for c in self._cache if c[0] == "fundo"]:
                del self._cache[velho]
            pm = QPixmap(w, h)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            # some nas bordas para se fundir ao fundo da janela, sem "caixa"
            g = QRadialGradient(QPointF(w / 2, (h - 26) / 2), min(w, h) * 0.75)
            g.setColorAt(0.0, _c((35, 10, 18)))
            g.setColorAt(0.25, _c((20, 9, 15)))
            g.setColorAt(0.6, _c((8, 7, 11), 200))
            g.setColorAt(1.0, _c((4, 1, 2), 0))
            q.fillRect(0, 0, w, h, QBrush(g))
            q.end()
            self._cache[k] = pm
        return self._cache[k]

    def _campo_radial(self, R):
        """Linhas radiais finas do miolo (estáticas): cache por tamanho."""
        chave = ("campo", int(R))
        if chave not in self._cache:
            self._cache = {k: v for k, v in self._cache.items() if k[0] != "campo"}
            lado = int(R * 2) + 4
            pm = QPixmap(lado, lado)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.translate(lado / 2, lado / 2)
            for i in range(240):
                a = i * 2 * math.pi / 240
                r0, r1 = R * (0.62 if i % 2 else 0.60), R * 0.745
                p.setPen(_caneta(LARANJA, 0.8, 34 if i % 6 else 70))
                p.drawLine(QPointF(math.cos(a) * r0, math.sin(a) * r0),
                           QPointF(math.cos(a) * r1, math.sin(a) * r1))
            # quadrados concêntricos tênues (o "corredor" atrás dos anéis)
            p.setBrush(Qt.NoBrush)
            for k in range(5):
                s = R * (0.30 + 0.08 * k)
                p.setPen(_caneta(BRASA, 1, 40 - 6 * k))
                p.drawRect(QRectF(-s, -s, 2 * s, 2 * s))
            p.end()
            self._cache[chave] = pm
        return self._cache[chave]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.tempo_visual
        w, h = self.width(), self.height()
        cx0, cy0, R = self._geo()
        n = self.est.nivel
        agora = time.time()
        on = bool(self.desktop)
        apagado = 1.0 if on else 0.3
        tinta = LARANJA

        def centro(prof):   # paralaxe: camadas mais fundas andam mais com o mouse
            return cx0 + self.tilt.x() * R * 0.22 * prof, cy0 + self.tilt.y() * R * 0.22 * prof

        def acesas(chave, total):
            return int(round(self.vis[chave] / 100 * total))

        # --- fundo (cache) e rastros de velocidade
        p.drawPixmap(0, 0, self._fundo(w, h))
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        diag = math.hypot(w, h) / 2
        for ang, dist, _, comp in self.rastros:
            r0 = dist * diag * 0.55
            r1 = r0 + comp * 22 * (0.5 + dist)
            if r0 < R * 0.98 and r1 > R * 0.2:
                continue
            if self.reduzido or not self._ativo():
                break
            borda = min(1.0, max(0.0, (diag * 1.05 - r1) / (diag * 0.35)))
            alfa = min(170, 210 * (dist - 0.3) * 0.6) * borda
            larg = 0.8 + dist * 0.9
            a0 = QPointF(cx0 + math.cos(ang) * r0, cy0 + math.sin(ang) * r0)
            a1 = QPointF(cx0 + math.cos(ang) * r1, cy0 + math.sin(ang) * r1)
            if max(a0.y(), a1.y()) > h - 30 or min(a0.y(), a1.y()) < 48:
                continue                       # rótulo de estado e legendas dos cantos ficam limpos
            p.setPen(_caneta(OURO, larg, alfa, Qt.RoundCap))
            p.drawLine(a0, a1)

        # --- túnel: arcos laterais que avançam para fora
        p.setBrush(Qt.NoBrush)
        for k in range(3):
            f = k / 3
            rr = R * (1.02 + f * 0.9)
            ret = QRectF(cx0 - rr, cy0 - rr, 2 * rr, 2 * rr)
            p.setPen(_caneta(LARANJA, 1, 30 * (1 - f)))
            p.drawArc(ret, 150 * 16, 60 * 16)
            p.drawArc(ret, -30 * 16, 60 * 16)

        # Segmentos mecânicos: movimento de presença, não são métricas.
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        for radius, speed, width, color in ((1.09, .4, 3, OURO),
                                           (.715, -1., 4, QUENTE),
                                           (.225, 1.5, 2, BRANCO)):
            box = QRectF(cx0-R*radius, cy0-R*radius, 2*R*radius, 2*R*radius)
            for j, span in enumerate((48, 22, 62, 34)):
                angle = j * 90 + self.giro["b"] * speed
                p.setPen(_caneta(color, width, 160 if radius < 1 else 95))
                p.drawArc(box, int(angle*16), span*16)
        p.setCompositionMode(QPainter.CompositionMode_Plus)

        # --- anel externo: CPU do notebook
        cx, cy = centro(0.2)
        foco = self.zona == "nb_cpu"
        def externo(q):
            self._circulo(q, 0, 0, R * 0.975, OURO, 1.0, 130)
            self._barras(q, 0, 0, R * 0.80, R * 0.94, 84, acesas("nb_cpu", 84), R * 0.017, foco)
            self._circulo(q, 0, 0, R * 0.87, QUENTE, 1.4, 150)
            self._circulo(q, 0, 0, R * 0.765, OURO, 1.0, 160)
        self._por(p, self._camada("ext", (acesas("nb_cpu", 84), foco), R, externo), cx, cy)
        self._cabeca(p, cx, cy, R * 0.80, R * 0.94, 84, acesas("nb_cpu", 84), R * 0.017, t)

        # --- miolo: campo radial e RAM do notebook
        cx, cy = centro(0.45)
        self._por(p, self._campo_radial(R), cx, cy, self.giro["a"])
        foco = self.zona == "nb_ram"
        def ram(q):
            self._circulo(q, 0, 0, R * 0.595, QUENTE, 1.6, 220)
            self._barras(q, 0, 0, R * 0.505, R * 0.58, 120, acesas("nb_ram", 120), R * 0.008, foco)
            self._circulo(q, 0, 0, R * 0.49, QUENTE, 1.6, 220)
        self._por(p, self._camada("ram", (acesas("nb_ram", 120), foco), R, ram), cx, cy)
        self._cabeca(p, cx, cy, R * 0.505, R * 0.58, 120, acesas("nb_ram", 120), R * 0.008, t)
        self._tracos(p, cx, cy, R * 0.615, 36, 3, self.giro["b"], QUENTE, 160)

        # --- desktop: CPU (barras), GPU e VRAM (pontos, desenhados ao vivo)
        cx, cy = centro(0.7)
        foco = self.zona == "pc_cpu"
        def pc(q):
            self._barras(q, 0, 0, R * 0.395, R * 0.455, 96, acesas("pc_cpu", 96), R * 0.007,
                         foco, apagado)
            self._circulo(q, 0, 0, R * 0.385, QUENTE, 1.2, 180 * apagado)
        self._por(p, self._camada("pc", (acesas("pc_cpu", 96), foco, on), R, pc), cx, cy)
        self._pontos(p, cx, cy, R * 0.335, 72, self.vis["pc_gpu"], self.giro["c"],
                     R * 0.009, self.zona == "pc_gpu", apagado)
        self._pontos(p, cx, cy, R * 0.268, 56, self.vis["pc_vram"], -self.giro["c"] * 0.7,
                     R * 0.007, self.zona == "pc_vram", apagado)
        self._tracos(p, cx, cy, R * 0.30, 24, 5, self.giro["c"] * 0.5, OURO, 110 * apagado)

        # --- rasgos de luz cortando os anéis
        for t0, ang, rad, comp, vida in self.rasgos:
            k = (agora - t0) / vida
            alfa = 255 * math.sin(math.pi * k)
            px, py = cx0 + math.cos(ang) * R * rad, cy0 + math.sin(ang) * R * rad
            dx, dy = math.cos(ang + 1.15) * R * comp / 2, math.sin(ang + 1.15) * R * comp / 2
            a0, a1 = QPointF(px - dx, py - dy), QPointF(px + dx, py + dy)
            p.setPen(_caneta(LARANJA, 9, alfa * 0.25, Qt.RoundCap))
            p.drawLine(a0, a1)
            p.setPen(_caneta(OURO, 3.5, alfa * 0.7, Qt.RoundCap))
            p.drawLine(a0, a1)
            p.setPen(_caneta(BRANCO, 1.4, alfa, Qt.RoundCap))
            p.drawLine(a0, a1)

        # --- núcleo incandescente
        cx, cy = centro(1.0)
        cor_nucleo = _mistura(BRASA, self.est.cor, 0.35)
        if self.em_erro():
            cor_nucleo = (255, 20, 30)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            pisca = 0.5 + 0.5 * math.sin(t * 1.5)
            self._circulo(p, cx0, cy0, R * 0.99, (255, 30, 40), 3, 120 + 120 * pisca)
            p.setCompositionMode(QPainter.CompositionMode_Plus)
        pulso = 1 + 0.06 * math.sin(t * (1.2 if not self._ativo() else 3.0)) + 0.35 * n
        rn = R * 0.21 * pulso
        g = QRadialGradient(QPointF(cx, cy), rn * 1.7)
        g.setColorAt(0.0, _c((255, 75, 92), 200))
        g.setColorAt(0.10, _c((255, 36, 63), 160))
        g.setColorAt(0.22, _c(_mistura(BRANCO, (255, 36, 63), 0.5), 120))
        g.setColorAt(0.45, _c((200, 16, 46), 90))
        g.setColorAt(0.75, _c(cor_nucleo, 60))
        g.setColorAt(1.0, _c(cor_nucleo, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), rn * 1.7, rn * 1.7)
        for k in range(3):       # pontilhados dentro do núcleo (o túnel continua)
            rr = rn * (0.55 + 0.25 * k)
            self._tracos(p, cx, cy, rr, 40 + 12 * k, 2, self.giro["c"] * (1.5 - k * 0.6),
                         (255, 75, 92), 110 - 25 * k)

        # --- erro: o núcleo inteiro vira vermelho e pulsa (multiplica o laranja por vermelho)
        if self.em_erro():
            pisca = 0.55 + 0.45 * math.sin(t * 1.5)
            p.setCompositionMode(QPainter.CompositionMode_Multiply)
            g = QRadialGradient(QPointF(cx0, cy0), R)
            g.setColorAt(0.0, _c((255, 120, 120)))
            g.setColorAt(1.0, _c((255, int(40 + 50 * (1 - pisca)), 40)))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(cx0, cy0), R, R)
            p.setCompositionMode(QPainter.CompositionMode_Plus)

        # --- camadas adaptadas das referências (técnica, não código): forma de onda, radar,
        #     retícula técnica e atividade das ferramentas no anel externo
        self._forma_de_onda(p, cx, cy, R)
        if "pesquis" in self.estado or "busca" in self.estado:
            self._radar(p, cx0, cy0, R, t)
        self._por(p, self._camada("reticula", None, R, lambda q: self._reticula(q, R), bloom=False), cx0, cy0)
        self._rumos(p, cx0, cy0, R)
        self._atividade_ferramentas(p, cx0, cy0, R, agora)

        # --- ondas de clique
        for t0, fr in self.ondas:
            k = (agora - t0) / 0.9
            self._circulo(p, cx0, cy0, R * (fr + k * 0.25), BRANCO, 2.5 * (1 - k), 255 * (1 - k))

        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self._legendas(p, w, h, on)
        if self.zona and self.mouse is not None:
            self._balao(p, self.zona, self.mouse, w, h)
        p.end()

    # ------------------------------------------------------------ camadas de processamento
    def _forma_de_onda(self, p, cx, cy, R):
        """72 barras radiais em volta do núcleo: o histórico recente da amplitude real (mic/voz)."""
        onda = getattr(self, "onda", [])
        if not onda or max(onda) < 0.02:
            return
        r0 = R * 0.235
        for i, v in enumerate(onda):
            a = -math.pi / 2 + i * 2 * math.pi / 72
            comp = R * 0.11 * min(1.0, v * 1.6)
            if comp < 1:
                continue
            p.setPen(_caneta((255, 75, 92), 2.2, 120 + 120 * min(1.0, v * 2)))
            p.drawLine(QPointF(cx + math.cos(a) * r0, cy + math.sin(a) * r0),
                       QPointF(cx + math.cos(a) * (r0 + comp), cy + math.sin(a) * (r0 + comp)))

    @staticmethod
    def _radar(p, cx, cy, R, t):
        """Varredura radial (PESQUISANDO): uma cunha com rastro girando no miolo."""
        varre = (t * 140) % 360
        for k in range(22):
            ang = math.radians(varre - k * 2.0)
            p.setPen(_caneta((255, 36, 63), 2.0, 150 * (1 - k / 22)))
            p.drawLine(QPointF(cx + math.cos(ang) * R * 0.30, cy - math.sin(ang) * R * 0.30),
                       QPointF(cx + math.cos(ang) * R * 0.74, cy - math.sin(ang) * R * 0.74))

    @staticmethod
    def _reticula(q, R):
        """Retícula técnica estática (cache): cruz fina interrompida, colchetes e rumos."""
        cor = (133, 139, 150)
        q.setPen(_caneta(cor, 0.8, 70))
        for a in (0, 90, 180, 270):
            r = math.radians(a)
            q.drawLine(QPointF(math.cos(r) * R * 0.62, math.sin(r) * R * 0.62),
                       QPointF(math.cos(r) * R * 0.74, math.sin(r) * R * 0.74))
        q.setPen(_caneta(cor, 1.0, 110))
        for a in (45, 135, 225, 315):
            ret = QRectF(-R * 1.0, -R * 1.0, R * 2.0, R * 2.0)
            q.drawArc(ret, int((a - 4) * 16), int(8 * 16))

    @staticmethod
    def _rumos(p, cx, cy, R):
        """Rumos 000/090/180/270 fora do anel externo (direto na tela: o cache só cobre até 1,05 R)."""
        f = QFont(FONTE, max(9, int(R * 0.042)))
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(f)
        p.setPen(_c((133, 139, 150), 200))
        for a, rot in ((0, "090"), (90, "000"), (180, "270"), (270, "180")):
            r = math.radians(a)
            p.drawText(QRectF(cx + math.cos(r) * R * 1.08 - 30, cy - math.sin(r) * R * 1.08 - 10, 60, 20), Qt.AlignCenter, rot)

    def _atividade_ferramentas(self, p, cx, cy, R, agora):
        """Cada ferramenta real acende um segmento do anel externo com o nome dela (2,5 s);
        concluída pisca em branco, falha em vermelho vivo."""
        ativos = {n: v for n, v in getattr(self, "ferramentas", {}).items() if agora - v[0] < 2.5}
        if not ativos:
            return
        fo = QFont(FONTE, max(9, int(R * 0.042)), QFont.DemiBold)
        fo.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(fo)
        ret = QRectF(cx - R * 0.985, cy - R * 0.985, R * 1.97, R * 1.97)
        for nome, (t0, tipo) in ativos.items():
            idade = (agora - t0) / 2.5
            ang = (sum(map(ord, nome)) * 37) % 360
            cor = {"tool.failed": (255, 36, 63), "tool.completed": (230, 232, 236)}.get(tipo, (255, 75, 92))
            p.setPen(_caneta(cor, 5, 255 * (1 - idade)))
            p.drawArc(ret, int(ang * 16), int(18 * 16))
            r = math.radians(ang + 9)
            p.setPen(_c(cor, 230 * (1 - idade)))
            p.drawText(QRectF(cx + math.cos(r) * R * 1.08 - 80, cy - math.sin(r) * R * 1.08 - 8, 160, 16),
                       Qt.AlignCenter, nome.replace("_", " ").upper()[:22])

    # ------------------------------------------------------------ primitivas
    @staticmethod
    def _circulo(p, cx, cy, r, rgb, largura, alfa):
        p.setBrush(Qt.NoBrush)
        p.setPen(_caneta(rgb, largura * 3.5, alfa * 0.18))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(_caneta(rgb, largura, alfa))
        p.drawEllipse(QPointF(cx, cy), r, r)

    @staticmethod
    def _barras(p, cx, cy, r0, r1, n, acesas, largura, foco, apagado=1.0):
        """Barras radiais a partir do topo, sentido horário: as 'acesas' brilham."""
        trilho = QPainterPath()
        luz = QPainterPath()
        for i in range(n):
            a = -math.pi / 2 + i * 2 * math.pi / n
            ca, sa = math.cos(a), math.sin(a)
            ri = r0 + (r1 - r0) * (0.18 if i % 2 else 0)   # comprimentos alternados
            alvo = luz if i < acesas else trilho
            alvo.moveTo(cx + ca * ri, cy + sa * ri)
            alvo.lineTo(cx + ca * r1, cy + sa * r1)
        p.setBrush(Qt.NoBrush)
        p.setPen(_caneta(LARANJA, largura, (150 if foco else 95) * apagado))
        p.drawPath(trilho)
        if not luz.isEmpty():
            p.setPen(_caneta(QUENTE, largura * 1.15, 255 * apagado))
            p.drawPath(luz)
            p.setPen(_caneta(BRANCO, largura * 0.4, 235 * apagado))
            p.drawPath(luz)

    @staticmethod
    def _cabeca(p, cx, cy, r0, r1, n, acesas, largura, t):
        """A última barra acesa cintila: mostra onde a medição está agora."""
        if acesas <= 0:
            return
        a = -math.pi / 2 + (acesas - 1) * 2 * math.pi / n
        p.setPen(_caneta(BRANCO, largura * 1.4, 200))
        p.drawLine(QPointF(cx + math.cos(a) * r0, cy + math.sin(a) * r0),
                   QPointF(cx + math.cos(a) * r1, cy + math.sin(a) * r1))

    @staticmethod
    def _pontos(p, cx, cy, r, n, valor, giro, raio, foco, apagado=1.0):
        """Anel de pontos: os acesos (valor%) brilham e giram juntos."""
        acesos = valor / 100 * n
        p.setPen(Qt.NoPen)
        for i in range(n):
            a = math.radians(giro) + i * 2 * math.pi / n
            x, y = cx + math.cos(a) * r, cy + math.sin(a) * r
            if i < acesos:
                p.setBrush(_c(QUENTE, 80 * apagado))
                p.drawEllipse(QPointF(x, y), raio * 2.4, raio * 2.4)
                p.setBrush(_c(BRANCO, 245 * apagado))
                p.drawEllipse(QPointF(x, y), raio, raio)
            else:
                p.setBrush(_c(LARANJA, (140 if foco else 90) * apagado))
                p.drawEllipse(QPointF(x, y), raio * 0.6, raio * 0.6)

    @staticmethod
    def _tracos(p, cx, cy, r, n, abertura, giro, rgb, alfa):
        ret = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.setBrush(Qt.NoBrush)
        p.setPen(_caneta(rgb, 1.6, alfa))
        passo = 360 / n
        for i in range(n):
            p.drawArc(ret, int((giro + i * passo) * 16), int(abertura * 16))

    def _legendas(self, p, w, h, on):
        v = self.valores()
        f = QFont(FONTE, 8, QFont.DemiBold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(f)
        cantos = [("NB CPU", v["nb_cpu"], 12, 10, Qt.AlignLeft),
                  ("NB RAM", v["nb_ram"], 12, 28, Qt.AlignLeft),
                  ("PC CPU", v["pc_cpu"], w - 12, 10, Qt.AlignRight),
                  ("PC GPU", v["pc_gpu"], w - 12, 28, Qt.AlignRight)]
        for rot, val, x, y, al in cantos:
            txt = f"{rot} {val:3.0f}%" if val is not None else f"{rot}  --"
            ret = QRectF(x - 160 if al == Qt.AlignRight else x, y, 160, 16)
            p.setPen(_c(QUENTE, 220 if val is not None else 90))
            p.drawText(ret, al | Qt.AlignVCenter, txt)
        if not on:
            p.setPen(_c(LARANJA, 120))
            p.drawText(QRectF(w - 172, 46, 160, 16), Qt.AlignRight | Qt.AlignVCenter, "DESKTOP OFFLINE")
        rot = {"": "EM ESPERA", 'aguardando "Ultron"': 'DIGA "ULTRON"'}.get(self.estado, self.estado.upper())
        cor_rot = _mistura(QUENTE, self.est.cor, 0.4)
        if self.em_erro():
            rot, cor_rot = "ERRO NA ÚLTIMA AÇÃO", (255, 70, 80)
        f.setPointSize(9)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        p.setFont(f)
        p.setPen(_c(cor_rot, 235))
        p.drawText(QRectF(0, h - 24, w, 18), Qt.AlignCenter, "CLIQUE NO CENTRO PARA FALAR")

    def _balao(self, p, chave, pos, w, h):
        _, _, _, rotulo, fonte_txt = next(z for z in ZONAS if z[0] == chave)
        linhas = [rotulo, self.texto_zona(chave), fonte_txt]
        if chave != "nucleo":
            linhas.append("clique: detalhes")
        f = QFont(FONTE, 8)
        p.setFont(f)
        larg = max(p.fontMetrics().horizontalAdvance(l) for l in linhas) + 20
        alt = 16 * len(linhas) + 10
        x = min(pos.x() + 16, w - larg - 4)
        y = min(pos.y() + 16, h - alt - 4)
        p.setPen(_caneta(QUENTE, 1, 200))
        p.setBrush(_c((14, 5, 5), 225))
        p.drawRect(QRectF(x, y, larg, alt))
        for i, l in enumerate(linhas):
            p.setPen(_c(BRANCO if i == 1 else QUENTE, 245 if i < 2 else 150))
            p.drawText(QRectF(x + 10, y + 5 + 16 * i, larg, 16), Qt.AlignLeft | Qt.AlignVCenter, l)
