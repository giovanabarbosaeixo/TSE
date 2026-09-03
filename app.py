from __future__ import annotations

import html as _html
import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import clientes
import senado2026
from tse_api import (
    CARGOS,
    CICLO,
    ELEICOES,
    IBGE_CODAREA_UF,
    UFS_ESTADUAIS,
    UFS_PRESIDENTE,
    obter_decisao_governador,
    obter_resultado,
    obter_resumo_governador_final_por_uf,
    obter_resumo_presidente_por_uf,
    obter_resumo_senador_por_uf,
    obter_resumo_uf_tabela,
    obter_secoes_totalizadas_por_uf,
    vagas_senado_por_uf,
)

# ─── Config ──────────────────────────────────────────────────────────────────
st.set_page_config(page_title=f"Apuração TSE · Eleições {CICLO.replace('ele', '')}", layout="wide")

REFRESH_SEGUNDOS = 60
# O mapa faz 27 requisições (uma por UF) a cada atualização, contra 1 do
# resto do painel — refresh mais espaçado pra não multiplicar a carga no
# servidor do TSE sem necessidade.
REFRESH_MAPA_SEGUNDOS = 240
GEOJSON_UF_PATH = "brasil_uf.geojson"

# Mesma paleta/identidade visual do painel Eixo de pesquisas eleitorais.
EIXO = {
    "tinta": "#111111",
    "vinho": "#962E4D",
    "gelo": "#F4F3EF",
    "borda": "#DADAD4",
    "subtexto": "#767672",
    "amarelo": "#E8A600",
    "marinho": "#192D4E",
    "coral": "#B84349",
}
COR_GRAFICO = "#192d4d"


def fmt(n: int) -> str:
    """Formata inteiro com ponto de milhar (padrão BR)."""
    return f"{n:,}".replace(",", ".")


def esc(texto: str) -> str:
    """Escapa texto vindo do TSE antes de embutir em HTML cru."""
    return _html.escape(str(texto or ""))


# ─── CSS ─────────────────────────────────────────────────────────────────────
st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap');
* {{ box-sizing: border-box; }}
[data-testid="stAppViewContainer"] {{ background: {EIXO["gelo"]} !important; }}
.block-container {{ max-width: 1180px !important; padding: 0 2rem 3rem !important; background: {EIXO["gelo"]}; }}
[data-testid="stHeader"] {{ display: none; }}
[data-testid="stDecoration"] {{ display: none; }}
footer {{ display: none !important; }}
#MainMenu {{ display: none !important; }}
body, p, span, div, label, input, select {{ font-family: 'Montserrat', sans-serif !important; }}

[data-testid="stSidebar"] {{ background: {EIXO["gelo"]} !important; border-right: 1px solid {EIXO["borda"]} !important; }}
[data-testid="stSidebar"] * {{ font-family: 'Montserrat', sans-serif !important; font-size: 13px !important; }}

/* Masthead: banner navy cheio, sangrando pra fora do padding do container */
.tse-masthead {{
    background: {EIXO["marinho"]};
    color: #fff;
    padding: 40px 48px;
    margin: 0 -2rem 24px -2rem;
    width: calc(100% + 4rem);
    display: flex; align-items: center; justify-content: space-between;
}}
.tse-masthead-title {{
    font-size: 38px; font-weight: 800; color: #fff; line-height: 1.1;
}}
.tse-masthead-meta {{
    font-size: 12px; color: rgba(255,255,255,0.65); letter-spacing: 0.05em;
    margin-top: 6px; display: block;
}}
.tse-masthead-mark {{
    width: 52px; height: 52px; border: 2px solid rgba(255,255,255,0.55);
    border-radius: 50%; display: flex; align-items: center; justify-content: center;
    font-size: 24px; flex-shrink: 0;
}}
.tse-page-title {{
    font-size: 24px; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; color: {EIXO["tinta"]};
    border-bottom: 1px solid {EIXO["borda"]}; padding-bottom: 14px;
    margin: 20px 0 20px;
}}
/* Abas — cada uma é uma "mini página" (Distribuição / Detalhamento / Mapa) */
[data-testid="stTabs"] [role="tablist"] {{
    border-bottom: 1px solid {EIXO["borda"]} !important; gap: 0 !important;
}}
[data-testid="stTabs"] [role="tab"] {{
    font-size: 11px !important; font-weight: 500 !important; letter-spacing: 0.12em !important;
    text-transform: uppercase !important; color: {EIXO["subtexto"]} !important;
    padding: 10px 20px 9px !important; border-bottom: 2px solid transparent !important;
    background: transparent !important; border-radius: 0 !important;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
    color: {EIXO["marinho"]} !important; border-bottom-color: {EIXO["marinho"]} !important;
}}

/* Candidato líder */
.tse-leader {{
    display: grid; grid-template-columns: 1fr auto; align-items: center;
    gap: 18px; padding: 18px 20px; background: #fff;
    border: 1px solid {EIXO["borda"]}; border-left: 4px solid {EIXO["vinho"]};
}}
.tse-leader-num {{ font-size: 11px; color: {EIXO["subtexto"]}; letter-spacing: 0.08em; text-transform: uppercase; }}
.tse-leader-name {{ font-size: 20px; font-weight: 800; color: {EIXO["tinta"]}; margin: 2px 0 4px; }}
.tse-leader-cc {{ font-size: 11.5px; color: {EIXO["subtexto"]}; line-height: 1.5; max-width: 640px; }}
.tse-leader-pct-label {{
    font-size: 10px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    color: {EIXO["subtexto"]}; text-align: right;
}}
.tse-leader-pct {{ font-size: 34px; font-weight: 800; color: {EIXO["vinho"]}; text-align: right; line-height: 1; }}
.tse-leader-votos {{ font-size: 11px; color: {EIXO["subtexto"]}; text-align: right; margin-top: 4px; }}

/* Faixa de indicadores */
.tse-stat-wrap {{
    display: flex; background: #fff; border: 1px solid {EIXO["borda"]}; margin-top: 10px;
}}
.tse-stat {{ flex: 1; padding: 14px 16px; border-left: 1px solid {EIXO["borda"]}; }}
.tse-stat:first-child {{ border-left: none; }}
.tse-stat-label {{
    font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
    color: {EIXO["subtexto"]}; margin-bottom: 4px;
}}
.tse-stat-value {{ font-size: 20px; font-weight: 800; color: {EIXO["tinta"]}; line-height: 1; }}
.tse-stat-sub {{ font-size: 10.5px; color: {EIXO["subtexto"]}; margin-top: 4px; }}

/* Tabela de candidatos */
.tse-snap-wrap {{ width: 100%; background: #fff; border: 1px solid {EIXO["borda"]}; overflow: hidden; margin-top: 10px; }}
.tse-snap-table {{ width: 100%; border-collapse: collapse; }}
.tse-snap-table thead th {{
    background: {EIXO["marinho"]}; color: #fff;
    font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
    padding: 11px 16px; text-align: left;
}}
.tse-snap-table thead th.tse-num {{ text-align: right; }}
.tse-snap-table tbody tr {{ border-bottom: 1px solid {EIXO["borda"]}; }}
.tse-snap-table tbody tr:last-child {{ border-bottom: none; }}
.tse-snap-table tbody tr:hover {{ background: {EIXO["gelo"]}; }}
.tse-snap-table tbody td {{ padding: 11px 16px; font-size: 12.5px; color: {EIXO["tinta"]}; vertical-align: middle; }}
.tse-snap-table tbody td.tse-num {{ text-align: right; font-weight: 700; }}
.tse-snap-cand {{ font-weight: 700; color: {EIXO["marinho"]}; }}
.tse-snap-sub {{ font-size: 11px; color: {EIXO["subtexto"]}; margin-top: 2px; }}
.tse-badge {{
    display: inline-block; font-size: 9px; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; padding: 2px 7px; border-radius: 2px; margin-left: 6px; vertical-align: middle;
}}
.tse-badge-eleito     {{ background: #d4edda; color: #1a5c2e; }}
.tse-badge-2turno     {{ background: #fff3cd; color: #856404; }}
.tse-badge-suplente   {{ background: #dbe4f0; color: #1f3864; }}
.tse-badge-naoeleito  {{ background: {EIXO["borda"]}; color: {EIXO["subtexto"]}; }}
.tse-badge-cliente {{
    display: inline-block; font-size: 9px; font-weight: 700; letter-spacing: 0.04em;
    padding: 2px 7px; border-radius: 2px; margin: 0 4px 2px 0; vertical-align: middle;
    background: {EIXO["amarelo"]}; color: #4a3300;
}}

/* Tabela por estado (uma linha por UF, barra de apuração embutida) */
.tse-uf-table td, .tse-uf-table th {{ vertical-align: middle; }}
.tse-uf-cands {{ display: flex; flex-direction: column; gap: 3px; }}
.tse-uf-cand {{ display: flex; align-items: baseline; gap: 6px; font-size: 12px; white-space: nowrap; }}
.tse-uf-dot {{ width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; display: inline-block; }}
.tse-uf-cand-nome {{ color: {EIXO["tinta"]}; overflow: hidden; text-overflow: ellipsis; }}
/* tabular-nums: dígitos com largura fixa, senão a casa decimal "dança" a
   cada refresh (49.2% -> 49.8% desloca o texto se as fontes forem
   proporcionais). Largura mínima fixa: sem isso a coluna pula de lugar
   quando o percentual passa de 9,9% (1 dígito) pra 10,0% (2 dígitos). */
.tse-tabnum {{
    font-variant-numeric: tabular-nums; font-weight: 700;
    display: inline-block; min-width: 42px; text-align: right;
}}
.tse-uf-apuracao {{ font-variant-numeric: tabular-nums; display: inline-block; min-width: 48px; text-align: right; }}
.tse-uf-bar-wrap {{
    display: flex; height: 10px; width: 100%; min-width: 120px;
    background: {EIXO["borda"]}; border-radius: 2px; overflow: hidden;
}}
.tse-uf-bar-seg {{ height: 100%; }}
.tse-uf-bar-seg:first-child {{ border-radius: 2px 0 0 2px; }}

/* Roteiro pós-eleição */
.tse-pos-intro {{
    font-size: 12.5px; color: {EIXO["subtexto"]}; line-height: 1.6;
    background: #fff; border: 1px solid {EIXO["borda"]}; border-left: 4px solid {EIXO["amarelo"]};
    padding: 14px 18px; margin: 4px 0 18px;
}}
.tse-pos-cat {{
    font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    color: #fff; background: {EIXO["marinho"]}; padding: 9px 16px; margin-top: 18px;
}}
.tse-pos-list {{ background: #fff; border: 1px solid {EIXO["borda"]}; border-top: none; margin: 0; padding: 0; list-style: none; }}
.tse-pos-list li {{
    padding: 12px 16px; border-bottom: 1px solid {EIXO["borda"]};
    font-size: 13px; color: {EIXO["tinta"]}; line-height: 1.5; display: flex; gap: 10px;
}}
.tse-pos-list li:last-child {{ border-bottom: none; }}
.tse-pos-num {{ color: {EIXO["vinho"]}; font-weight: 800; flex-shrink: 0; }}

/* Widgets */
[data-testid="stSelectbox"] label, [data-testid="stRadio"] label {{
    font-size: 11px !important; font-weight: 700 !important;
    letter-spacing: 0.14em !important; text-transform: uppercase !important;
    color: {EIXO["subtexto"]} !important;
}}
[data-testid="stSelectbox"] > div > div {{
    border: 1px solid {EIXO["borda"]} !important; border-radius: 0 !important;
    background: #fff !important; font-size: 15px !important; min-height: 42px !important;
}}
[data-testid="stSidebar"] hr {{ border-color: {EIXO["borda"]}; }}

/* Navegação principal na sidebar — st.radio disfarçado de lista de menu
   (Início / Disputa.../ Planos de Governo...). É sempre o primeiro
   st.radio da sidebar, por isso :first-of-type — assim não briga com o
   estilo do radio "Turno" nos Filtros, que continua com o visual padrão.
   O "*" zera borda/fundo/sombra em TODO mundo dentro do radiogroup primeiro
   (não dá pra saber se a caixa que sobra vem do label ou de um wrapper do
   BaseWeb em volta dele) — depois as regras mais específicas de baixo
   (maior especificidade: tag + pseudo-classe) reaplicam só o que a gente
   quer, então ganham do reset genérico independente da ordem. */
[data-testid="stSidebar"] [data-testid="stRadio"]:first-of-type [role="radiogroup"] {{
    gap: 1px !important; margin-top: 2px;
}}
[data-testid="stSidebar"] [data-testid="stRadio"]:first-of-type [role="radiogroup"] * {{
    border: none !important; box-shadow: none !important; background: transparent !important;
    outline: none !important;
}}
[data-testid="stSidebar"] [data-testid="stRadio"]:first-of-type label {{
    display: flex !important; align-items: center !important;
    padding: 9px 12px !important; border-radius: 6px !important;
    width: 100% !important; margin: 0 !important;
    font-size: 13.5px !important; font-weight: 600 !important;
    letter-spacing: normal !important; text-transform: none !important;
    color: {EIXO["marinho"]} !important; cursor: pointer;
}}
[data-testid="stSidebar"] [data-testid="stRadio"]:first-of-type label:hover {{
    background: {EIXO["gelo"]} !important;
}}
[data-testid="stSidebar"] [data-testid="stRadio"]:first-of-type label:has(input:checked) {{
    background: {EIXO["borda"]} !important; color: {EIXO["tinta"]} !important; font-weight: 700 !important;
}}
/* esconde a bolinha do radio — o input nativo e qualquer svg/div/span que
   o BaseWeb desenhe como indicador visual por cima dele. */
[data-testid="stSidebar"] [data-testid="stRadio"]:first-of-type label input,
[data-testid="stSidebar"] [data-testid="stRadio"]:first-of-type label svg,
[data-testid="stSidebar"] [data-testid="stRadio"]:first-of-type label > div:first-child,
[data-testid="stSidebar"] [data-testid="stRadio"]:first-of-type label > span:first-child {{
    display: none !important; width: 0 !important; height: 0 !important;
    margin: 0 !important; padding: 0 !important;
}}
</style>""", unsafe_allow_html=True)


st.markdown(f"""
<div class="tse-masthead">
  <div>
    <div class="tse-masthead-title">Apuração TSE</div>
    <span class="tse-masthead-meta">dados oficiais {esc(CICLO)} · cache: {REFRESH_SEGUNDOS}s</span>
  </div>
  <div class="tse-masthead-mark">🗳️</div>
</div>
""", unsafe_allow_html=True)

LOGO_PATH = "logoeixo.png"

# Interesse de clientes muda em ritmo de planilha editada à mão, não de
# apuração — cache bem mais longo (30 min) que o resto do painel evita
# baixar a planilha inteira a cada refresh de 60s sem necessidade.
CARGO_LOGICO_CLIENTES = {"0005": "Senador", "0006": "Deputado Federal", "0007": "Deputado Estadual"}


@st.cache_data(ttl=1800, show_spinner=False)
def carregar_interesses_clientes():
    return clientes.carregar_interesses_clientes()


# Mesmo raciocínio de cache do bloco de clientes acima: candidatura muda em
# ritmo de julgamento/planilha editada à mão, não de apuração ao vivo.
@st.cache_data(ttl=1800, show_spinner=False)
def carregar_candidaturas_senado_2026():
    return senado2026.carregar_candidaturas_senado_2026()


@st.cache_data(ttl=1800, show_spinner=False)
def carregar_senadores_2031():
    return senado2026.carregar_senadores_2031()


with st.sidebar:
    pagina = st.radio(
        "Navegação",
        ["Apuração ao vivo", "Pós-eleição", "Interesse dos clientes", "Senado 2026"],
        label_visibility="collapsed", key="pagina_nav",
    )
    st.markdown("---")

    try:
        st.image(LOGO_PATH, width="stretch")
    except Exception:
        st.caption("Logo não encontrada.")
    st.markdown(
        f'<div style="border-left:3px solid {EIXO["vinho"]};padding:10px 12px;'
        f'margin:0 0 10px 0;background:#fff;border-radius:0 6px 6px 0;">'
        f'<p style="font-size:12.5px;color:{EIXO["tinta"]};line-height:1.65;margin:0;">'
        f'Lê os arquivos JSON públicos e oficiais de '
        f'<strong>resultados.tse.jus.br</strong>, sem chave nem cadastro.'
        f"</p></div>",
        unsafe_allow_html=True,
    )

    if pagina == "Apuração ao vivo":
        st.markdown("---")
        st.subheader("Filtros")
        cargo_nome = st.selectbox("Cargo", list(CARGOS.keys()))
        cargo_cod = CARGOS[cargo_nome]

        if cargo_cod == "0001":
            uf = st.selectbox(
                "Abrangência",
                UFS_PRESIDENTE,
                format_func=lambda u: {"br": "BR (nacional)", "zz": "Exterior"}.get(
                    u, u.upper()
                ),
            )
        else:
            uf = st.selectbox(
                "UF",
                UFS_ESTADUAIS,
                index=UFS_ESTADUAIS.index("sp"),
                format_func=str.upper,
            )

        turnos_possiveis = [t for t, e in ELEICOES[cargo_cod].items() if e]
        if len(turnos_possiveis) > 1:
            turno = st.radio("Turno", turnos_possiveis, horizontal=True)
        else:
            turno = turnos_possiveis[0]
            st.caption(f"{cargo_nome} só tem 1º turno (não há 2º turno para este cargo).")

        filtro_cliente = None
        if cargo_cod in CARGO_LOGICO_CLIENTES:
            try:
                interesses_clientes, _pendencias_clientes = carregar_interesses_clientes()
                clientes_disponiveis = (
                    sorted(interesses_clientes["cliente"].unique())
                    if not interesses_clientes.empty else []
                )
            except requests.RequestException:
                clientes_disponiveis = []
            if clientes_disponiveis:
                escolha = st.selectbox("Cliente (marcar interesse)", ["Todos"] + clientes_disponiveis)
                filtro_cliente = None if escolha == "Todos" else escolha

    st.markdown("---")
    if st.button("↻ Atualizar agora", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"Atualização automática a cada {REFRESH_SEGUNDOS}s.")


@st.cache_data(ttl=REFRESH_SEGUNDOS - 5, show_spinner=False)
def carregar(cargo_cod: str, uf: str, turno: int):
    df = obter_resultado(cargo_cod, uf, turno)
    return df, df.attrs["meta"]


@st.cache_data(ttl=REFRESH_MAPA_SEGUNDOS - 10, show_spinner=False)
def carregar_mapa(turno: int):
    return obter_secoes_totalizadas_por_uf(turno)


@st.cache_data(ttl=REFRESH_MAPA_SEGUNDOS - 10, show_spinner=False)
def carregar_resumo_presidente_uf(turno: int):
    return obter_resumo_presidente_por_uf(turno)


@st.cache_data(ttl=REFRESH_MAPA_SEGUNDOS - 10, show_spinner=False)
def carregar_decisao_governador():
    return obter_decisao_governador()


@st.cache_data(ttl=REFRESH_MAPA_SEGUNDOS - 10, show_spinner=False)
def carregar_resumo_senador_uf():
    return obter_resumo_senador_por_uf()


@st.cache_data(ttl=REFRESH_MAPA_SEGUNDOS - 10, show_spinner=False)
def carregar_tabela_uf(cargo_cod: str, turno: int):
    return obter_resumo_uf_tabela(cargo_cod, turno)


@st.cache_data(ttl=REFRESH_MAPA_SEGUNDOS - 10, show_spinner=False)
def carregar_governador_final_uf():
    return obter_resumo_governador_final_por_uf()



def carregar_resumo_presidente_final():
    """2º turno se existir apuração pra ele; senão cai pro 1º turno (eleição
    decidida já na primeira rodada — não fica sem resposta)."""
    df = carregar_resumo_presidente_uf(2)
    if df["vencedor"].isna().all():
        return carregar_resumo_presidente_uf(1), 1
    return df, 2


REGIOES_ORDEM = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
PALETA_CANDIDATOS = [EIXO["marinho"], EIXO["vinho"], EIXO["amarelo"], "#4C8C4A", "#7F5AA6", "#4A90A4"]

def render_pos_eleicao():
    st.markdown(
        """
<div class="tse-pos-intro">
  ⚠️ Números batem com o estado atual da apuração — ainda em contagem, o
  retrato muda a cada atualização. O que exige comparar com a eleição de
  2018, a composição anterior do Senado/governos, pesquisas pré-eleição ou
  gênero do candidato não dá pra tirar dos arquivos de apuração do TSE —
  fica no checklist ao final desta aba.
</div>""",
        unsafe_allow_html=True,
    )

    try:
        df_pres, turno_final = carregar_resumo_presidente_final()
    except requests.RequestException as e:
        st.error(f"Falha ao consultar o TSE: {e}")
        df_pres, turno_final = None, None

    df_validos = df_pres.dropna(subset=["vencedor"]) if df_pres is not None else None
    candidatos_ordenados = []
    cor_por_candidato = {}

    tab_pres, tab_sen, tab_gov, tab_geral = st.tabs(["Presidente", "Senado", "Governador", "Geral"])

    with tab_pres:
        st.markdown('<div class="tse-pos-cat">Presidente — quem venceu em cada estado</div>', unsafe_allow_html=True)
        if df_validos is None or df_validos.empty:
            st.warning("Nenhuma UF respondeu ainda para Presidente.")
        else:
            candidatos_ordenados = (
                df_validos.groupby("vencedor")["uf"].count().sort_values(ascending=False).index.tolist()
            )
            cor_por_candidato = {
                c: PALETA_CANDIDATOS[i % len(PALETA_CANDIDATOS)] for i, c in enumerate(candidatos_ordenados)
            }
            idx_por_candidato = {c: i for i, c in enumerate(candidatos_ordenados)}
            n_cand = len(candidatos_ordenados)

            geo = carregar_geojson_uf()
            colorscale = []
            for i, c in enumerate(candidatos_ordenados):
                cor = cor_por_candidato[c]
                colorscale.append([i / n_cand, cor])
                colorscale.append([(i + 1) / n_cand, cor])

            fig_mapa = go.Figure(
                go.Choroplethmap(
                    geojson=geo,
                    featureidkey="properties.sigla",
                    locations=df_validos["uf"],
                    z=[idx_por_candidato[c] + 0.5 for c in df_validos["vencedor"]],
                    zmin=0,
                    zmax=n_cand,
                    colorscale=colorscale,
                    showscale=False,
                    marker_line_color="#ffffff",
                    marker_line_width=1,
                    customdata=df_validos[["uf", "vencedor", "vencedor_pct", "margem_pct"]],
                    hovertemplate=(
                        "<b>%{customdata[0]}</b><br>%{customdata[1]} — %{customdata[2]:.2f}%<br>"
                        "Margem: %{customdata[3]:.2f} p.p.<extra></extra>"
                    ),
                )
            )
            for c in candidatos_ordenados:
                fig_mapa.add_trace(
                    go.Scattermap(
                        lat=[None], lon=[None], mode="markers",
                        marker=dict(size=10, color=cor_por_candidato[c]),
                        name=c, showlegend=True,
                    )
                )
            fig_mapa.update_layout(
                height=460,
                margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor=EIXO["gelo"],
                font={"family": "Montserrat", "color": EIXO["tinta"]},
                map_style="white-bg",
                map_zoom=2.9,
                map_center={"lat": -14, "lon": -55},
                legend=dict(orientation="h", y=-0.02, font={"family": "Montserrat", "size": 11}),
            )
            st.plotly_chart(fig_mapa, width="stretch", theme=None, config={"displayModeBar": False})

            for c in candidatos_ordenados:
                ufs_candidato = sorted(df_validos.loc[df_validos["vencedor"] == c, "uf"].tolist())
                st.markdown(
                    f'<div class="tse-pos-list" style="border-top:1px solid {EIXO["borda"]};">'
                    f'<li><span class="tse-pos-num" style="color:{cor_por_candidato[c]};">{esc(c)}</span>'
                    f'<span>venceu em {len(ufs_candidato)} estado(s): {", ".join(ufs_candidato) or "—"}</span></li>'
                    f"</div>",
                    unsafe_allow_html=True,
                )

            faltando = df_pres[df_pres["vencedor"].isna()]
            if not faltando.empty:
                st.caption("Sem resposta do TSE ainda para: " + ", ".join(faltando["uf"].tolist()))

            if turno_final == 2:
                try:
                    df_t1 = carregar_resumo_presidente_uf(1)
                    comp = df_pres[["uf", "vencedor"]].merge(
                        df_t1[["uf", "vencedor"]].dropna(), on="uf", suffixes=("_t2", "_t1")
                    ).dropna(subset=["vencedor_t2"])
                    viraram = comp[comp["vencedor_t1"] != comp["vencedor_t2"]]
                    st.markdown(
                        '<div class="tse-pos-cat">Estados que mudaram de líder entre o 1º e o 2º turno</div>',
                        unsafe_allow_html=True,
                    )
                    if viraram.empty:
                        st.caption("Nenhum estado mudou de candidato líder entre os turnos.")
                    else:
                        itens = "".join(
                            f'<li><span class="tse-pos-num">{esc(r.uf)}</span>'
                            f'<span>{esc(r.vencedor_t1)} → {esc(r.vencedor_t2)}</span></li>'
                            for r in viraram.itertuples()
                        )
                        st.markdown(f'<ul class="tse-pos-list">{itens}</ul>', unsafe_allow_html=True)
                except requests.RequestException:
                    pass

            st.markdown('<div class="tse-pos-cat">Vitórias mais apertadas e mais folgadas</div>', unsafe_allow_html=True)
            st.caption(
                "⚠️ Cada barra é a diferença de votos válidos entre o 1º e o 2º "
                "colocado no estado — quanto maior a barra, mais folgada foi a "
                "vitória ali. As barras ficam ordenadas da vitória mais apertada "
                "(embaixo) pra mais folgada (em cima)."
            )
            legenda_cores = "".join(
                f'<span style="display:inline-flex;align-items:center;margin-right:16px;">'
                f'<span style="width:10px;height:10px;border-radius:2px;background:{cor_por_candidato[c]};'
                f'display:inline-block;margin-right:6px;"></span>{esc(c)}</span>'
                for c in candidatos_ordenados
            )
            st.markdown(
                f'<div style="font-size:11.5px;color:{EIXO["subtexto"]};margin-bottom:6px;">{legenda_cores}</div>',
                unsafe_allow_html=True,
            )
            df_margem = df_validos.sort_values("margem_pct", ascending=True)
            fig_margem = go.Figure(
                go.Bar(
                    x=df_margem["margem_pct"],
                    y=df_margem["uf"],
                    orientation="h",
                    marker_color=[cor_por_candidato[c] for c in df_margem["vencedor"]],
                    text=[f"{m:.1f} p.p." for m in df_margem["margem_pct"]],
                    textposition="outside",
                    textfont={"family": "Montserrat", "color": EIXO["tinta"]},
                    customdata=df_margem[["vencedor"]],
                    hovertemplate="<b>%{y}</b> — %{customdata[0]}<br>Margem: %{x:.2f} p.p.<extra></extra>",
                )
            )
            fig_margem.update_layout(
                height=max(360, 26 * len(df_margem)),
                margin=dict(l=10, r=60, t=10, b=40),
                xaxis_title="Diferença entre 1º e 2º colocado (pontos percentuais)",
                plot_bgcolor=EIXO["gelo"],
                paper_bgcolor=EIXO["gelo"],
                font={"family": "Montserrat", "size": 11, "color": EIXO["tinta"]},
            )
            fig_margem.update_yaxes(automargin=True)
            fig_margem.update_xaxes(gridcolor=EIXO["borda"], zeroline=False)
            st.plotly_chart(fig_margem, width="stretch", theme=None, config={"displayModeBar": False})

            cols_extremos = st.columns(len(candidatos_ordenados))
            for col, c in zip(cols_extremos, candidatos_ordenados):
                df_cand = df_margem[df_margem["vencedor"] == c]
                if df_cand.empty:
                    continue
                apertada_c = df_cand.iloc[0]
                folgada_c = df_cand.iloc[-1]
                with col:
                    st.markdown(
                        f"""
<div style="border-top:3px solid {cor_por_candidato[c]}; padding-top:8px;">
  <div style="font-size:11px; font-weight:700; color:{cor_por_candidato[c]};
  text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;">{esc(c)}</div>
  <ul class="tse-pos-list">
    <li><span class="tse-pos-num">Mais apertada</span><span>{esc(apertada_c['uf'])} —
    venceu por {apertada_c['margem_pct']:.2f} p.p.</span></li>
    <li><span class="tse-pos-num">Mais folgada</span><span>{esc(folgada_c['uf'])} —
    venceu por {folgada_c['margem_pct']:.2f} p.p.</span></li>
  </ul>
</div>""",
                        unsafe_allow_html=True,
                    )

            st.markdown('<div class="tse-pos-cat">Votação média por região</div>', unsafe_allow_html=True)
            st.caption(
                "⚠️ Média simples do % de cada candidato entre os estados da região "
                "(não pondera por eleitorado — estado pequeno pesa igual a estado grande)."
            )
            soma = {}
            conta = {}
            for _, row in df_validos.iterrows():
                pares = [(row["regiao"], row["vencedor"], row["vencedor_pct"])]
                if pd.notna(row["segundo_pct"]):
                    pares.append((row["regiao"], row["segundo_nome"], row["segundo_pct"]))
                for regiao, cand, pct in pares:
                    soma[(regiao, cand)] = soma.get((regiao, cand), 0.0) + pct
                    conta[(regiao, cand)] = conta.get((regiao, cand), 0) + 1

            fig_regiao = go.Figure()
            for c in candidatos_ordenados:
                ys = [
                    soma.get((r, c), 0) / conta[(r, c)] if conta.get((r, c)) else None
                    for r in REGIOES_ORDEM
                ]
                fig_regiao.add_trace(
                    go.Bar(x=REGIOES_ORDEM, y=ys, name=c, marker_color=cor_por_candidato.get(c, COR_GRAFICO))
                )
            fig_regiao.update_layout(
                barmode="group",
                height=360,
                margin=dict(l=10, r=10, t=10, b=10),
                yaxis_title="% médio de votos válidos",
                plot_bgcolor=EIXO["gelo"],
                paper_bgcolor=EIXO["gelo"],
                font={"family": "Montserrat", "size": 11, "color": EIXO["tinta"]},
                legend=dict(orientation="h", y=-0.15),
            )
            fig_regiao.update_yaxes(gridcolor=EIXO["borda"], zeroline=False)
            st.plotly_chart(fig_regiao, width="stretch", theme=None, config={"displayModeBar": False})

            st.markdown('<div class="tse-pos-cat">Mapa comparado à eleição de 2018 (quais estados mudaram de lado)</div>', unsafe_allow_html=True)
            st.caption(
                "⚠️ Não dá pra responder só com os arquivos de apuração de 2022 — "
                "eles não trazem o resultado de 2018. Precisaria cruzar com o "
                "resumo por UF da eleição anterior (mesma lógica desta página, "
                "aplicada ao ciclo `ele2018`)."
            )

        st.markdown('<div class="tse-pos-cat">Abstenção por estado (Presidente)</div>', unsafe_allow_html=True)
        if df_pres is not None:
            df_abst = df_pres.dropna(subset=["abstencao_pct"]).sort_values("abstencao_pct", ascending=False)
            if df_abst.empty:
                st.caption("Sem dados de abstenção ainda.")
            else:
                st.caption(
                    "⚠️ % de eleitores registrados no estado que não compareceram — "
                    "ordenado do estado que mais deixou de votar (esquerda) pro que "
                    "menos deixou (direita). Barra em destaque = maior e menor abstenção."
                )
                uf_maior = df_abst.iloc[0]
                uf_menor = df_abst.iloc[-1]
                cores_abst = [
                    EIXO["vinho"] if uf == uf_maior["uf"]
                    else EIXO["amarelo"] if uf == uf_menor["uf"]
                    else COR_GRAFICO
                    for uf in df_abst["uf"]
                ]
                fig_abst = go.Figure(
                    go.Bar(
                        x=df_abst["uf"],
                        y=df_abst["abstencao_pct"],
                        marker_color=cores_abst,
                        text=[f"{v:.1f}%" for v in df_abst["abstencao_pct"]],
                        textposition="outside",
                        textfont={"family": "Montserrat", "size": 10, "color": EIXO["tinta"]},
                    )
                )
                fig_abst.update_layout(
                    height=380,
                    margin=dict(l=60, r=10, t=20, b=10),
                    yaxis_title="% de abstenção",
                    plot_bgcolor=EIXO["gelo"],
                    paper_bgcolor=EIXO["gelo"],
                    font={"family": "Montserrat", "size": 11, "color": EIXO["tinta"]},
                    bargap=0.25,
                )
                fig_abst.update_yaxes(gridcolor=EIXO["borda"], zeroline=False, title_standoff=16)
                fig_abst.update_xaxes(tickfont={"size": 10})
                st.plotly_chart(fig_abst, width="stretch", theme=None, config={"displayModeBar": False})
                st.markdown(
                    f"""
<ul class="tse-pos-list">
  <li><span class="tse-pos-num" style="color:{EIXO["vinho"]};">Maior abstenção</span>
  <span>{esc(uf_maior['uf'])} — {uf_maior['abstencao_pct']:.2f}%</span></li>
  <li><span class="tse-pos-num" style="color:{EIXO["amarelo"]};">Menor abstenção</span>
  <span>{esc(uf_menor['uf'])} — {uf_menor['abstencao_pct']:.2f}%</span></li>
</ul>""",
                    unsafe_allow_html=True,
                )

    with tab_sen:
        try:
            df_sen = carregar_resumo_senador_uf()
        except requests.RequestException as e:
            st.error(f"Falha ao consultar o TSE: {e}")
            df_sen = None

        df_sen_validos = df_sen.dropna(subset=["eleito1_nome"]) if df_sen is not None else None
        vagas_ciclo = vagas_senado_por_uf(CICLO)

        st.markdown('<div class="tse-pos-cat">Senado — quem venceu em cada estado</div>', unsafe_allow_html=True)
        st.caption(
            f"⚠️ Senador é sempre decidido em turno único (não há 2º turno pra "
            f"essa eleição) — mas o número de vagas por estado muda por ciclo: "
            f"neste ({esc(CICLO)}) são {vagas_ciclo} por UF. Quem diz quantos "
            f"venceram em cada estado é a contagem de \"Eleito\" no arquivo do "
            f"TSE, não um número fixo nesta tela."
        )
        if df_sen_validos is None or df_sen_validos.empty:
            st.warning("Nenhuma UF respondeu ainda para Senador.")
        else:
            linhas_html = "".join(
                f"""
    <tr>
      <td class="tse-snap-cand">{esc(r.uf)}</td>
      <td>{esc(r.eleito1_nome)}<div class="tse-snap-sub">{esc(r.eleito1_coligacao)}</div></td>
      <td class="tse-num">{r.eleito1_pct:.2f}%</td>
      <td>{esc(r.eleito2_nome) if pd.notna(r.eleito2_nome) else "—"}{f'<div class="tse-snap-sub">{esc(r.eleito2_coligacao)}</div>' if pd.notna(r.eleito2_nome) else ""}</td>
      <td class="tse-num">{f"{r.eleito2_pct:.2f}%" if pd.notna(r.eleito2_pct) else "—"}</td>
    </tr>"""
                for r in df_sen_validos.sort_values("uf").itertuples()
            )
            st.markdown(
                f"""
    <div class="tse-snap-wrap">
      <table class="tse-snap-table">
        <thead><tr><th>UF</th><th>1º eleito</th><th class="tse-num">% válidos</th><th>2º eleito (ciclos de 2 vagas)</th><th class="tse-num">% válidos</th></tr></thead>
        <tbody>{linhas_html}</tbody>
      </table>
    </div>""",
                unsafe_allow_html=True,
            )

            faltando_sen = df_sen[df_sen["eleito1_nome"].isna()]
            if not faltando_sen.empty:
                st.caption("Sem resposta do TSE ainda para: " + ", ".join(faltando_sen["uf"].tolist()))

            st.markdown('<div class="tse-pos-cat">Senado — disputa mais apertada e mais folgada pela última vaga</div>', unsafe_allow_html=True)
            st.caption(
                "⚠️ Não é mais \"1º menos 2º colocado\" — em ciclo de 2 vagas o "
                "2º colocado também se elege. É a distância entre a ÚLTIMA vaga "
                "preenchida naquele estado e o primeiro candidato que ficou de "
                "fora (\"quase lá\")."
            )
            df_sen_margem = df_sen_validos.dropna(subset=["margem_pct"]).sort_values("margem_pct", ascending=True)
            fig_sen_margem = go.Figure(
                go.Bar(
                    x=df_sen_margem["margem_pct"],
                    y=df_sen_margem["uf"],
                    orientation="h",
                    marker_color=COR_GRAFICO,
                    text=[f"{m:.1f} p.p." for m in df_sen_margem["margem_pct"]],
                    textposition="outside",
                    textfont={"family": "Montserrat", "color": EIXO["tinta"]},
                    customdata=df_sen_margem[["proximo_nome"]],
                    hovertemplate="<b>%{y}</b> — quase lá: %{customdata[0]}<br>Distância até a última vaga: %{x:.2f} p.p.<extra></extra>",
                )
            )
            fig_sen_margem.update_layout(
                height=max(360, 26 * len(df_sen_margem)),
                margin=dict(l=10, r=60, t=10, b=40),
                xaxis_title="Distância até a última vaga (pontos percentuais)",
                plot_bgcolor=EIXO["gelo"],
                paper_bgcolor=EIXO["gelo"],
                font={"family": "Montserrat", "size": 11, "color": EIXO["tinta"]},
            )
            fig_sen_margem.update_yaxes(automargin=True)
            fig_sen_margem.update_xaxes(gridcolor=EIXO["borda"], zeroline=False)
            st.plotly_chart(fig_sen_margem, width="stretch", theme=None, config={"displayModeBar": False})

        st.markdown('<div class="tse-pos-cat">Senado — o que os arquivos de apuração não respondem</div>', unsafe_allow_html=True)
        ano_ciclo_sen = int(CICLO.replace("ele", ""))
        st.markdown(
            f"""
    <ul class="tse-pos-list">
      <li><span class="tse-pos-num">·</span><span>Quais senadores titulares não se reelegeram — exige saber quem
      já era o senador titular em cada estado (eleito em {ano_ciclo_sen - 8}, mesma renovação de vagas
      recontestada agora), dado que não vem no arquivo de apuração.</span></li>
      <li><span class="tse-pos-num">·</span><span>Cadeiras ganhas/perdidas por partido vs. a legislatura anterior —
      exige a composição do Senado antes da eleição, e o arquivo só traz a coligação (não o partido) do vencedor.</span></li>
      <li><span class="tse-pos-num">·</span><span>Quantos eleitos são estreantes no cargo — mesma limitação: precisa
      do histórico de quem já ocupou a cadeira.</span></li>
      <li><span class="tse-pos-num">·</span><span>Estados onde o Senado "virou de espectro" — exigiria um mapeamento
      partido → posição política, que este painel não tem.</span></li>
      <li><span class="tse-pos-num">·</span><span>Quantas mulheres foram eleitas — o arquivo de apuração não traz o
      gênero do candidato (só nome, número, coligação e votos).</span></li>
    </ul>""",
            unsafe_allow_html=True,
        )

    with tab_gov:
        st.markdown('<div class="tse-pos-cat">Governador — decidido em que turno</div>', unsafe_allow_html=True)
        try:
            df_gov = carregar_decisao_governador()
        except requests.RequestException as e:
            st.error(f"Falha ao consultar o TSE: {e}")
            df_gov = None

        if df_gov is not None:
            n_1o = int((df_gov["decidido_1o_turno"] == True).sum())  # noqa: E712
            n_2o = int((df_gov["decidido_1o_turno"] == False).sum())  # noqa: E712
            n_indef = int(df_gov["decidido_1o_turno"].isna().sum())
            fig_gov = go.Figure(
                go.Pie(
                    labels=["Decidido no 1º turno", "Foi a 2º turno", "Ainda em apuração"],
                    values=[n_1o, n_2o, n_indef],
                    hole=0.55,
                    marker_colors=[EIXO["marinho"], EIXO["vinho"], EIXO["borda"]],
                    textfont={"family": "Montserrat"},
                )
            )
            fig_gov.update_layout(
                height=320,
                margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor=EIXO["gelo"],
                font={"family": "Montserrat", "size": 12, "color": EIXO["tinta"]},
                legend=dict(orientation="h", y=-0.1),
            )
            st.plotly_chart(fig_gov, width="stretch", theme=None, config={"displayModeBar": False})

            st.markdown('<div class="tse-pos-cat">Governador — quem venceu em cada estado</div>', unsafe_allow_html=True)
            df_gov_validos = df_gov.dropna(subset=["vencedor"])
            if df_gov_validos.empty:
                st.warning("Nenhuma UF respondeu ainda para Governador.")
            else:
                linhas_html = "".join(
                    f"""
    <tr>
      <td class="tse-snap-cand">{esc(r.uf)}</td>
      <td>{esc(r.vencedor)}<div class="tse-snap-sub">{esc(r.vencedor_coligacao)}</div></td>
      <td>{"1º turno" if r.decidido_1o_turno else "2º turno"}</td>
    </tr>"""
                    for r in df_gov_validos.sort_values("uf").itertuples()
                )
                st.markdown(
                    f"""
    <div class="tse-snap-wrap">
      <table class="tse-snap-table">
        <thead><tr><th>UF</th><th>Vencedor</th><th>Decidido em</th></tr></thead>
        <tbody>{linhas_html}</tbody>
      </table>
    </div>""",
                    unsafe_allow_html=True,
                )
                faltando_gov = df_gov[df_gov["vencedor"].isna()]
                if not faltando_gov.empty:
                    st.caption("Sem resposta do TSE ainda para: " + ", ".join(faltando_gov["uf"].tolist()))

        st.markdown('<div class="tse-pos-cat">Governador — o que os arquivos de apuração não respondem</div>', unsafe_allow_html=True)
        st.markdown(
            """
    <ul class="tse-pos-list">
      <li><span class="tse-pos-num">·</span><span>Quais governadores titulares perderam a reeleição — exige saber
      quem era o titular em cada estado antes da eleição, dado que não vem no arquivo de apuração.</span></li>
      <li><span class="tse-pos-num">·</span><span>Quantos governos estaduais mudaram de partido — exige a coligação/
      partido vencedor da eleição anterior (2018) para comparar.</span></li>
    </ul>""",
            unsafe_allow_html=True,
        )

    with tab_geral:
        st.markdown(
            '<div class="tse-pos-cat">Presidente × Governador — o estado votou junto ou dividiu?</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "⚠️ Compara só a coligação vencedora de cada corrida no estado — "
            "rotular isso como \"espectro político oposto\" exigiria um mapeamento "
            "partido → posição política que este painel não tem."
        )
        if df_pres is not None and df_gov is not None:
            cruz = df_pres[["uf", "vencedor", "vencedor_coligacao"]].merge(
                df_gov[["uf", "vencedor", "vencedor_coligacao"]], on="uf", suffixes=("_pres", "_gov"), how="inner"
            )
            linhas_html = ""
            for _, row in cruz.sort_values("uf").iterrows():
                mesma = bool(
                    row["vencedor_coligacao_pres"]
                    and row["vencedor_coligacao_gov"]
                    and row["vencedor_coligacao_pres"] == row["vencedor_coligacao_gov"]
                )
                badge = (
                    '<span class="tse-badge tse-badge-eleito">Mesma coligação</span>'
                    if mesma
                    else '<span class="tse-badge tse-badge-naoeleito">Coligações diferentes</span>'
                )
                linhas_html += f"""
    <tr>
      <td class="tse-snap-cand">{esc(row['uf'])}</td>
      <td>{esc(row['vencedor_pres']) or '—'}<div class="tse-snap-sub">{esc(row['vencedor_coligacao_pres']) or '—'}</div></td>
      <td>{esc(row['vencedor_gov']) or '—'}<div class="tse-snap-sub">{esc(row['vencedor_coligacao_gov']) or '—'}</div></td>
      <td>{badge}</td>
    </tr>"""
            st.markdown(
                f"""
    <div class="tse-snap-wrap">
      <table class="tse-snap-table">
        <thead><tr><th>UF</th><th>Vencedor Presidente</th><th>Vencedor Governador</th><th>Coligação</th></tr></thead>
        <tbody>{linhas_html}</tbody>
      </table>
    </div>""",
                unsafe_allow_html=True,
            )

        st.markdown(
            '<div class="tse-pos-cat">Presidente × Senado — o estado votou junto ou dividiu?</div>',
            unsafe_allow_html=True,
        )
        if df_pres is not None and df_sen is not None:
            cruz_sen = df_pres[["uf", "vencedor", "vencedor_coligacao"]].merge(
                df_sen[["uf", "eleito1_nome", "eleito1_coligacao", "eleito2_nome", "eleito2_coligacao"]],
                on="uf", how="inner",
            )
            linhas_html = ""
            for _, row in cruz_sen.sort_values("uf").iterrows():
                coligacoes_sen = {
                    c for c in (row["eleito1_coligacao"], row["eleito2_coligacao"]) if pd.notna(c) and c
                }
                mesma = bool(row["vencedor_coligacao"]) and row["vencedor_coligacao"] in coligacoes_sen
                badge = (
                    '<span class="tse-badge tse-badge-eleito">Mesma coligação</span>'
                    if mesma
                    else '<span class="tse-badge tse-badge-naoeleito">Coligações diferentes</span>'
                )
                eleitos_sen_txt = esc(row["eleito1_nome"]) or "—"
                coligs_sen_txt = esc(row["eleito1_coligacao"]) or "—"
                if pd.notna(row["eleito2_nome"]):
                    eleitos_sen_txt += f" · {esc(row['eleito2_nome'])}"
                    coligs_sen_txt += f" · {esc(row['eleito2_coligacao'])}"
                linhas_html += f"""
    <tr>
      <td class="tse-snap-cand">{esc(row['uf'])}</td>
      <td>{esc(row['vencedor']) or '—'}<div class="tse-snap-sub">{esc(row['vencedor_coligacao']) or '—'}</div></td>
      <td>{eleitos_sen_txt}<div class="tse-snap-sub">{coligs_sen_txt}</div></td>
      <td>{badge}</td>
    </tr>"""
            st.caption(
                "⚠️ \"Mesma coligação\" considera bater com QUALQUER um dos "
                "eleitos ao Senado no estado (podem ser 2, a depender do ciclo)."
            )
            st.markdown(
                f"""
    <div class="tse-snap-wrap">
      <table class="tse-snap-table">
        <thead><tr><th>UF</th><th>Vencedor Presidente</th><th>Eleito(s) Senado</th><th>Coligação</th></tr></thead>
        <tbody>{linhas_html}</tbody>
      </table>
    </div>""",
                unsafe_allow_html=True,
            )

        st.markdown('<div class="tse-pos-cat">Maiores "zebras" (favorito nas pesquisas que perdeu)</div>', unsafe_allow_html=True)
        st.caption(
            "⚠️ Não dá pra responder com os arquivos de apuração — eles só têm o "
            "resultado das urnas, não pesquisas eleitorais pré-eleição. Precisaria "
            "cruzar com uma base externa de pesquisas (ex.: agregador de institutos) "
            "por estado/cargo."
        )

        st.markdown('<div class="tse-pos-cat">Checklist — o que fica de fora só com dados de apuração</div>', unsafe_allow_html=True)
        st.markdown(
            """
    <ul class="tse-pos-list">
      <li><span class="tse-pos-num">1</span><span><strong>Comparação com a eleição de 2018</strong> (Presidente,
      Governador, Senado) — precisa do resumo por UF do ciclo `ele2018`, que este painel não consulta.</span></li>
      <li><span class="tse-pos-num">2</span><span><strong>Titulares que perderam a reeleição</strong> (Governador e
      Senado) — precisa saber quem já ocupava o cargo antes da eleição.</span></li>
      <li><span class="tse-pos-num">3</span><span><strong>Cadeiras por partido vs. legislatura anterior</strong> e
      <strong>estreantes no cargo</strong> (Senado) — precisa da composição anterior do Senado; o arquivo de apuração
      só traz a coligação do vencedor, não o partido isolado.</span></li>
      <li><span class="tse-pos-num">4</span><span><strong>Espectro político</strong> (Presidente, Governador, Senado)
      — precisaria de um mapeamento partido → posição política; este painel só compara coligações, não ideologia.</span></li>
      <li><span class="tse-pos-num">5</span><span><strong>Gênero dos eleitos</strong> (quantas mulheres no Senado) —
      o arquivo de apuração não traz esse campo.</span></li>
      <li><span class="tse-pos-num">6</span><span><strong>Abstenção por município</strong> — os arquivos consultados
      aqui são agregados por UF; abstenção por município exigiria buscar os dados de cada um dos +5.000 municípios
      individualmente.</span></li>
      <li><span class="tse-pos-num">7</span><span><strong>"Zebras" (favorito que perdeu)</strong> — precisa de dados
      de pesquisas eleitorais pré-eleição, que não vêm dos arquivos de apuração do TSE.</span></li>
    </ul>""",
            unsafe_allow_html=True,
        )


def render_interesse_clientes():
    try:
        encontrados, pendencias = carregar_interesses_clientes()
    except requests.RequestException as e:
        st.error(f"Falha ao consultar a planilha: {e}")
        return

    if encontrados.empty and pendencias.empty:
        st.warning("Não consegui carregar nada da planilha de clientes.")
        return

    total_clientes = encontrados["cliente"].nunique() if not encontrados.empty else 0
    st.markdown(
        f"""
<div class="tse-stat-wrap">
  <div class="tse-stat">
    <div class="tse-stat-label">Clientes com nome casado</div>
    <div class="tse-stat-value">{total_clientes}</div>
  </div>
  <div class="tse-stat">
    <div class="tse-stat-label">Nomes casados</div>
    <div class="tse-stat-value">{len(encontrados)}</div>
  </div>
  <div class="tse-stat">
    <div class="tse-stat-label">Pendências</div>
    <div class="tse-stat-value">{len(pendencias)}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
<ul class="tse-pos-list">
  <li><span class="tse-pos-num">·</span><span><strong>Clientes com nome casado</strong> — de todos os
  clientes que têm lista de interesse na planilha, quantos tiveram pelo menos um nome batido com
  sucesso contra o cadastro de parlamentares em exercício.</span></li>
  <li><span class="tse-pos-num">·</span><span><strong>Nomes casados</strong> — total de nomes das
  listas dos clientes que foram identificados (achamos exatamente quem é: cargo, partido, UF).</span></li>
  <li><span class="tse-pos-num">·</span><span><strong>Pendências</strong> — nomes que estavam nas
  listas mas não bateram com ninguém no cadastro atual — na maioria porque a pessoa não é mais
  parlamentar (ex-deputado, ex-senador). Lista completa mais abaixo nesta página.</span></li>
</ul>""",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="tse-pos-cat">Nomes casados</div>', unsafe_allow_html=True)
    if encontrados.empty:
        st.caption("Nenhum nome casado ainda.")
    else:
        opcoes_cliente = ["Todos"] + sorted(encontrados["cliente"].unique())
        escolha = st.selectbox("Filtrar por cliente", opcoes_cliente, key="filtro_pagina_clientes")
        df_show = encontrados if escolha == "Todos" else encontrados[encontrados["cliente"] == escolha]
        linhas_html = "".join(
            f"""
<tr>
  <td class="tse-snap-cand">{esc(r.cliente)}</td>
  <td>{esc(r.parlamentar)}<div class="tse-snap-sub">buscado na planilha como "{esc(r.nome_interesse)}"</div></td>
  <td>{esc(r.cargo)}</td>
  <td>{esc(r.uf)}</td>
  <td>{esc(r.pauta)}</td>
  <td class="tse-snap-sub">{esc(r.motivo)}</td>
</tr>"""
            for r in df_show.sort_values(["cliente", "parlamentar"]).itertuples()
        )
        st.markdown(
            f"""
<div class="tse-snap-wrap">
  <table class="tse-snap-table">
    <thead>
      <tr>
        <th>Cliente</th><th>Parlamentar</th><th>Cargo</th><th>UF</th><th>Pauta</th><th>Como casou</th>
      </tr>
    </thead>
    <tbody>{linhas_html}</tbody>
  </table>
</div>""",
            unsafe_allow_html=True,
        )

    st.markdown('<div class="tse-pos-cat">Pendências — não casaram, revisar na mão</div>', unsafe_allow_html=True)
    st.caption(
        "⚠️ Nomes que a planilha do cliente lista mas que não bateram com ninguém em "
        'exercício — na maioria dos casos porque a pessoa não está mais no cargo '
        '("Ex-parlamentar"), mas vale conferir de vez em quando se não é a planilha '
        "renomeando cabeçalho de novo, ou alguém saindo do cadastro."
    )
    if pendencias.empty:
        st.caption("Nenhuma pendência — tudo casou.")
    else:
        linhas_html = "".join(
            f"""
<tr>
  <td class="tse-snap-cand">{esc(r.cliente)}</td>
  <td>{esc(r.nome_interesse)}</td>
  <td>{esc(r.cargo_partido_uf_bruto) or "—"}</td>
  <td>{esc(r.pauta)}</td>
  <td class="tse-snap-sub">{esc(r.motivo)}</td>
</tr>"""
            for r in pendencias.sort_values(["cliente"]).itertuples()
        )
        st.markdown(
            f"""
<div class="tse-snap-wrap">
  <table class="tse-snap-table">
    <thead>
      <tr>
        <th>Cliente</th><th>Nome (como está na planilha)</th><th>Cargo/Partido/UF</th><th>Pauta</th><th>Motivo</th>
      </tr>
    </thead>
    <tbody>{linhas_html}</tbody>
  </table>
</div>""",
            unsafe_allow_html=True,
        )


def render_senado_2026():
    TOTAL = senado2026.TOTAL_CADEIRAS_SENADO
    GARANTIDAS = senado2026.CADEIRAS_GARANTIDAS_2031
    DISPUTA = senado2026.CADEIRAS_EM_DISPUTA
    pct_garantidas = GARANTIDAS / TOTAL * 100
    pct_disputa = DISPUTA / TOTAL * 100

    try:
        df_cand = carregar_candidaturas_senado_2026()
    except requests.RequestException as e:
        st.error(f"Falha ao consultar a planilha de candidaturas: {e}")
        df_cand = None

    try:
        df_2031 = carregar_senadores_2031()
    except requests.RequestException as e:
        st.error(f"Falha ao consultar a planilha dos mandatos até 2031: {e}")
        df_2031 = None

    st.markdown('<div class="tse-pos-cat">Composição do Senado — 81 cadeiras</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
<div class="tse-uf-bar-wrap" style="height:28px;">
  <div class="tse-uf-bar-seg" style="width:{pct_garantidas}%;background:{EIXO["marinho"]};"
       title="{GARANTIDAS} cadeiras garantidas até 2031"></div>
  <div class="tse-uf-bar-seg" style="width:{pct_disputa}%;background:{EIXO["borda"]};
       background-image:repeating-linear-gradient(45deg,rgba(0,0,0,0.06) 0 6px,transparent 6px 12px);"
       title="{DISPUTA} cadeiras em disputa em 2026"></div>
</div>
<div style="display:flex;justify-content:space-between;font-size:11px;color:{EIXO["subtexto"]};margin-top:4px;">
  <span>■ {GARANTIDAS} garantidas até 2031</span>
  <span>▨ {DISPUTA} em disputa — resultado só em outubro/2026</span>
</div>
""",
        unsafe_allow_html=True,
    )

    if df_cand is not None:
        resumo = senado2026.resumo_julgamento(df_cand)
        st.markdown(
            '<div class="tse-pos-cat">Progresso do registro de candidaturas ao Senado 2026</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "⚠️ Mede quantas candidaturas já saíram de \"aguardando julgamento\" "
            "na Justiça Eleitoral (deferidas, indeferidas ou com renúncia) — "
            "isso é progresso do REGISTRO, não uma projeção de quem vai vencer "
            "a cadeira. Uma candidatura \"Deferida\" só está liberada pra "
            "concorrer em outubro."
        )
        pct_txt = f"{resumo['pct'] * 100:.1f}%" if resumo["total"] else "—"
        st.markdown(
            f"""
<div class="tse-stat-wrap">
  <div class="tse-stat">
    <div class="tse-stat-label">Candidaturas já julgadas</div>
    <div class="tse-stat-value">{fmt(resumo['julgadas'])} de {fmt(resumo['total'])}</div>
    <div class="tse-stat-sub">{pct_txt} do total registrado ao Senado 2026</div>
  </div>
  <div class="tse-stat">
    <div class="tse-stat-label">Estados cobertos</div>
    <div class="tse-stat-value">{df_cand['uf'].nunique() if not df_cand.empty else 0} de {senado2026.TOTAL_UFS}</div>
  </div>
  <div class="tse-stat">
    <div class="tse-stat-label">Partidos com candidatura</div>
    <div class="tse-stat-value">{df_cand['partido_candidato'].nunique() if not df_cand.empty else 0}</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

        st.markdown('<div class="tse-pos-cat">Placar por partido — candidaturas registradas</div>', unsafe_allow_html=True)
        st.caption(
            "⚠️ Conta CANDIDATURAS ao Senado (uma por titular de chapa), não "
            "intenção de voto nem projeção de cadeira — um partido com mais "
            "candidaturas não é um partido com mais chance de eleger. Por "
            "partido isolado de propósito: a coligação de cada chapa tem nome "
            "próprio por estado (mais de 90 nomes distintos hoje), então "
            "agrupar por coligação fragmentaria ainda mais que por partido."
        )
        df_partido = senado2026.placar_por_partido(df_cand)
        if not df_partido.empty:
            df_plot = df_partido.sort_values("candidaturas", ascending=True)
            fig_partido = go.Figure(
                go.Bar(
                    x=df_plot["candidaturas"],
                    y=df_plot["partido_candidato"],
                    orientation="h",
                    marker_color=COR_GRAFICO,
                    text=df_plot["candidaturas"],
                    textposition="outside",
                    textfont={"family": "Montserrat", "color": EIXO["tinta"]},
                    customdata=df_plot[["n_ufs"]],
                    hovertemplate="<b>%{y}</b><br>%{x} candidatura(s) · %{customdata[0]} UF(s)<extra></extra>",
                )
            )
            fig_partido.update_layout(
                height=max(360, 24 * len(df_plot)),
                margin=dict(l=10, r=40, t=10, b=40),
                xaxis_title="Candidaturas ao Senado registradas (2026)",
                plot_bgcolor=EIXO["gelo"],
                paper_bgcolor=EIXO["gelo"],
                font={"family": "Montserrat", "size": 11, "color": EIXO["tinta"]},
            )
            fig_partido.update_yaxes(automargin=True)
            fig_partido.update_xaxes(gridcolor=EIXO["borda"], zeroline=False)
            st.plotly_chart(fig_partido, width="stretch", theme=None, config={"displayModeBar": False})

        st.markdown('<div class="tse-pos-cat">Candidaturas ao Senado por estado — 2026</div>', unsafe_allow_html=True)
        badge_class_cand = {
            "Deferido": "tse-badge-eleito",
            "Aguardando julgamento": "tse-badge-2turno",
        }

        def badge_candidatura(situacao: str) -> str:
            cls = badge_class_cand.get(situacao, "tse-badge-naoeleito")
            return f'<span class="tse-badge {cls}">{esc(situacao)}</span>'

        if df_cand.empty:
            st.caption("Nenhuma candidatura ao Senado 2026 encontrada na planilha ainda.")
        else:
            opcoes_uf = ["Todos"] + sorted(df_cand["uf"].unique())
            escolha_uf = st.selectbox("Filtrar por UF", opcoes_uf, key="filtro_senado_uf")
            df_show = df_cand if escolha_uf == "Todos" else df_cand[df_cand["uf"] == escolha_uf]
            linhas_html = "".join(
                f"""
<tr>
  <td class="tse-snap-cand">{esc(r.uf)}</td>
  <td>{esc(r.candidato)}<div class="tse-snap-sub">{esc(r.partido_candidato)}</div></td>
  <td>{esc(r.nome_coligacao)}<div class="tse-snap-sub">{esc(r.tipo_chapa)}{f" · {int(r.quantidade_partidos)} partido(s)" if pd.notna(r.quantidade_partidos) else ""}</div></td>
  <td>{badge_candidatura(r.situacao)}</td>
</tr>"""
                for r in df_show.sort_values(["uf", "candidato"]).itertuples()
            )
            st.markdown(
                f"""
<div class="tse-snap-wrap">
  <table class="tse-snap-table">
    <thead>
      <tr><th>UF</th><th>Candidato · Partido</th><th>Coligação/Federação</th><th>Situação</th></tr>
    </thead>
    <tbody>{linhas_html}</tbody>
  </table>
</div>""",
                unsafe_allow_html=True,
            )

    if df_2031 is not None:
        st.markdown(
            f'<div class="tse-pos-cat">Os {senado2026.CADEIRAS_GARANTIDAS_2031} mandatos que seguem até 2031 (não estão em disputa)</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "⚠️ Eleitos em 2022, mandato só termina em 2031 — não aparecem "
            "nas urnas de 2026. Quando a \"situação eleitoral em 2026\" mostra "
            "outro cargo (ex.: pré-candidato a governador), a vaga de Senado "
            "pode abrir antes do fim do mandato caso a pessoa se eleja lá — "
            "quem assumiria seria o suplente, dado que este painel não traz."
        )
        if df_2031.empty:
            st.caption("Não consegui carregar a lista de mandatos até 2031.")
        else:
            linhas_2031 = "".join(
                f"""
<tr>
  <td class="tse-snap-cand">{esc(r.uf)}</td>
  <td>{esc(r.senador_exercicio)}<div class="tse-snap-sub">{esc(r.partido_atual)}</div></td>
  <td>{esc(r.mandato)}</td>
  <td>{esc(r.situacao_eleitoral_2026) or "—"}</td>
</tr>"""
                for r in df_2031.sort_values("uf").itertuples()
            )
            st.markdown(
                f"""
<div class="tse-snap-wrap">
  <table class="tse-snap-table">
    <thead>
      <tr><th>UF</th><th>Senador(a)</th><th>Mandato</th><th>Situação eleitoral em 2026</th></tr>
    </thead>
    <tbody>{linhas_2031}</tbody>
  </table>
</div>""",
                unsafe_allow_html=True,
            )

    st.markdown('<div class="tse-pos-cat">O que esta página não responde (ainda)</div>', unsafe_allow_html=True)
    st.markdown(
        """
<ul class="tse-pos-list">
  <li><span class="tse-pos-num">·</span><span>Quem vai vencer cada cadeira — só existe a partir da apuração
  real, em outubro/2026 (este painel ainda não tem esse feed ligado ao ciclo 2026).</span></li>
  <li><span class="tse-pos-num">·</span><span>"Bloco" aqui é o partido isolado do titular da chapa — não um
  agrupamento político maior (governismo/oposição/centrão), que não está disponível nos dados de origem.</span></li>
  <li><span class="tse-pos-num">·</span><span>Se um dos 27 senadores com mandato até 2031 se eleger pra outro
  cargo (ex.: governador), quem assume a cadeira e quando — depende da lista de suplentes, que não está
  nesta planilha.</span></li>
</ul>""",
        unsafe_allow_html=True,
    )


@st.fragment(run_every=REFRESH_SEGUNDOS)
def painel(cargo_nome: str, cargo_cod: str, uf: str, turno: int, filtro_cliente: str | None = None):
    try:
        df, meta = carregar(cargo_cod, uf, turno)
    except FileNotFoundError as e:
        st.warning(str(e))
        return
    except requests.RequestException as e:
        st.error(f"Falha ao consultar o TSE: {e}")
        return

    if df.empty:
        st.warning("Nenhum candidato retornado para essa combinação.")
        return

    # "clientes" fica em TODO candidato (usado pro marcador na tabela de
    # detalhamento) — o filtro em si só restringe aquela tabela, não o
    # card do líder nem o gráfico de distribuição, que continuam
    # mostrando a corrida inteira.
    cargo_logico_cliente = CARGO_LOGICO_CLIENTES.get(cargo_cod)
    if cargo_logico_cliente:
        try:
            interesses_clientes, _pendencias_clientes = carregar_interesses_clientes()
        except requests.RequestException:
            interesses_clientes = pd.DataFrame()
        df = clientes.marcar_candidatos(df, cargo_logico_cliente, uf.upper(), interesses_clientes)
        if cargo_cod == "0005":
            ano_ciclo = int(CICLO.replace("ele", ""))
            cadeiras_ciclo = vagas_senado_por_uf(CICLO) * 27
            cadeiras_outras = 81 - cadeiras_ciclo
            st.caption(
                f"⚠️ Marcação de cliente no Senado só encontra quem foi eleito em "
                f"{ano_ciclo} (as {cadeiras_ciclo} cadeiras deste ciclo) — os outros "
                f"{cadeiras_outras} senadores, eleitos em {ano_ciclo - 4}, não estão nos "
                f"arquivos de apuração que esta aba lê, mesmo aparecendo na planilha "
                f"de interesse dos clientes."
            )

    st.caption(
        f"{cargo_nome} · {uf.upper()} · {turno}º turno  —  "
        f"dado gerado pelo TSE em {meta['data_geracao']} {meta['hora_geracao']}  ·  "
        f"consultado nesta página às {datetime.now():%H:%M:%S}"
    )

    if not meta["totalizacao_final"]:
        st.warning(
            "⚠️ Resultado ainda PARCIAL — o TSE não fechou a totalização "
            "oficial deste arquivo (\"tf\" ≠ \"s\"), mesmo que as seções "
            "totalizadas já estejam em 100%. Em Deputado Federal/Estadual "
            "isso é comum: quem se elege depende do cálculo do quociente "
            "eleitoral com todos os votos já contados, e essa conta demora "
            "mais do que só somar votos."
        )

    # Cargos proporcionais (Dep. Federal/Estadual) usam valores de "situacao"
    # diferentes dos majoritários — nunca aparece "Eleito" sozinho, e sim
    # "Eleito por QP" (quociente partidário) ou "Eleito por média" (sobras).
    badge_class = {
        "Eleito": "tse-badge-eleito",
        "Eleito por QP": "tse-badge-eleito",
        "Eleito por média": "tse-badge-eleito",
        "2º turno": "tse-badge-2turno",
        "Suplente": "tse-badge-suplente",
    }

    def badge_html(situacao: str) -> str:
        cls = badge_class.get(situacao, "tse-badge-naoeleito")
        return f'<span class="tse-badge {cls}">{esc(situacao)}</span>'

    # --- Candidato líder ---
    lider = df.iloc[0]
    st.markdown(
        f"""
<div class="tse-leader">
  <div>
    <div class="tse-leader-num">№ {esc(lider['numero'])} · {esc(lider['coligacao'])}</div>
    <div class="tse-leader-name">{esc(lider['nome'])}{badge_html(lider['situacao'])}</div>
    <div class="tse-leader-cc">Vice: {esc(lider['vice']) or '—'}</div>
  </div>
  <div>
    <div class="tse-leader-pct-label">% dos votos válidos</div>
    <div class="tse-leader-pct">{lider['percentual_validos']:.2f}%</div>
    <div class="tse-leader-votos">{fmt(lider['votos'])} votos</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # --- Faixa de indicadores da apuração ---
    st.markdown(
        f"""
<div class="tse-stat-wrap">
  <div class="tse-stat">
    <div class="tse-stat-label">Seções totalizadas</div>
    <div class="tse-stat-value">{meta['secoes_totalizadas_pct']:.2f}%</div>
  </div>
  <div class="tse-stat">
    <div class="tse-stat-label">Comparecimento</div>
    <div class="tse-stat-value">{meta['comparecimento_pct']:.2f}%</div>
    <div class="tse-stat-sub">{fmt(meta['comparecimento'])} eleitores</div>
  </div>
  <div class="tse-stat">
    <div class="tse-stat-label">Abstenção</div>
    <div class="tse-stat-value">{meta['abstencao_pct']:.2f}%</div>
    <div class="tse-stat-sub">{fmt(meta['abstencao'])} eleitores</div>
  </div>
  <div class="tse-stat">
    <div class="tse-stat-label">Brancos</div>
    <div class="tse-stat-value">{meta['brancos_pct']:.2f}%</div>
    <div class="tse-stat-sub">{fmt(meta['brancos'])} votos</div>
  </div>
  <div class="tse-stat">
    <div class="tse-stat-label">Nulos</div>
    <div class="tse-stat-value">{meta['nulos_pct']:.2f}%</div>
    <div class="tse-stat-sub">{fmt(meta['nulos'])} votos</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.caption(
        f"⚠️ O percentual de cada candidato é sobre os votos VÁLIDOS "
        f"({fmt(meta['votos_validos'])} votos, {meta['votos_validos_pct']:.2f}% do "
        f"comparecimento) — brancos ({fmt(meta['brancos'])}) e nulos "
        f"({fmt(meta['nulos'])}) já saíram do denominador, não é sobre o total de votos."
    )

    # --- Abas: cada uma é uma "mini página" ---
    nomes_abas = ["Distribuição dos votos", "Detalhamento por candidato"]
    tem_mapa = cargo_cod == "0001"
    tem_legenda = cargo_cod in ("0006", "0007")
    tem_tabela_uf = cargo_cod in ("0003", "0005")
    tem_grade_governos = cargo_cod == "0003"
    if tem_mapa:
        nomes_abas.append("Apuração por UF — Presidente")
    if tem_legenda:
        nomes_abas.append("Legenda")
    if tem_tabela_uf:
        nomes_abas.append("Por estado")
    if tem_grade_governos:
        nomes_abas.append("Mapa & lista de governos")
    abas = st.tabs(nomes_abas)

    with abas[0]:
        df_plot = df.sort_values("votos", ascending=True)
        fig = go.Figure(
            go.Bar(
                x=df_plot["percentual_validos"],
                y=df_plot["nome"],
                orientation="h",
                marker_color=COR_GRAFICO,
                text=[f"{p:.2f}%" for p in df_plot["percentual_validos"]],
                textposition="outside",
                textfont={"family": "Montserrat", "color": EIXO["tinta"]},
                hovertext=[
                    f"{n} — {fmt(v)} votos"
                    for n, v in zip(df_plot["nome"], df_plot["votos"])
                ],
                hoverinfo="text",
            )
        )
        # Teto do eixo com folga: sem isso, o rótulo "outside" da barra líder
        # (perto de 100% da largura) fica cortado pela borda do gráfico / atrás
        # da barra de ferramentas do Plotly.
        maior_pct = float(df_plot["percentual_validos"].max())
        teto_eixo = min(100, maior_pct * 1.22)

        fig.update_layout(
            height=max(320, 56 * len(df_plot)),
            # margem inferior maior: com b=10 o título do eixo ("% dos votos
            # válidos") não tinha espaço próprio e ficava sobreposto aos
            # números do eixo (0, 10, 20...).
            margin=dict(l=10, r=40, t=10, b=50),
            xaxis_title="% dos votos válidos",
            yaxis_title=None,
            plot_bgcolor=EIXO["gelo"],
            paper_bgcolor=EIXO["gelo"],
            font={"family": "Montserrat", "size": 12, "color": EIXO["tinta"]},
        )
        fig.update_xaxes(title_standoff=14)
        # automargin: a margem esquerda passa a ser calculada pelo tamanho real
        # do nome mais longo, em vez do valor fixo acima — sem isso, nomes
        # compridos ("SORAYA THRONICKE" etc.) vazam pra fora da área visível.
        fig.update_yaxes(automargin=True)
        fig.update_xaxes(gridcolor=EIXO["borda"], zeroline=False, range=[0, teto_eixo])
        st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})

    with abas[1]:
        df_tabela = df
        tem_clientes = "clientes" in df.columns
        if filtro_cliente and tem_clientes:
            df_tabela = df[df["clientes"].apply(lambda cs: filtro_cliente in cs)]
            st.caption(f"Filtrado por cliente: **{filtro_cliente}** — {len(df_tabela)} de {len(df)} candidatos.")
            if df_tabela.empty:
                st.info(f'Nenhum candidato marcado de interesse do cliente "{filtro_cliente}" nesta corrida.')

        linhas_html = ""
        for _, row in df_tabela.iterrows():
            marcadores_cliente = (
                "".join(f'<span class="tse-badge-cliente">🔖 {esc(c)}</span>' for c in row["clientes"])
                if tem_clientes and row["clientes"]
                else ""
            )
            linhas_html += f"""
<tr>
  <td>
    <div class="tse-snap-cand">№ {esc(row['numero'])} · {esc(row['nome'])}{badge_html(row['situacao'])}</div>
    {f'<div style="margin-top:3px;">{marcadores_cliente}</div>' if marcadores_cliente else ''}
    <div class="tse-snap-sub">{esc(row['coligacao'])}</div>
  </td>
  <td>{esc(row['vice']) or '—'}</td>
  <td class="tse-num">{fmt(row['votos'])}</td>
  <td class="tse-num">{row['percentual_validos']:.2f}%</td>
</tr>"""
        st.markdown(
            f"""
<div class="tse-snap-wrap">
  <table class="tse-snap-table">
    <thead>
      <tr>
        <th>Candidato · Coligação</th>
        <th>Vice</th>
        <th class="tse-num">Votos</th>
        <th class="tse-num">% válidos</th>
      </tr>
    </thead>
    <tbody>{linhas_html}</tbody>
  </table>
</div>""",
            unsafe_allow_html=True,
        )

    if tem_mapa:
        with abas[2]:
            render_mapa_apuracao(turno)

    if tem_legenda:
        with abas[2]:
            st.caption(
                "⚠️ Deputado Federal e Estadual são cargos PROPORCIONAIS — não é "
                "só \"quem tem mais voto se elege\". Primeiro se calcula o "
                "quociente eleitoral (votos válidos ÷ nº de vagas do estado), "
                "depois quantas vagas cada partido/federação atingiu com esse "
                "quociente (QP); as vagas que sobram vão pra quem tiver a maior "
                "média entre os que ainda não fecharam conta sozinhos. Por isso "
                "um candidato pode ter mais voto que outro e mesmo assim não se "
                "eleger — quem decide é a legenda, não só o indivíduo."
            )

            legenda_linhas = [
                (
                    "tse-badge-eleito",
                    "Eleito por QP",
                    "O partido/federação atingiu o quociente partidário (votos da "
                    "legenda ÷ quociente eleitoral) e esse candidato foi um dos mais "
                    "votados dentro dela — vaga garantida direto pela conta do partido.",
                ),
                (
                    "tse-badge-eleito",
                    "Eleito por média",
                    "Depois de distribuir as vagas por QP, sobram cadeiras. Elas vão, "
                    "uma a uma, pro partido com a maior média (votos ÷ vagas já "
                    "conquistadas + 1) entre os que ainda não bateram o quociente "
                    "sozinhos — e dentro dele, pro candidato mais votado disponível.",
                ),
                (
                    "tse-badge-suplente",
                    "Suplente",
                    "Não ficou com a vaga nesta apuração, mas entra na fila do "
                    "partido: se um eleito da mesma legenda sair (renúncia, "
                    "cassação, morte etc.), quem assume é o suplente mais bem "
                    "colocado.",
                ),
                (
                    "tse-badge-naoeleito",
                    "Não eleito",
                    "Nem ficou com a vaga nem como suplente — o partido/federação "
                    "não teve votação suficiente pra manter esse candidato na lista "
                    "de reserva.",
                ),
            ]
            linhas_html = "".join(
                f"""
<tr>
  <td><span class="tse-badge {cls}" style="margin-left:0;">{esc(rotulo)}</span></td>
  <td>{esc(explicacao)}</td>
</tr>"""
                for cls, rotulo, explicacao in legenda_linhas
            )
            st.markdown(
                f"""
<div class="tse-snap-wrap">
  <table class="tse-snap-table">
    <thead><tr><th>Badge</th><th>O que significa</th></tr></thead>
    <tbody>{linhas_html}</tbody>
  </table>
</div>""",
                unsafe_allow_html=True,
            )

            contagem = df["situacao"].value_counts()
            resumo = " · ".join(
                f"{contagem.get(rotulo, 0)} {rotulo.lower()}" for _, rotulo, _ in legenda_linhas
            )
            st.caption(f"Nesta UF agora: {resumo}.")

    if tem_tabela_uf:
        with abas[2]:
            st.caption(
                "⚠️ Resume as 27 corridas de uma vez, independente da UF "
                "escolhida no menu — cada linha é um estado, ordenada pelas "
                "seções mais apuradas primeiro. A barra mostra a fatia de "
                "votos válidos do 1º, 2º e 3º colocado; o resto (demais "
                "candidatos) fica em coral. As cores são só posição no "
                "estado (1º/2º/3º), não indicam partido."
            )
            try:
                df_uf = carregar_tabela_uf(cargo_cod, turno)
            except requests.RequestException as e:
                st.error(f"Falha ao consultar o TSE: {e}")
                df_uf = None

            if df_uf is not None and not df_uf.empty:
                df_uf = df_uf.sort_values("secoes_totalizadas_pct", ascending=False, na_position="last")
                cores_rank = [EIXO["vinho"], EIXO["marinho"], EIXO["amarelo"]]
                linhas_html = ""
                for r in df_uf.itertuples():
                    if r.cand1_nome is None:
                        linhas_html += f"""
<tr>
  <td class="tse-snap-cand">{esc(r.uf)}</td>
  <td colspan="2"><span class="tse-snap-sub">Sem resposta do TSE ainda</span></td>
  <td class="tse-num"><span class="tse-uf-apuracao">—</span></td>
</tr>"""
                        continue

                    cands_html = ""
                    barra_html = ""
                    soma_pct = 0.0
                    for i in range(1, 4):
                        nome = getattr(r, f"cand{i}_nome")
                        pct = getattr(r, f"cand{i}_pct")
                        if nome is None or pct is None:
                            continue
                        cor = cores_rank[i - 1]
                        cands_html += (
                            f'<div class="tse-uf-cand">'
                            f'<span class="tse-uf-dot" style="background:{cor};"></span>'
                            f'<span class="tse-uf-cand-nome">{esc(nome)}</span>'
                            f'<span class="tse-tabnum">{pct:.1f}%</span>'
                            f"</div>"
                        )
                        barra_html += f'<div class="tse-uf-bar-seg" style="width:{pct}%;background:{cor};"></div>'
                        soma_pct += pct
                    resto = max(0.0, 100.0 - soma_pct)
                    barra_html += (
                        f'<div class="tse-uf-bar-seg" style="width:{resto}%;background:{EIXO["coral"]};"></div>'
                    )

                    apuracao_txt = (
                        f"{r.secoes_totalizadas_pct:.1f}%" if pd.notna(r.secoes_totalizadas_pct) else "—"
                    )
                    linhas_html += f"""
<tr>
  <td class="tse-snap-cand">{esc(r.uf)}</td>
  <td><div class="tse-uf-cands">{cands_html}</div></td>
  <td><div class="tse-uf-bar-wrap">{barra_html}</div></td>
  <td class="tse-num"><span class="tse-uf-apuracao">{apuracao_txt}</span></td>
</tr>"""

                st.markdown(
                    f"""
<div class="tse-snap-wrap">
  <table class="tse-snap-table tse-uf-table">
    <thead>
      <tr>
        <th>UF</th>
        <th>Candidatos</th>
        <th>Distribuição de votos</th>
        <th class="tse-num">Seções apuradas</th>
      </tr>
    </thead>
    <tbody>{linhas_html}</tbody>
  </table>
</div>""",
                    unsafe_allow_html=True,
                )

    if tem_grade_governos:
        with abas[3]:
            st.caption(
                "⚠️ \"Quem ocupa hoje\" é o líder atual da apuração ao vivo, "
                "não o titular anterior à eleição — essa informação não vem "
                "dos arquivos do TSE. Resolve o turno certo por estado (2º "
                "turno quando o estado precisou dele), não o turno escolhido "
                "no menu — senão um estado decidido só no 2º turno apareceria "
                "como \"em disputa\" mesmo já resolvido."
            )
            try:
                df_grade = carregar_governador_final_uf()
            except requests.RequestException as e:
                st.error(f"Falha ao consultar o TSE: {e}")
                df_grade = None

            if df_grade is not None and not df_grade.empty:
                def _status_uf(situacao):
                    if situacao is None:
                        return "sem_dados"
                    if str(situacao).startswith("Eleito"):
                        return "decidido"
                    return "disputa"

                status_cores = {"decidido": EIXO["vinho"], "disputa": EIXO["marinho"], "sem_dados": EIXO["borda"]}
                status_labels = {"decidido": "Decidido", "disputa": "Em disputa", "sem_dados": "Sem dados ainda"}
                status_idx = {"decidido": 0, "disputa": 1, "sem_dados": 2}

                df_grade = df_grade.copy()
                df_grade["status"] = df_grade["vencedor_situacao"].apply(_status_uf)

                geo = carregar_geojson_uf()
                colorscale = []
                for status_key, i in status_idx.items():
                    cor = status_cores[status_key]
                    colorscale.append([i / 3, cor])
                    colorscale.append([(i + 1) / 3, cor])

                fig_grade = go.Figure(
                    go.Choroplethmap(
                        geojson=geo,
                        featureidkey="properties.sigla",
                        locations=df_grade["uf"],
                        z=[status_idx[s] + 0.5 for s in df_grade["status"]],
                        zmin=0,
                        zmax=3,
                        colorscale=colorscale,
                        showscale=False,
                        marker_line_color="#ffffff",
                        marker_line_width=1,
                        customdata=df_grade[["uf", "vencedor", "vencedor_pct", "turno_final"]].fillna("—"),
                        hovertemplate=(
                            "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                            "%{customdata[2]}% · %{customdata[3]}º turno<extra></extra>"
                        ),
                    )
                )
                for status_key in ("decidido", "disputa", "sem_dados"):
                    fig_grade.add_trace(
                        go.Scattermap(
                            lat=[None], lon=[None], mode="markers",
                            marker=dict(size=10, color=status_cores[status_key]),
                            name=status_labels[status_key], showlegend=True,
                        )
                    )
                fig_grade.update_layout(
                    height=460,
                    margin=dict(l=0, r=0, t=0, b=0),
                    paper_bgcolor=EIXO["gelo"],
                    font={"family": "Montserrat", "color": EIXO["tinta"]},
                    map_style="white-bg",
                    map_zoom=2.9,
                    map_center={"lat": -14, "lon": -55},
                    legend=dict(orientation="h", y=-0.02, font={"family": "Montserrat", "size": 11}),
                )
                st.plotly_chart(fig_grade, width="stretch", theme=None, config={"displayModeBar": False})

                st.markdown('<div class="tse-pos-cat">Lista de governos estaduais</div>', unsafe_allow_html=True)
                linhas_lista = ""
                for r in df_grade.sort_values("uf").itertuples():
                    status = _status_uf(r.vencedor_situacao)
                    badge = (
                        '<span class="tse-badge tse-badge-eleito">Decidido</span>'
                        if status == "decidido"
                        else '<span class="tse-badge tse-badge-2turno">Em disputa</span>'
                        if status == "disputa"
                        else '<span class="tse-badge tse-badge-naoeleito">Sem dados</span>'
                    )
                    nome_txt = esc(r.vencedor) if r.vencedor else "—"
                    colig_txt = esc(r.vencedor_coligacao) if r.vencedor_coligacao else "—"
                    linhas_lista += f"""
<tr>
  <td class="tse-snap-cand">{esc(r.uf)}</td>
  <td>{nome_txt}</td>
  <td>{colig_txt}</td>
  <td>{badge}</td>
</tr>"""
                st.markdown(
                    f"""
<div class="tse-snap-wrap">
  <table class="tse-snap-table">
    <thead>
      <tr>
        <th>UF</th>
        <th>Quem ocupa hoje</th>
        <th>Coligação</th>
        <th>Situação</th>
      </tr>
    </thead>
    <tbody>{linhas_lista}</tbody>
  </table>
</div>""",
                    unsafe_allow_html=True,
                )


@st.cache_resource(show_spinner=False)
def carregar_geojson_uf():
    """
    Malha estadual do IBGE (baixada uma vez e salva localmente no projeto —
    não depende de nenhum CDN externo estar de pé no dia da eleição).
    O arquivo só tem "codarea" (código numérico do IBGE) nas properties;
    aqui a gente enriquece cada feature com a sigla da UF pra poder casar
    direto com os dados do TSE.
    """
    with open(GEOJSON_UF_PATH, encoding="utf-8") as f:
        geo = json.load(f)
    for feat in geo["features"]:
        codarea = feat["properties"]["codarea"]
        feat["properties"]["sigla"] = IBGE_CODAREA_UF.get(codarea, "")
    return geo


def render_mapa_apuracao(turno: int):
    # Chamada de dentro da aba do painel() (que já é um fragment de 60s) —
    # por isso não é fragment própria (Streamlit não suporta fragment
    # aninhado em fragment). Quem segura a atualização mais lenta é só o
    # cache de carregar_mapa() (ttl = REFRESH_MAPA_SEGUNDOS), então mesmo
    # redesenhando a cada 60s o mapa só busca o TSE de novo a cada poucos
    # minutos.
    st.caption(
        "⚠️ Só existe para Presidente: Governador e Senador são eleições "
        "próprias de cada UF, então não há o que comparar entre estados "
        f"nelas. Os dados do mapa são cacheados por {REFRESH_MAPA_SEGUNDOS // 60} "
        "min (mais devagar que o resto do painel, já que busca as 27 UFs)."
    )

    try:
        df_uf = carregar_mapa(turno)
    except requests.RequestException as e:
        st.error(f"Falha ao consultar o TSE: {e}")
        return

    geo = carregar_geojson_uf()
    df_validas = df_uf.dropna(subset=["secoes_totalizadas_pct"])
    if df_validas.empty:
        st.warning("Nenhuma UF respondeu ainda — tente atualizar em instantes.")
        return

    # go.Choropleth (o trace "geo" clássico) renderiza esse geojson errado —
    # em vez de colorir só os 27 estados, uma UF aleatória (a última da
    # lista) acaba pintando o retângulo inteiro do mapa também. Reproduzi
    # isso com o geojson oficial de exemplo do Plotly pra confirmar que não
    # é um problema dos nossos dados, e sim do trace clássico com essa
    # malha. go.Choroplethmap (vetorial, mais novo) não tem esse bug.
    fig = go.Figure(
        go.Choroplethmap(
            geojson=geo,
            featureidkey="properties.sigla",
            locations=df_validas["uf"],
            z=df_validas["secoes_totalizadas_pct"],
            zmin=0,
            zmax=100,
            colorscale=[[0, EIXO["gelo"]], [1, EIXO["marinho"]]],
            marker_line_color="#ffffff",
            marker_line_width=1,
            colorbar=dict(
                title=dict(text="% totalizado", font={"family": "Montserrat", "size": 11}),
                tickfont={"family": "Montserrat", "size": 10},
                ticksuffix="%",
            ),
            customdata=df_validas[["uf", "comparecimento_pct"]],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Seções totalizadas: %{z:.2f}%<br>"
                "Comparecimento: %{customdata[1]:.2f}%<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        height=520,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor=EIXO["gelo"],
        font={"family": "Montserrat", "color": EIXO["tinta"]},
        map_style="white-bg",
        map_zoom=2.9,
        map_center={"lat": -14, "lon": -55},
    )
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})

    faltando = df_uf[df_uf["secoes_totalizadas_pct"].isna()]
    if not faltando.empty:
        st.caption(
            "Sem resposta do TSE ainda para: " + ", ".join(faltando["uf"].tolist())
        )


if pagina == "Apuração ao vivo":
    st.markdown(f'<div class="tse-page-title">{esc(cargo_nome)} · {esc(uf.upper())}</div>', unsafe_allow_html=True)
    painel(cargo_nome, cargo_cod, uf, turno, filtro_cliente)
elif pagina == "Pós-eleição":
    render_pos_eleicao()
elif pagina == "Interesse dos clientes":
    render_interesse_clientes()
else:
    render_senado_2026()
