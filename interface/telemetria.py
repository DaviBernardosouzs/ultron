"""Telemetria do notebook lida direto do /proc e /sys (sem dependências)."""
import glob
import os
import shutil
import time


class Telemetria:
    def __init__(self):
        self._cpu_ant = self._cpu_bruto()
        self._rede_ant = (self._rede_bruta(), time.time())
        self.dados = {}
        self.ler()

    @staticmethod
    def _cpu_bruto():
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        ocioso = v[3] + v[4]
        return sum(v), ocioso

    @staticmethod
    def _rede_bruta():
        rx = tx = 0
        with open("/proc/net/dev") as f:
            for linha in f.readlines()[2:]:
                nome, resto = linha.split(":", 1)
                if nome.strip() == "lo":
                    continue
                campos = resto.split()
                rx += int(campos[0])
                tx += int(campos[8])
        return rx, tx

    @staticmethod
    def _temperatura():
        melhores = []
        for hw in glob.glob("/sys/class/hwmon/hwmon*"):
            try:
                nome = open(f"{hw}/name").read().strip()
            except OSError:
                continue
            if nome in ("k10temp", "coretemp", "zenpower", "acpitz", "cpu_thermal"):
                for t in glob.glob(f"{hw}/temp*_input"):
                    try:
                        melhores.append(int(open(t).read()) / 1000)
                    except (OSError, ValueError):
                        pass
                if melhores:
                    break
        return max(melhores) if melhores else None

    @staticmethod
    def _bateria():
        for b in ("BAT0", "BAT1"):
            base = f"/sys/class/power_supply/{b}"
            if os.path.exists(base):
                try:
                    return int(open(f"{base}/capacity").read()), open(f"{base}/status").read().strip()
                except OSError:
                    pass
        return None, None

    def ler(self):
        total, ocioso = self._cpu_bruto()
        t0, o0 = self._cpu_ant
        self._cpu_ant = (total, ocioso)
        cpu = 0.0 if total == t0 else 100 * (1 - (ocioso - o0) / (total - t0))
        mem = {}
        with open("/proc/meminfo") as f:
            for l in f:
                k, v = l.split(":")
                mem[k] = int(v.split()[0])
        ram = 100 * (1 - mem["MemAvailable"] / mem["MemTotal"])
        disco = shutil.disk_usage("/")
        (rx, tx), agora = self._rede_bruta(), time.time()
        (rx0, tx0), t_ant = self._rede_ant
        self._rede_ant = ((rx, tx), agora)
        dt = max(agora - t_ant, 0.1)
        bat, bat_estado = self._bateria()
        with open("/proc/uptime") as f:
            ligado = float(f.read().split()[0])
        self.dados = {
            "cpu": max(0.0, min(100.0, cpu)), "ram": ram,
            "ram_txt": f"{(mem['MemTotal'] - mem['MemAvailable']) / 1048576:.1f}/{mem['MemTotal'] / 1048576:.1f} GB",
            "disco": 100 * disco.used / disco.total, "bateria": bat, "bateria_estado": bat_estado,
            "temp": self._temperatura(), "rx": (rx - rx0) / dt, "tx": (tx - tx0) / dt,
            "ligado": ligado, "carga": os.getloadavg()[0], "nucleos": os.cpu_count()}
        return self.dados


def taxa(bps):
    for un in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024:
            return f"{bps:.0f} {un}" if un == "B/s" else f"{bps:.1f} {un}"
        bps /= 1024
    return f"{bps:.1f} TB/s"
