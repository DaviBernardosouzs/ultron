"""Executor que roda DENTRO do sandbox (não importa nada do Ultron).

Uso: python executor.py testar|chamar  (JSON pela entrada padrão)
  testar: importa /codigo/testes.py e roda cada função teste_*; devolve resultados.
  chamar: importa /codigo/ferramenta.py e chama {"funcao", "argumentos"}.
A última linha da saída é sempre um JSON.
"""
import json
import sys
import time
import traceback

sys.path.insert(0, "/codigo")
sys.dont_write_bytecode = True


def _saida(obj):
    sys.stdout.write("\n" + json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def testar():
    import importlib
    try:
        mod = importlib.import_module("testes")
    except Exception:
        _saida({"ok": False, "erro": "testes.py não importou:\n" + traceback.format_exc(limit=3)})
        return
    resultados = []
    for nome in sorted(n for n in dir(mod) if n.startswith("teste_")):
        inicio = time.perf_counter()
        try:
            getattr(mod, nome)()
            resultados.append({"teste": nome, "ok": True,
                               "ms": round((time.perf_counter() - inicio) * 1000, 2)})
        except Exception as e:
            resultados.append({"teste": nome, "ok": False, "erro": f"{type(e).__name__}: {e}"[:500],
                               "ms": round((time.perf_counter() - inicio) * 1000, 2)})
    _saida({"ok": True, "resultados": resultados})


def chamar(pedido):
    try:
        import ferramenta
        valor = getattr(ferramenta, pedido["funcao"])(**(pedido.get("argumentos") or {}))
        _saida({"ok": True, "valor": valor})
    except Exception as e:
        _saida({"ok": False, "erro": f"{type(e).__name__}: {e}"[:1000]})


if __name__ == "__main__":
    modo = sys.argv[1]
    pedido = json.loads(sys.stdin.read() or "{}")
    testar() if modo == "testar" else chamar(pedido)
