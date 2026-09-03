"""
Checagem de prontidão pra trocar de ciclo (ex.: ele2022 -> ele2026).

Roda ANTES do dia da eleição (recomendado: começar uns 7-10 dias antes,
repetir a cada dia) — não espera o dia em si pra descobrir que o TSE
ainda não publicou o pleito geral. Não muda nada no projeto, só consulta
o catálogo ao vivo do TSE e diz se `obter_eleicoes()` vai funcionar.

Uso:
    python verificar_ciclo.py ele2026
"""

from __future__ import annotations

import sys

# Console do Windows costuma abrir em cp1252, que não tem os emojis usados
# abaixo — sem isso o script quebra com UnicodeEncodeError antes de mostrar
# qualquer resultado, exatamente no dia em que teria que funcionar sem drama.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import tse_api


def verificar(ciclo: str) -> bool:
    print(f"Consultando o catálogo ao vivo do TSE pro ciclo {ciclo!r}...\n")
    try:
        eleicoes = tse_api.obter_eleicoes(ciclo)
    except RuntimeError as e:
        print("❌ AINDA NÃO ESTÁ PRONTO\n")
        print(str(e))
        return False

    print("✅ PRONTO — os 5 cargos foram encontrados:\n")
    for nome, cod in tse_api.CARGOS.items():
        turnos = eleicoes[cod]
        turno2 = f", 2º turno: {turnos[2]}" if turnos.get(2) else " (sem 2º turno)"
        print(f"  {nome:<20} 1º turno: {turnos[1]}{turno2}")
    print(f"\nPode editar CICLO = {ciclo!r} em tse_api.py.")
    return True


if __name__ == "__main__":
    ciclo_alvo = sys.argv[1] if len(sys.argv) > 1 else "ele2026"
    ok = verificar(ciclo_alvo)
    sys.exit(0 if ok else 1)
