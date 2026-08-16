from __future__ import annotations

import html as _html
import json
from datetime import datetime

import plotly.graph_objects as go
import requests
import streamlit as st

from tse_api import (
    CARGOS,
    CICLO,
    ELEICOES,
    IBGE_CODAREA_UF,
    UFS_ESTADUAIS,
    UFS_PRESIDENTE,
    obter_resultado,
    obter_secoes_totalizadas_por_uf,
)

# ─── Config ──────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Apuração TSE · Eleições 2022", layout="wide")

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
.tse-badge-naoeleito  {{ background: {EIXO["borda"]}; color: {EIXO["subtexto"]}; }}

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

with st.sidebar:
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


st.markdown(f'<div class="tse-page-title">{esc(cargo_nome)} · {esc(uf.upper())}</div>', unsafe_allow_html=True)


@st.fragment(run_every=REFRESH_SEGUNDOS)
def painel(cargo_nome: str, cargo_cod: str, uf: str, turno: int):
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

    st.caption(
        f"{cargo_nome} · {uf.upper()} · {turno}º turno  —  "
        f"dado gerado pelo TSE em {meta['data_geracao']} {meta['hora_geracao']}  ·  "
        f"consultado nesta página às {datetime.now():%H:%M:%S}"
    )

    badge_class = {
        "Eleito": "tse-badge-eleito",
        "2º turno": "tse-badge-2turno",
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
    <div class="tse-leader-pct">{lider['percentual_validos']:.2f}%</div>
    <div class="tse-leader-votos">{fmt(lider['votos'])} votos válidos</div>
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

    # --- Abas: cada uma é uma "mini página" ---
    nomes_abas = ["Distribuição dos votos", "Detalhamento por candidato"]
    tem_mapa = cargo_cod == "0001"
    if tem_mapa:
        nomes_abas.append("Apuração por UF — Presidente")
    abas = st.tabs(nomes_abas)

    with abas[0]:
        info_pct = (
            f"O percentual de cada candidato é calculado pelo TSE sobre os "
            f"votos válidos ({fmt(meta['votos_validos'])} votos, "
            f"{meta['votos_validos_pct']:.2f}% do comparecimento) — brancos e "
            f"nulos já saíram do denominador."
        )
        st.caption(f"⚠️ {info_pct}")

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
        linhas_html = ""
        for _, row in df.iterrows():
            linhas_html += f"""
<tr>
  <td>
    <div class="tse-snap-cand">№ {esc(row['numero'])} · {esc(row['nome'])}{badge_html(row['situacao'])}</div>
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


painel(cargo_nome, cargo_cod, uf, turno)
