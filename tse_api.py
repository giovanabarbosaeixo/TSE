"""
Cliente para os arquivos JSON públicos de apuração do TSE
(resultados.tse.jus.br). Sem chave, sem cadastro — são os mesmos
arquivos estáticos que os portais de notícia leem no dia da eleição.

Descoberta feita em 2022-08 conferindo os arquivos manualmente:

- Presidente concorre numa eleição FEDERAL: código 544 (1º turno) e
  545 (2º turno). Abrangência "br" (nacional) ou uma UF específica.
- Governador, Senador, Deputado Federal e Deputado Estadual concorrem
  na mesma eleição ESTADUAL (código 546, 1º turno), mesmo sendo cargos
  de níveis diferentes — é o pleito que corre por UF. Governador tem
  2º turno (547) só nos estados que não decidiram no 1º turno; os
  outros três nunca têm 2º turno.
- Deputado Federal e Estadual são cargos PROPORCIONAIS: o candidato
  só é eleito se o partido/coligação atingir o quociente eleitoral,
  não basta ter mais votos que os concorrentes. Por isso "situacao"
  usa valores diferentes dos cargos majoritários: "Eleito por QP"
  (quociente partidário), "Eleito por média" (sobras via média),
  "Suplente" e "Não eleito" — nunca aparece o "Eleito" simples. É
  comum um candidato ter votação alta e mesmo assim não se eleger,
  porque quem fecha conta é a legenda, não o indivíduo.
- O código de cargo (0001/0003/0005/0006/0007) é o mesmo em qualquer
  eleição — confirmado pelo campo "carper" de cada arquivo.
- O campo "tf" ("totalização final") só vira "s" quando o TSE fecha a
  apuração oficial daquele arquivo. Em cargos proporcionais isso pode
  ficar "n" mesmo com "pst" (seções totalizadas) em 100% — o resultado
  final de quem se elege depende do cálculo do quociente com TODAS as
  seções já contadas, e esse cálculo/validação leva mais tempo que só
  somar votos. Enquanto "tf" != "s", trate o resultado como parcial.
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
    "Deputado Federal": "0006",
    "Deputado Estadual": "0007",
}

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PainelTSE/1.0)"}

# Descrição de cargo usada pra casar com o campo "ds" (nome do cargo) do
# catálogo de eleições vigentes do TSE — ver descobrir_eleicoes().
_DESCRICOES_CARGO = {
    "0001": "presidente",
    "0003": "governador",
    "0005": "senador",
    "0006": "deputado federal",
    "0007": "deputado estadual",
}

# Cache dos códigos de eleição de ciclos já encerrados, confirmados
# manualmente contra os arquivos reais do TSE (ele2022: descoberto em
# 2022-08 e revalidado direto na API em 2026-09). Só é consultado quando
# descobrir_eleicoes() não acha o ciclo pedido — o catálogo ao vivo do TSE
# cobre só uma janela de tempo (pleitos recentes/vigentes), então um ciclo
# mais velho some dele. Isto NÃO é a fonte de verdade, é o que sobra
# depois que a fonte de verdade (a API) já não tem mais o dado.
_ELEICOES_CACHE_HISTORICO = {
    "ele2022": {
        "0001": {1: "544", 2: "545"},
        "0003": {1: "546", 2: "547"},
        "0005": {1: "546", 2: None},
        "0006": {1: "546", 2: None},
        "0007": {1: "546", 2: None},
    },
}


def descobrir_eleicoes(ciclo: str) -> dict:
    """
    Descobre ao vivo, na configuração pública do TSE, os códigos de eleição
    de cada cargo pro `ciclo` pedido (ex.: "ele2022") — em vez de hardcodar
    números que mudam a cada pleito (544/546 em 2022 vão ser outros em
    2026; "em 4 de outubro a troca é de uma linha" só funciona se ninguém
    tiver que caçar o número novo à mão).

    Consulta oficial/comum/config/ele-c.json, o catálogo de pleitos que o
    próprio site oficial usa pra montar a navegação. Cada pleito ("pl")
    tem uma ou mais "eleições" ("e") — uma por nível (federal, estadual),
    não por cargo — cada uma com o código usado nas URLs de resultado
    ("cd" pro 1º turno, "cdt2" pro 2º turno quando existe) e a lista de
    cargos que ela cobre (dentro de "abr" -> "cp" -> "ds").

    IMPORTANTE: essa listagem só cobre uma janela de tempo — na prática,
    uns 2 anos a partir da data da eleição. Um ciclo mais velho que isso
    não aparece mais aqui, e a função devolve {}; quem chama
    (obter_eleicoes) cai pro cache histórico nesse caso.
    """
    ano = ciclo.replace("ele", "")
    try:
        resp = requests.get(
            "https://resultados.tse.jus.br/oficial/comum/config/ele-c.json",
            headers=_HEADERS, timeout=8,
        )
        resp.raise_for_status()
        catalogo = resp.json()
    except requests.RequestException:
        return {}

    encontrados: dict = {}
    for pleito in catalogo.get("pl", []):
        if pleito.get("dt", "")[-4:] != ano:
            continue
        for eleicao in pleito.get("e", []):
            turno2 = eleicao.get("cdt2") or None
            for abrangencia in eleicao.get("abr", []):
                for cargo in abrangencia.get("cp", []):
                    # Comparação EXATA, não "contém": "ds" também é usado pra
                    # texto de Consulta Popular (uma pergunta inteira), e uma
                    # pergunta sobre a cidade "Governador Edison Lobão" bate
                    # com "governador" em substring — achado testando contra
                    # o catálogo ao vivo. cp["tp"] "1"/"2" (majoritário/
                    # proporcional) filtra o mesmo problema por outro lado.
                    ds = str(cargo.get("ds") or "").strip().lower()
                    if cargo.get("tp") not in ("1", "2"):
                        continue
                    for cod, alvo in _DESCRICOES_CARGO.items():
                        if cod not in encontrados and ds == alvo:
                            encontrados[cod] = {1: eleicao["cd"], 2: turno2}
    return encontrados


def obter_eleicoes(ciclo: str) -> dict:
    """cargo -> {turno: código da eleição, ou None se o turno não existe}."""
    if ciclo in _ELEICOES_CACHE_HISTORICO:
        return _ELEICOES_CACHE_HISTORICO[ciclo]
    encontrados = descobrir_eleicoes(ciclo)
    faltando = [nome for nome, cod in CARGOS.items() if cod not in encontrados]
    if faltando:
        # NÃO basta checar "achei algo" — em 2026-09, o catálogo ao vivo já
        # tinha uma entrada de "Governador" pro ano, mas era da eleição
        # SUPLEMENTAR de Roraima (pleito de 21/06/2026, já encerrada), não
        # do pleito geral de outubro: mesmo código de cargo, eleição
        # completamente diferente. Se aceitássemos qualquer resultado não
        # vazio, o painel teria apontado silenciosamente pra essa eleição
        # errada em vez de travar com um erro claro. Por isso exige os 5
        # cargos batendo, não só "não veio vazio".
        raise RuntimeError(
            f"Catálogo ao vivo do TSE pro ciclo {ciclo!r} não tem todos os "
            f"cargos ainda — faltam: {faltando}. Isso é esperado se o TSE "
            f"ainda não publicou o pleito geral deste ciclo (costuma sair "
            f"só perto da eleição), OU se o catálogo hoje só tem eleições "
            f"suplementares/municipais que usam os mesmos códigos de cargo "
            f"mas são pleitos completamente diferentes do geral — já "
            f"aconteceu (set/2026: só 'Governador', da suplementar de RR, "
            f"sem Presidente/Senador/Deputados). Se esse ciclo já rodou, "
            f"confirme os códigos manualmente e adicione em "
            f"_ELEICOES_CACHE_HISTORICO; se é um ciclo futuro, espere o TSE "
            f"publicar o pleito geral e tente de novo mais perto da eleição."
        )
    return encontrados


ELEICOES = obter_eleicoes(CICLO)

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


# O Senado alterna renovação de 1/3 (1 vaga por UF — ex.: 2022) e 2/3 (2
# vagas por UF — ex.: 2018, 2026) a cada 4 anos. 2018 é o ano-base de uma
# renovação de 2/3 (confirmado: a planilha de mandatos mostra os 27
# senadores eleitos em 2022 com mandato até 2031, ou seja, 2022 foi 1/3 —
# logo 2018 e 2026, 4 anos antes/depois, são 2/3). Regra fixa da Câmara
# Alta, não precisa reconferir a cada ciclo nem hardcodar por CICLO.
_ANO_BASE_RENOVACAO_DOIS_TERCOS = 2018


def vagas_senado_por_uf(ciclo: str) -> int:
    """1 ou 2 — quantas vagas de Senador cada UF elege no `ciclo` pedido."""
    ano = int(ciclo.replace("ele", ""))
    return 2 if (ano - _ANO_BASE_RENOVACAO_DOIS_TERCOS) % 8 == 0 else 1


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
                # em "st": "Eleito" / "2º turno" / "Não eleito"). Validado
                # com Governador SP, 1º turno 2022: Tarcísio tem e="s" e
                # st="2º turno" — lendo só "e" ele apareceria eleito em
                # outubro, o que é falso. Nunca decidir status por "e".
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
        # "tf" ("totalização final") só fecha em "s" quando o TSE oficializa
        # o resultado daquele arquivo. Pode continuar "n" mesmo com 100% das
        # seções totalizadas — sobretudo em cargos proporcionais, onde quem
        # se elege depende do cálculo do quociente eleitoral, não só da
        # contagem de votos. Enquanto isso, o resultado é parcial.
        "totalizacao_final": dados.get("tf") == "s",
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


# Região de cada UF — usada só na análise pós-eleição (votação média por
# região, agrupamento de estados). Divisão oficial do IBGE, não muda.
REGIOES_UF = {
    "ac": "Norte", "ap": "Norte", "am": "Norte", "pa": "Norte", "ro": "Norte",
    "rr": "Norte", "to": "Norte",
    "al": "Nordeste", "ba": "Nordeste", "ce": "Nordeste", "ma": "Nordeste",
    "pb": "Nordeste", "pe": "Nordeste", "pi": "Nordeste", "rn": "Nordeste",
    "se": "Nordeste",
    "df": "Centro-Oeste", "go": "Centro-Oeste", "mt": "Centro-Oeste", "ms": "Centro-Oeste",
    "es": "Sudeste", "mg": "Sudeste", "rj": "Sudeste", "sp": "Sudeste",
    "pr": "Sul", "rs": "Sul", "sc": "Sul",
}


def obter_resumo_presidente_por_uf(turno: int, max_workers: int = 12) -> pd.DataFrame:
    """
    Busca, em paralelo, o resultado de Presidente nas 27 UFs e devolve só o
    resumo por estado (1º e 2º colocados, margem, abstenção) — usado na
    análise pós-eleição (mapa de vencedor, margem de vitória, votação por
    região).

    UFs que falharem entram com campos None em vez de derrubar a análise.
    """

    def _buscar_uf(uf: str) -> dict:
        base = {
            "uf": uf.upper(),
            "regiao": REGIOES_UF.get(uf, ""),
            "vencedor": None,
            "vencedor_coligacao": None,
            "vencedor_pct": None,
            "segundo_nome": None,
            "segundo_coligacao": None,
            "segundo_pct": None,
            "margem_pct": None,
            "abstencao_pct": None,
            "comparecimento_pct": None,
        }
        try:
            df = obter_resultado("0001", uf, turno)
            if df.empty:
                return base
            meta = df.attrs["meta"]
            primeiro = df.iloc[0]
            base.update(
                vencedor=primeiro["nome"],
                vencedor_coligacao=primeiro["coligacao"],
                vencedor_pct=float(primeiro["percentual_validos"]),
                abstencao_pct=meta["abstencao_pct"],
                comparecimento_pct=meta["comparecimento_pct"],
            )
            if len(df) > 1:
                segundo = df.iloc[1]
                base.update(
                    segundo_nome=segundo["nome"],
                    segundo_coligacao=segundo["coligacao"],
                    segundo_pct=float(segundo["percentual_validos"]),
                    margem_pct=float(primeiro["percentual_validos"]) - float(segundo["percentual_validos"]),
                )
            else:
                base["margem_pct"] = float(primeiro["percentual_validos"])
            return base
        except Exception:
            return base

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        linhas = list(executor.map(_buscar_uf, UFS_ESTADUAIS))

    return pd.DataFrame(linhas)


def obter_resumo_senador_por_uf(max_workers: int = 12) -> pd.DataFrame:
    """
    Busca, em paralelo, o resultado de Senador (turno único — o cargo nunca
    tem 2º turno) nas 27 UFs e devolve o resumo por estado — usado na
    análise pós-eleição.

    NÃO hardcoda "1 vencedor por UF": o Senado elege 1 vaga por UF em
    ciclos de renovação de 1/3 (ex.: 2022) e 2 vagas por UF em ciclos de
    2/3 (ex.: 2018, 2026 — ver vagas_senado_por_uf()). Quem diz quantos
    venceram em cada UF é a própria contagem de candidatos com
    situacao == "Eleito" no arquivo do TSE, nunca um número fixo aqui —
    então esta função funciona nos dois tipos de ciclo sem precisar de
    ajuste. Devolve até 2 eleitos (o máximo hoje possível); um ciclo que
    mudasse essa regra precisaria revisar isto.

    "margem_pct" NÃO é mais "1º menos 2º colocado" (isso não faz sentido
    num ciclo de 2 vagas: o 2º colocado também venceu) — é a distância
    entre a ÚLTIMA vaga preenchida e o primeiro candidato que ficou de
    fora ("quase lá"). Em ciclo de 1 vaga isso dá exatamente o mesmo
    número de antes (1º menos 2º), só que com o nome certo.

    UFs que falharem entram com campos None em vez de derrubar a análise.
    """

    def _buscar_uf(uf: str) -> dict:
        base = {
            "uf": uf.upper(),
            "regiao": REGIOES_UF.get(uf, ""),
            "vagas": None,
            "eleito1_nome": None,
            "eleito1_coligacao": None,
            "eleito1_pct": None,
            "eleito2_nome": None,
            "eleito2_coligacao": None,
            "eleito2_pct": None,
            "proximo_nome": None,
            "proximo_coligacao": None,
            "proximo_pct": None,
            "margem_pct": None,
            "abstencao_pct": None,
            "comparecimento_pct": None,
        }
        try:
            df = obter_resultado("0005", uf, 1)
            if df.empty:
                return base
            meta = df.attrs["meta"]
            base.update(abstencao_pct=meta["abstencao_pct"], comparecimento_pct=meta["comparecimento_pct"])

            eleitos = df[df["situacao"] == "Eleito"]
            base["vagas"] = len(eleitos)
            ultima_vaga_pct = None
            if len(eleitos) >= 1:
                e1 = eleitos.iloc[0]
                ultima_vaga_pct = float(e1["percentual_validos"])
                base.update(
                    eleito1_nome=e1["nome"], eleito1_coligacao=e1["coligacao"], eleito1_pct=ultima_vaga_pct
                )
            if len(eleitos) >= 2:
                e2 = eleitos.iloc[1]
                ultima_vaga_pct = float(e2["percentual_validos"])
                base.update(
                    eleito2_nome=e2["nome"], eleito2_coligacao=e2["coligacao"], eleito2_pct=ultima_vaga_pct
                )

            resto = df[df["situacao"] != "Eleito"]
            if not resto.empty:
                proximo = resto.iloc[0]
                proximo_pct = float(proximo["percentual_validos"])
                base.update(
                    proximo_nome=proximo["nome"], proximo_coligacao=proximo["coligacao"], proximo_pct=proximo_pct
                )
                if ultima_vaga_pct is not None:
                    base["margem_pct"] = ultima_vaga_pct - proximo_pct
            return base
        except Exception:
            return base

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        linhas = list(executor.map(_buscar_uf, UFS_ESTADUAIS))

    return pd.DataFrame(linhas)


def obter_resumo_uf_tabela(cargo_cod: str, turno: int, top_n: int = 3, max_workers: int = 12) -> pd.DataFrame:
    """
    Busca, em paralelo, o resultado de `cargo_cod` (Governador ou Senador —
    Presidente já tem o mapa nacional dedicado) nas 27 UFs e devolve uma
    linha por estado com os `top_n` candidatos mais votados (nome + % de
    votos válidos) e o % de seções totalizadas — a "tabela por estado, uma
    linha cada, com a barra de apuração dentro da linha" estilo Politico.

    Colunas cand{n}_nome / cand{n}_pct / cand{n}_situacao / cand{n}_coligacao
    ficam None quando o estado tem menos de `top_n` candidatos, ou quando a
    UF ainda não respondeu.
    """

    def _buscar_uf(uf: str) -> dict:
        base = {"uf": uf.upper(), "regiao": REGIOES_UF.get(uf, ""), "secoes_totalizadas_pct": None}
        for i in range(1, top_n + 1):
            base[f"cand{i}_nome"] = None
            base[f"cand{i}_pct"] = None
            base[f"cand{i}_situacao"] = None
            base[f"cand{i}_coligacao"] = None
        try:
            df = obter_resultado(cargo_cod, uf, turno)
            if df.empty:
                return base
            base["secoes_totalizadas_pct"] = df.attrs["meta"]["secoes_totalizadas_pct"]
            for i, row in enumerate(df.head(top_n).itertuples(), start=1):
                base[f"cand{i}_nome"] = row.nome
                base[f"cand{i}_pct"] = float(row.percentual_validos)
                base[f"cand{i}_situacao"] = row.situacao
                base[f"cand{i}_coligacao"] = row.coligacao
            return base
        except Exception:
            return base

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        linhas = list(executor.map(_buscar_uf, UFS_ESTADUAIS))

    return pd.DataFrame(linhas)


def obter_resumo_governador_final_por_uf(max_workers: int = 12) -> pd.DataFrame:
    """
    Busca o resultado de Governador nas 27 UFs e resolve, PRA CADA UF, qual
    turno vale: 2º turno se o estado precisou dele e ele já tem dado; senão
    1º turno. Devolve nome, % válidos, coligação e situação do líder desse
    turno final — não só o vencedor (usa obter_decisao_governador() pra
    isso), porque quem consome isso (mapa em grade, lista de governos)
    também precisa do percentual pra mostrar.

    Sem resolver por UF, um painel que sempre olha o MESMO turno pra todos
    os 27 estados de uma vez mostra como "em disputa" um estado que só foi
    decidido no 2º turno — mesmo a eleição já tendo acabado há anos. Cada
    UF pode estar num turno diferente do outro (só quem não teve maioria
    no 1º turno foi pro 2º).
    """

    def _buscar_uf(uf: str) -> dict:
        base = {
            "uf": uf.upper(),
            "turno_final": 1,
            "vencedor": None,
            "vencedor_pct": None,
            "vencedor_coligacao": None,
            "vencedor_situacao": None,
        }
        try:
            df1 = obter_resultado("0003", uf, 1)
            if df1.empty:
                return base
            lider1 = df1.iloc[0]
            base.update(
                vencedor=lider1["nome"],
                vencedor_pct=float(lider1["percentual_validos"]),
                vencedor_coligacao=lider1["coligacao"],
                vencedor_situacao=lider1["situacao"],
            )
            if lider1["situacao"] != "2º turno":
                return base
            try:
                df2 = obter_resultado("0003", uf, 2)
                if not df2.empty:
                    lider2 = df2.iloc[0]
                    base.update(
                        turno_final=2,
                        vencedor=lider2["nome"],
                        vencedor_pct=float(lider2["percentual_validos"]),
                        vencedor_coligacao=lider2["coligacao"],
                        vencedor_situacao=lider2["situacao"],
                    )
            except Exception:
                pass
            return base
        except Exception:
            return base

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        linhas = list(executor.map(_buscar_uf, UFS_ESTADUAIS))

    return pd.DataFrame(linhas)


def obter_decisao_governador(max_workers: int = 12) -> pd.DataFrame:
    """
    Busca, em paralelo, o resultado de Governador (1º turno, e 2º turno onde
    houver) nas 27 UFs e devolve o vencedor final de cada estado + se foi
    decidido ainda no 1º turno — usado na análise pós-eleição.

    `decidido_1o_turno` vem None quando a apuração ainda não definiu nem o
    1º turno (nem "Eleito" nem "2º turno" apareceu pra ninguém ainda).
    """

    def _buscar_uf(uf: str) -> dict:
        base = {
            "uf": uf.upper(),
            "decidido_1o_turno": None,
            "vencedor": None,
            "vencedor_coligacao": None,
        }
        try:
            df1 = obter_resultado("0003", uf, 1)
            if df1.empty:
                return base

            eleitos_1o = df1[df1["situacao"] == "Eleito"]
            if not eleitos_1o.empty:
                v = eleitos_1o.iloc[0]
                base.update(decidido_1o_turno=True, vencedor=v["nome"], vencedor_coligacao=v["coligacao"])
                return base

            foram_2o = df1[df1["situacao"] == "2º turno"]
            if foram_2o.empty:
                return base

            base["decidido_1o_turno"] = False
            try:
                df2 = obter_resultado("0003", uf, 2)
                eleitos_2o = df2[df2["situacao"] == "Eleito"]
                if not eleitos_2o.empty:
                    v = eleitos_2o.iloc[0]
                    base.update(vencedor=v["nome"], vencedor_coligacao=v["coligacao"])
            except Exception:
                pass
            return base
        except Exception:
            return base

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        linhas = list(executor.map(_buscar_uf, UFS_ESTADUAIS))

    return pd.DataFrame(linhas)
