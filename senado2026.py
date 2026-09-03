"""
Painel do Senado 2026 — candidaturas registradas na Justiça Eleitoral pro
ciclo 2026 (fonte: planilha "Candidaturas 2026" da Eixo, aba
"coligacoes_governador" — mesma aba do link gid=1814194065 passado pelo
time, que apesar do nome também carrega candidaturas de SENADOR e
PRESIDENTE), mais os 27 mandatos que já estão garantidos até 2031
(eleitos em 2022, não voltam a disputar agora) — aba "27 Senadores
mandato 2031" da planilha de gid=729199560.

IMPORTANTE — isto NÃO é apuração de voto:

- Em 2026-09 a eleição ainda não aconteceu (urnas abrem só em
  outubro/2026), e o painel de apuração ao vivo deste projeto só está
  ligado ao ciclo 2022 (CICLO em tse_api.py) — não existe nenhum sinal de
  quem está ganhando o Senado 2026 disponível hoje.
- "situacao" == "Deferido" aqui é a Justiça Eleitoral liberando a chapa
  pra CONCORRER, não um resultado de urna. Nunca trate como "eleito".
- Cada UF elege 2 cadeiras em 2026 (renovação de 2/3, ao contrário de
  2022 que renovou 1/3) — por isso 27 UFs x 2 = 54 cadeiras em disputa.
"""

from __future__ import annotations

import pandas as pd

from clientes import CampoNaoEncontrado, baixar_planilha, buscar_aba

PLANILHA_CANDIDATURAS_ID = "1Vo-2oa11JpPaYC051Z0UYNR1yJZdhYW4RJeylHfX-bA"
ABA_CANDIDATURAS = "coligacoes_governador"

PLANILHA_CARGO_ID = "1PxKVZeBIyJ5bCKhmyjSvvQNK8I0igGiy5qWxa512Qu8"
ABA_SENADORES_2031 = "27 Senadores mandato 2031"

TOTAL_UFS = 27
CADEIRAS_POR_UF_2026 = 2
CADEIRAS_EM_DISPUTA = TOTAL_UFS * CADEIRAS_POR_UF_2026  # 54
CADEIRAS_GARANTIDAS_2031 = 27
TOTAL_CADEIRAS_SENADO = CADEIRAS_GARANTIDAS_2031 + CADEIRAS_EM_DISPUTA  # 81

# Situações de candidatura que já saíram de "aguardando julgamento" — ou
# seja, a Justiça Eleitoral já bateu o martelo (positivo ou negativo).
# NÃO confundir com "eleito": só diz que o processo de registro terminou.
SITUACOES_JULGADAS = {
    "Deferido",
    "Indeferido",
    "Renúncia",
    "Indeferido em prazo recursal ou com recurso",
}

_CAMPOS_CANDIDATURAS = {
    "ano": ["ano"],
    "uf": ["uf"],
    "cargo": ["cargo"],
    "candidato": ["candidato"],
    "partido_candidato": ["partido_candidato"],
    "nome_coligacao": ["nome_coligacao"],
    "quantidade_partidos": ["quantidade_partidos"],
    "tipo_chapa": ["tipo_chapa"],
    "situacao": ["situacao"],
}

_CAMPOS_SENADORES_2031 = {
    "mandato": ["Mandato"],
    "uf": ["UF"],
    "partido_atual": ["Partido atual"],
    "senador_exercicio": ["Senador(a) em exercício"],
    "situacao_eleitoral_2026": ["Situação eleitoral em 2026"],
}


def _indice(cabecalho: tuple, mapa: dict[str, list[str]]) -> dict[str, int]:
    """Mesma lógica tolerante a rename de clientes.indice_campos(), só que
    contra o dicionário de campos local (planilhas diferentes, cabeçalhos
    diferentes — não faz sentido reaproveitar o CAMPOS de clientes.py)."""
    limpo = [(str(c).strip() if c is not None else "") for c in cabecalho]
    resultado: dict[str, int] = {}
    faltando = []
    for campo, aceitos in mapa.items():
        idx = next((i for i, h in enumerate(limpo) if h in aceitos), None)
        if idx is None:
            faltando.append(campo)
        else:
            resultado[campo] = idx
    if faltando:
        raise CampoNaoEncontrado(
            f"Cabeçalho da planilha mudou: não achei coluna pra {faltando} "
            f"(nomes aceitos hoje: {[mapa[c] for c in faltando]}). "
            f"Cabeçalho real agora: {limpo}."
        )
    return resultado


def carregar_candidaturas_senado_2026() -> pd.DataFrame:
    """
    Uma linha por candidatura a Senador no ciclo 2026 (titular da chapa).
    Colunas: uf, candidato, partido_candidato, nome_coligacao,
    quantidade_partidos, tipo_chapa, situacao.
    """
    wb = baixar_planilha(PLANILHA_CANDIDATURAS_ID)
    try:
        linhas = buscar_aba(wb, ABA_CANDIDATURAS)
    finally:
        wb.close()

    cabecalho, *dados = linhas
    idx = _indice(tuple(cabecalho), _CAMPOS_CANDIDATURAS)

    registros = []
    for row in dados:
        def campo(chave):
            i = idx[chave]
            return row[i] if i < len(row) else ""

        if campo("cargo") != "SENADOR" or str(campo("ano")) != "2026":
            continue
        registros.append({c: campo(c) for c in _CAMPOS_CANDIDATURAS})

    df = pd.DataFrame(registros, columns=list(_CAMPOS_CANDIDATURAS))
    if not df.empty:
        df["quantidade_partidos"] = pd.to_numeric(df["quantidade_partidos"], errors="coerce")
    return df


def carregar_senadores_2031() -> pd.DataFrame:
    """Uma linha por UF — os 27 senadores eleitos em 2022, mandato até 2031."""
    wb = baixar_planilha(PLANILHA_CARGO_ID)
    try:
        linhas = buscar_aba(wb, ABA_SENADORES_2031)
    finally:
        wb.close()

    cabecalho, *dados = linhas
    idx = _indice(tuple(cabecalho), _CAMPOS_SENADORES_2031)

    registros = []
    for row in dados:
        def campo(chave):
            i = idx[chave]
            return row[i] if i < len(row) else ""

        if not campo("uf"):
            continue
        registros.append({c: campo(c) for c in _CAMPOS_SENADORES_2031})

    return pd.DataFrame(registros, columns=list(_CAMPOS_SENADORES_2031))


def resumo_julgamento(df_candidaturas: pd.DataFrame) -> dict:
    """
    Progresso do JULGAMENTO das candidaturas (não de quem vence) — quantas
    das candidaturas ao Senado 2026 já saíram de "aguardando julgamento".
    Ver aviso no topo do módulo: nunca leia isto como projeção de vitória.
    """
    total = len(df_candidaturas)
    if total == 0:
        return {"julgadas": 0, "total": 0, "pct": 0.0}
    julgadas = int(df_candidaturas["situacao"].isin(SITUACOES_JULGADAS).sum())
    return {"julgadas": julgadas, "total": total, "pct": julgadas / total}


def placar_por_partido(df_candidaturas: pd.DataFrame) -> pd.DataFrame:
    """
    Quantas candidaturas ao Senado 2026 cada partido do titular registrou,
    e em quantas UFs distintas — "por partido isolado" de propósito (ver
    docstring do módulo: a coluna de coligação tem MAIS nomes distintos
    que a de partido nesta planilha, então agrupar por coligação
    fragmentaria ainda mais, não menos).
    """
    if df_candidaturas.empty:
        return pd.DataFrame(columns=["partido_candidato", "candidaturas", "n_ufs"])
    g = (
        df_candidaturas.groupby("partido_candidato")
        .agg(candidaturas=("uf", "size"), n_ufs=("uf", "nunique"))
        .reset_index()
        .sort_values("candidaturas", ascending=False)
    )
    return g
