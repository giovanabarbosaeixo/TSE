"""
Cliente para os arquivos JSON públicos de apuração do TSE
(resultados.tse.jus.br). Sem chave, sem cadastro — são os mesmos
arquivos estáticos que os portais de notícia leem no dia da eleição.

Descoberta feita em 2022-08 conferindo os arquivos manualmente:

- Presidente concorre numa eleição FEDERAL: código 544 (1º turno) e
  545 (2º turno). Abrangência "br" (nacional) ou uma UF específica.
- Governador e Senador concorrem numa eleição ESTADUAL diferente,
  mesmo acontecendo no mesmo domingo: código 546 (1º turno).
  Governador tem 2º turno (547) só nos estados que não decidiram no
  1º turno; Senador nunca tem 2º turno (o mandato é decidido em turno
  único, por maioria simples ou pelas duas vagas mais votadas).
- O código de cargo (0001/0003/0005) é o mesmo em qualquer eleição —
  confirmado pelo campo "carper" de cada arquivo.
"""

from __future__ import annotations

import concurrent.futures
import html

import pandas as pd
import requests

CICLO = "ele2022"

CARGOS = {
    "Presidente": "0001",
    "Governador": "0003",
    "Senador": "0005",
}

# cargo -> {turno: código da eleição, ou None se o turno não existe}
ELEICOES = {
    "0001": {1: "544", 2: "545"},
    "0003": {1: "546", 2: "547"},
    "0005": {1: "546", 2: None},
}

UFS_ESTADUAIS = [
    "ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg",
    "ms", "mt", "pa", "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr",
    "rs", "sc", "se", "sp", "to",
]

# Presidente também pode ser consultado nacionalmente ("br") ou pelo
# voto no exterior ("zz"), além de cada UF.
UFS_PRESIDENTE = ["br"] + UFS_ESTADUAIS + ["zz"]

# Código de área do IBGE (usado no GeoJSON de malha estadual) -> sigla da UF.
# Tabela oficial e estável, usada em qualquer sistema público que precise
# cruzar malha territorial do IBGE com sigla de UF.
IBGE_CODAREA_UF = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA",
    "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
    "41": "PR", "42": "SC", "43": "RS",
    "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PainelTSE/1.0)"}


def _cargo_codigo(cargo: str) -> str:
    """Aceita tanto o nome amigável ('Presidente') quanto o código ('0001')."""
    if cargo in CARGOS:
        return CARGOS[cargo]
    if cargo in CARGOS.values():
        return cargo
    raise ValueError(f"Cargo desconhecido: {cargo!r}")


def parse_numero_br(valor) -> float:
    """
    Converte um número no formato do TSE ('1.234.567' ou '48,43') para float.

    Todo número nesses arquivos vem como texto; alguns campos usam ponto de
    milhar, e o separador decimal é sempre vírgula. Nunca some/subtraia os
    campos crus sem passar por aqui.
    """
    if valor is None:
        return 0.0
    texto = str(valor).strip()
    if not texto:
        return 0.0
    return float(texto.replace(".", "").replace(",", "."))


def _texto(valor) -> str:
    """
    Limpa um campo de texto do TSE.

    Os JSONs do TSE trazem nomes/coligações já com entidades HTML cruas
    (ex.: a string literal é "FELIPE D&apos;AVILA", não "FELIPE D'AVILA"),
    então sem isso os apelidos com acento/apóstrofo aparecem errados na tela.
    """
    if valor is None:
        return ""
    return html.unescape(str(valor)).strip()


def montar_url(cargo: str, uf: str, turno: int) -> str:
    cargo_cod = _cargo_codigo(cargo)
    turnos = ELEICOES[cargo_cod]
    if turno not in turnos or turnos[turno] is None:
        raise ValueError(
            f"Cargo {cargo!r} não tem {turno}º turno "
            f"(ex.: Senador é sempre decidido em turno único)."
        )
    eleicao = turnos[turno]
    uf = uf.lower()
    return (
        f"https://resultados.tse.jus.br/oficial/{CICLO}/{eleicao}"
        f"/dados-simplificados/{uf}/{uf}-c{cargo_cod}-e{eleicao.zfill(6)}-r.json"
    )


def buscar_json(cargo: str, uf: str, turno: int, timeout: float = 10) -> dict:
    url = montar_url(cargo, uf, turno)
    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    if resp.status_code == 404:
        raise FileNotFoundError(
            f"Sem arquivo para essa combinação (provavelmente não houve "
            f"esse turno nessa UF/cargo): {url}"
        )
    resp.raise_for_status()
    return resp.json()


def obter_resultado(cargo: str, uf: str, turno: int) -> pd.DataFrame:
    """
    Busca o resultado de `cargo` (nome ou código), na UF `uf`, no `turno`
    indicado, e devolve os candidatos como DataFrame.

    Os totais da apuração (seções totalizadas, comparecimento, abstenção,
    brancos, nulos, votos válidos etc.) vêm junto em `df.attrs["meta"]".
    """
    dados = buscar_json(cargo, uf, turno)

    linhas = []
    for c in dados.get("cand", []):
        linhas.append(
            {
                "numero": c.get("n"),
                "nome": _texto(c.get("nm")),
                "vice": _texto(c.get("nv")),
                "coligacao": _texto(c.get("cc")),
                "votos": int(parse_numero_br(c.get("vap"))),
                # Percentual já calculado pelo TSE sobre VOTOS VÁLIDOS
                # (exclui brancos e nulos) — não é sobre o total de votos.
                "percentual_validos": parse_numero_br(c.get("pvap")),
                # CUIDADO: no 1º turno, "e" vem "s" tanto para quem foi
                # eleito em 1º turno quanto para quem só avançou ao 2º
                # turno. Quem diz o resultado real é "situacao" (texto
                # em "st": "Eleito" / "2º turno" / "Não eleito").
                "avancou_ou_eleito_flag": c.get("e"),
                "situacao": _texto(c.get("st")),
            }
        )

    df = pd.DataFrame(linhas)
    if not df.empty:
        df = df.sort_values("votos", ascending=False).reset_index(drop=True)

    meta = {
        "cargo": cargo,
        "uf": uf.lower(),
        "turno": int(dados.get("t", turno)),
        "data_geracao": dados.get("dg"),
        "hora_geracao": dados.get("hg"),
        "secoes_totalizadas_pct": parse_numero_br(dados.get("pst")),
        # "eleitorado" (e) é o total de eleitores registrados, incluindo os
        # de seções que nunca chegaram a instalar/abrir (esni). Quem casa
        # exatamente com comparecimento + abstenção é "eleitorado_apurado"
        # (ea) — os eleitores das seções que de fato foram apuradas.
        "eleitorado": int(parse_numero_br(dados.get("e"))),
        "eleitorado_apurado": int(parse_numero_br(dados.get("ea"))),
        "eleitorado_secoes_nao_instaladas": int(parse_numero_br(dados.get("esni"))),
        "comparecimento": int(parse_numero_br(dados.get("c"))),
        "comparecimento_pct": parse_numero_br(dados.get("pc")),
        "abstencao": int(parse_numero_br(dados.get("a"))),
        "abstencao_pct": parse_numero_br(dados.get("pa")),
        "votos_validos": int(parse_numero_br(dados.get("vvc"))),
        "votos_validos_pct": parse_numero_br(dados.get("pvvc")),
        "brancos": int(parse_numero_br(dados.get("vb"))),
        "brancos_pct": parse_numero_br(dados.get("pvb")),
        "nulos": int(parse_numero_br(dados.get("tvn"))),
        "nulos_pct": parse_numero_br(dados.get("ptvn")),
    }
    df.attrs["meta"] = meta
    return df


def obter_secoes_totalizadas_por_uf(turno: int, max_workers: int = 12) -> pd.DataFrame:
    """
    Busca, em paralelo, o % de seções totalizadas de Presidente nas 27 UFs —
    usado no mapa de acompanhamento da apuração no dia da eleição.

    Só existe para Presidente: Governador/Senador são eleições próprias por
    UF, então "comparar apuração entre UFs" não faz sentido pra elas (cada
    UF só tem a própria corrida, não dá pra pintar um mapa nacional).

    UFs que falharem (rede, 404 etc.) entram no resultado com percentuais
    None em vez de derrubar o mapa inteiro.
    """

    def _buscar_uf(uf: str) -> dict:
        try:
            dados = buscar_json("0001", uf, turno)
            return {
                "uf": uf.upper(),
                "secoes_totalizadas_pct": parse_numero_br(dados.get("pst")),
                "comparecimento_pct": parse_numero_br(dados.get("pc")),
            }
        except Exception:
            return {"uf": uf.upper(), "secoes_totalizadas_pct": None, "comparecimento_pct": None}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        linhas = list(executor.map(_buscar_uf, UFS_ESTADUAIS))

    return pd.DataFrame(linhas)
