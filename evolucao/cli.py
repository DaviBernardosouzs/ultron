"""`ultron evolucao <comando>`: a parte humana do motor de evolução.

  inventario                 capacidades instaladas
  necessidades               o que faltou ao Ultron
  candidatos                 melhorias em desenvolvimento
  pendentes                  pedidos de aprovação (com relatório)
  aprovar ID [N1|N2|N3]      instala/ativa (padrão N2: a ferramenta pede confirmação)
  rejeitar ID [motivo]
  avaliar PASTA              reavalia um candidato (sandbox + testes + comparação)
  desativar|reativar|desinstalar NOME
  rollback NOME [VERSAO]     volta para a versão anterior guardada
  versoes NOME
  remover-skill NOME
  historico [N]
  diagnostico
  centro | forja             abre a Evolution Forge (centro-classico: janela antiga)
"""
import json
import sys

from evolucao import aprovacao, avaliacao, base, capacidades, descoberta, extensoes, skills


def _tabela(linhas):
    for l in linhas:
        print(l)


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "ajuda"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "inventario":
            _tabela(f"{i['tipo']:10} {i['nome']:38} v{i['versao']:8} {str(i['permissoes'].get('nivel')):6} "
                    f"{i['status']}" for i in capacidades.inventario())
        elif cmd == "necessidades":
            _tabela(f"{n['id']} [{n['estado']}] x{n.get('vezes', 1)} {n['descricao']}"
                    for n in descoberta.necessidades())
        elif cmd == "candidatos":
            for p in sorted(base.CANDIDATOS.iterdir()):
                r = avaliacao.ultima(p.name)
                print(f"{p.name:40} " + ("sem avaliação" if not r else
                                         ("APROVADO nos testes" if r["aprovado"] else "reprovado")))
        elif cmd == "pendentes":
            pend = aprovacao.pendentes()
            if not pend:
                print("Nenhum pedido pendente.")
            for p in pend:
                print(f"\n=== {p['id']} | {p['tipo']} {p['nome']} v{p['versao']} | {p['criado']}")
                print(p["relatorio"])
                print(f"Para aprovar: ultron evolucao aprovar {p['id']} [N1|N2|N3]")
        elif cmd == "aprovar":
            nivel = args[1] if len(args) > 1 else "N2"
            p = aprovacao.aprovar(args[0], nivel, por="usuário (CLI)")
            print(f"Aprovado e ativado: {p['tipo']} {p['nome']} v{p['versao']} (nível {nivel}). "
                  "Reinicie o Ultron para carregar.")
        elif cmd == "rejeitar":
            aprovacao.rejeitar(args[0], " ".join(args[1:]), por="usuário (CLI)")
            print("Rejeitado.")
        elif cmd == "avaliar":
            from pathlib import Path
            pasta = Path(args[0])
            if (pasta / "SKILL.md").exists():
                r = avaliacao.avaliar_skill(pasta)
            elif (pasta / "plugin.yaml").exists() or (pasta / "package.json").exists():
                r = avaliacao.avaliar_mcp(pasta)
            else:
                r = avaliacao.avaliar_extensao(pasta)
            print(avaliacao.relatorio(r))
            if r["aprovado"] and "--pedir" in args:
                print("Pedido:", aprovacao.solicitar(r, pasta))
        elif cmd == "desativar":
            extensoes.desativar(args[0]); print("Desativada.")
        elif cmd == "reativar":
            extensoes.reativar(args[0]); print("Reativada.")
        elif cmd == "desinstalar":
            extensoes.desinstalar(args[0]); print("Desinstalada (versões antigas guardadas).")
        elif cmd == "rollback":
            extensoes.rollback(args[0], args[1] if len(args) > 1 else None); print("Rollback feito.")
        elif cmd == "versoes":
            print(", ".join(extensoes.versoes(args[0])) or "nenhuma")
        elif cmd == "remover-skill":
            skills.remover(args[0]); print("Skill removida.")
        elif cmd == "historico":
            for h in base.historico(int(args[0]) if args else 30):
                print(f"{h['quando']} {h['evento']:22} {h.get('nome', '')} {h.get('versao', '') or ''} "
                      f"{h.get('resumo', '') or ''}")
        elif cmd == "diagnostico":
            for a in descoberta.diagnostico():
                print(f"[{a['fonte']}/{a['nivel']}] {a['origem']}: {a['problema']} (x{a['vezes']}) → {a['sugestao']}")
        elif cmd in ("centro", "forja"):
            from evolucao import forja
            return forja.abrir()
        elif cmd == "centro-classico":
            from evolucao import centro
            return centro.abrir()
        else:
            print(f"Comando desconhecido: {cmd}\n{__doc__}")
            return 2
    except (KeyError, IndexError) as e:
        print(f"Faltou argumento ou não existe: {e}")
        return 2
    except Exception as e:
        print(f"Erro: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
