"""
Sistema de Previsões e Palpites para Basquete (NBA)
====================================================
Usa a API BallDontLie para buscar jogos e histórico,
aplica modelo probabilístico simples e gera predictions_nba.json.

Segue o mesmo padrão de dois estágios do predictor.py:
  - Run completo (1x por dia): análise + exporta
  - Run leve (demais runs): só atualiza placar/status
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional, List, Tuple
from dataclasses import dataclass, asdict, field

import requests

# ── Constantes da API ──────────────────────────────────────────────
NBA_API_BASE = "https://api.balldontlie.io/v1"
NBA_API_KEY = os.getenv("BALLDONTLIE_API_KEY", "").strip()
NBA_HEADERS = {"Authorization": NBA_API_KEY}

# ── Constantes do modelo ───────────────────────────────────────────
NBA_HOME_ADVANTAGE = 3.2      # pontos de vantagem média em casa
NBA_MEDIA_LIGA = 113.5        # média de pontos por jogo por time (NBA 2024)
NBA_HISTORICO_JOGOS = 15      # últimos N jogos para calcular médias
NBA_SHRINKAGE_K = 8           # jogos para peso total no shrinkage
NBA_SHRINKAGE_MIN = 0.25
NBA_STD_SPREAD = 11.0         # desvio padrão histórico de spread NBA
NBA_CLAMP_MIN = 85.0
NBA_CLAMP_MAX = 145.0

# ── Timezone ───────────────────────────────────────────────────────
def _carregar_timezone() -> timezone:
    key = os.getenv("APP_TIMEZONE", "America/Sao_Paulo")
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, Exception):
        print(f"WARNING: timezone '{key}' indisponivel. Usando UTC-03:00.")
        return timezone(timedelta(hours=-3))

APP_TIMEZONE = _carregar_timezone()


# ── Dataclass ──────────────────────────────────────────────────────
@dataclass
class PredicaoJogoNBA:
    game_id: int
    data_jogo: str
    time_casa: str
    time_visitante: str
    abrev_casa: str
    abrev_visitante: str
    conference_casa: str
    conference_visitante: str
    status: str
    status_original: str
    periodo_atual: int
    tempo_periodo: str
    placar_casa: Optional[int]
    placar_visitante: Optional[int]
    quarters_casa: List[Optional[int]]
    quarters_visitante: List[Optional[int]]
    pts_esperados_casa: float
    pts_esperados_visitante: float
    prob_casa: float
    prob_visitante: float
    spread_esperado: float
    forma_casa: float
    forma_visitante: float
    temporada: int
    palpites: List[dict] = field(default_factory=list)
    leitura_rapida: str = ""


# ── Helpers ────────────────────────────────────────────────────────
def temporada_nba_atual() -> int:
    agora = datetime.now(timezone.utc)
    return agora.year if agora.month >= 10 else agora.year - 1


def _mapear_status_nba(status_api: str, period: int) -> str:
    if status_api == "Final":
        return "FINISHED"
    if any(k in status_api for k in ("Qtr", "Halftime", "OT")):
        return "IN_PLAY"
    return "SCHEDULED"


def prob_vitoria_casa(spread: float, std: float = NBA_STD_SPREAD) -> float:
    """Aproximação da CDF normal via logística (sem scipy)."""
    x = spread / std
    return 1.0 / (1.0 + (2.718281828 ** (-1.702 * x)))


def _media_com_shrinkage(media_time: float, media_liga: float, n_jogos: int) -> float:
    """Suaviza a média do time em direção à média da liga com base em n_jogos."""
    peso = min(1.0, n_jogos / NBA_SHRINKAGE_K)
    peso = max(NBA_SHRINKAGE_MIN, peso)
    return peso * media_time + (1.0 - peso) * media_liga


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _forma_recente(jogos: list, team_id: int) -> float:
    """Calcula índice de forma 0.0–1.0 dos últimos 5 jogos com peso decrescente."""
    pesos = [1.0, 0.85, 0.70, 0.55, 0.40]
    resultados = []
    for jogo in jogos[:5]:
        home_id = jogo.get("home_team", {}).get("id")
        home_score = jogo.get("home_team_score") or 0
        visit_score = jogo.get("visitor_team_score") or 0
        if team_id == home_id:
            resultados.append(1.0 if home_score > visit_score else 0.0)
        else:
            resultados.append(1.0 if visit_score > home_score else 0.0)
    if not resultados:
        return 0.5
    total_peso = sum(pesos[i] for i in range(len(resultados)))
    soma = sum(resultados[i] * pesos[i] for i in range(len(resultados)))
    return soma / total_peso if total_peso > 0 else 0.5


# ── Chamadas à API ─────────────────────────────────────────────────
def _api_get(path: str, params: dict = None, retries: int = 3) -> Optional[dict]:
    if not NBA_API_KEY:
        print("ERRO: BALLDONTLIE_API_KEY não definida.")
        return None
    url = f"{NBA_API_BASE}{path}"
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=NBA_HEADERS, params=params, timeout=15)
            if resp.status_code == 429:
                print("Rate limit atingido. Aguardando 60s...")
                time.sleep(60)
                continue
            if resp.status_code == 401:
                print("ERRO: API Key inválida ou sem permissão.")
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            print(f"AVISO: Tentativa {attempt + 1}/{retries} falhou: {exc}")
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    return None


def buscar_jogos_nba_dia() -> list:
    """Busca jogos da NBA para hoje (horário local)."""
    hoje = datetime.now(APP_TIMEZONE).date().isoformat()
    print(f"🏀 Buscando jogos NBA para {hoje}...")
    data = _api_get("/games", params={"dates[]": hoje, "per_page": 100})
    if not data:
        return []
    jogos = [j for j in (data.get("data") or []) if not j.get("postponed")]
    print(f"   {len(jogos)} jogo(s) encontrado(s).")
    return jogos


def buscar_historico_time_nba(team_id: int, season: int) -> list:
    """Busca os últimos N jogos de um time na temporada."""
    data = _api_get(
        "/games",
        params={
            "team_ids[]": team_id,
            "seasons[]": season,
            "per_page": NBA_HISTORICO_JOGOS,
        },
    )
    if not data:
        return []
    jogos = [j for j in (data.get("data") or []) if j.get("status") == "Final"]
    jogos.sort(key=lambda j: j.get("date", ""), reverse=True)
    return jogos[:NBA_HISTORICO_JOGOS]


def calcular_media_pontos(historico: list, team_id: int) -> Tuple[float, float, int]:
    """Retorna (media_marcados, media_sofridos, n_jogos) para um time."""
    marcados = []
    sofridos = []
    for jogo in historico:
        home_id = jogo.get("home_team", {}).get("id")
        hs = jogo.get("home_team_score") or 0
        vs = jogo.get("visitor_team_score") or 0
        if team_id == home_id:
            marcados.append(hs)
            sofridos.append(vs)
        else:
            marcados.append(vs)
            sofridos.append(hs)
    n = len(marcados)
    if n == 0:
        return NBA_MEDIA_LIGA, NBA_MEDIA_LIGA, 0
    return sum(marcados) / n, sum(sofridos) / n, n


# ── Modelo de predição ─────────────────────────────────────────────
def analisar_jogo_nba(jogo: dict) -> Optional[PredicaoJogoNBA]:
    """Analisa um jogo e retorna uma PredicaoJogoNBA completa."""
    home_team = jogo.get("home_team", {})
    visit_team = jogo.get("visitor_team", {})
    home_id = home_team.get("id")
    visit_id = visit_team.get("id")

    if not home_id or not visit_id:
        return None

    season = temporada_nba_atual()
    print(f"   Analisando: {home_team.get('full_name')} x {visit_team.get('full_name')}...")

    hist_casa = buscar_historico_time_nba(home_id, season)
    time.sleep(1)
    hist_visit = buscar_historico_time_nba(visit_id, season)
    time.sleep(1)

    med_marc_casa, med_sofr_casa, n_casa = calcular_media_pontos(hist_casa, home_id)
    med_marc_visit, med_sofr_visit, n_visit = calcular_media_pontos(hist_visit, visit_id)

    # Shrinkage em direção à média da liga
    med_marc_casa = _media_com_shrinkage(med_marc_casa, NBA_MEDIA_LIGA, n_casa)
    med_marc_visit = _media_com_shrinkage(med_marc_visit, NBA_MEDIA_LIGA, n_visit)
    med_sofr_casa = _media_com_shrinkage(med_sofr_casa, NBA_MEDIA_LIGA, n_casa)
    med_sofr_visit = _media_com_shrinkage(med_sofr_visit, NBA_MEDIA_LIGA, n_visit)

    # Pontos esperados (modelo multiplicativo com vantagem de casa)
    pts_casa = (med_marc_casa * (med_sofr_visit / NBA_MEDIA_LIGA)) + NBA_HOME_ADVANTAGE
    pts_visit = med_marc_visit * (med_sofr_casa / NBA_MEDIA_LIGA)

    pts_casa = _clamp(pts_casa, NBA_CLAMP_MIN, NBA_CLAMP_MAX)
    pts_visit = _clamp(pts_visit, NBA_CLAMP_MIN, NBA_CLAMP_MAX)

    spread = pts_casa - pts_visit
    prob_casa = prob_vitoria_casa(spread)
    prob_visit = 1.0 - prob_casa

    forma_casa = _forma_recente(hist_casa, home_id)
    forma_visit = _forma_recente(hist_visit, visit_id)

    # Status e placar
    status_api = jogo.get("status", "")
    status_interno = _mapear_status_nba(status_api, jogo.get("period", 0))

    placar_casa: Optional[int] = None
    placar_visit: Optional[int] = None
    if status_interno in ("IN_PLAY", "FINISHED"):
        raw_hs = jogo.get("home_team_score")
        raw_vs = jogo.get("visitor_team_score")
        if raw_hs is not None:
            placar_casa = int(raw_hs)
        if raw_vs is not None:
            placar_visit = int(raw_vs)

    quarters_casa = [
        jogo.get("home_q1"), jogo.get("home_q2"),
        jogo.get("home_q3"), jogo.get("home_q4"),
    ]
    quarters_visit = [
        jogo.get("visitor_q1"), jogo.get("visitor_q2"),
        jogo.get("visitor_q3"), jogo.get("visitor_q4"),
    ]

    # Data ISO
    data_raw = jogo.get("date", "")
    try:
        if "T" in data_raw:
            data_iso = data_raw
        else:
            data_iso = data_raw + "T00:00:00.000Z"
    except Exception:
        data_iso = data_raw

    pred = PredicaoJogoNBA(
        game_id=jogo.get("id", 0),
        data_jogo=data_iso,
        time_casa=home_team.get("full_name", ""),
        time_visitante=visit_team.get("full_name", ""),
        abrev_casa=home_team.get("abbreviation", ""),
        abrev_visitante=visit_team.get("abbreviation", ""),
        conference_casa=home_team.get("conference", ""),
        conference_visitante=visit_team.get("conference", ""),
        status=status_interno,
        status_original=status_api,
        periodo_atual=jogo.get("period", 0),
        tempo_periodo=(jogo.get("time") or "").strip(),
        placar_casa=placar_casa,
        placar_visitante=placar_visit,
        quarters_casa=quarters_casa,
        quarters_visitante=quarters_visit,
        pts_esperados_casa=round(pts_casa, 1),
        pts_esperados_visitante=round(pts_visit, 1),
        prob_casa=round(prob_casa, 4),
        prob_visitante=round(prob_visit, 4),
        spread_esperado=round(spread, 1),
        forma_casa=round(forma_casa, 3),
        forma_visitante=round(forma_visit, 3),
        temporada=season,
    )
    pred.palpites = gerar_palpites_nba(pred)
    pred.leitura_rapida = _gerar_leitura_rapida_nba(pred)
    return pred


def gerar_palpites_nba(pred: "PredicaoJogoNBA") -> list:
    """Gera lista de palpites para um jogo NBA."""
    palpites = []

    # ── WINNER ──────────────────────────────────────────────────────
    edge_winner = abs(pred.prob_casa - pred.prob_visitante)
    conf_winner = "HIGH" if edge_winner >= 0.30 else "MEDIUM" if edge_winner >= 0.15 else "LOW"
    if pred.prob_casa >= pred.prob_visitante:
        opcao_winner = "CASA"
        prob_winner = pred.prob_casa
        nome_winner = pred.time_casa
    else:
        opcao_winner = "VISIT"
        prob_winner = pred.prob_visitante
        nome_winner = pred.time_visitante
    palpites.append({
        "tipo": "WINNER",
        "opcao": opcao_winner,
        "probabilidade": round(prob_winner, 4),
        "confianca": conf_winner,
        "justificativa": f"{nome_winner} favorito com {round(prob_winner * 100, 1)}% de chance (spread esperado: {pred.spread_esperado:+.1f} pts).",
        "edge": round(edge_winner, 4),
        "resultado_verificador": None,
    })

    # ── OVER/UNDER ──────────────────────────────────────────────────
    total_esperado = pred.pts_esperados_casa + pred.pts_esperados_visitante
    # Linha dinâmica arredondada para 0.5
    linha = round(total_esperado * 2) / 2
    if linha == round(total_esperado):
        linha += 0.5
    prob_over = prob_vitoria_casa((total_esperado - linha) / 8.0)
    prob_under = 1.0 - prob_over
    opcao_ou = "OVER" if prob_over >= prob_under else "UNDER"
    prob_ou = prob_over if opcao_ou == "OVER" else prob_under
    edge_ou = abs(prob_over - prob_under)
    conf_ou = "HIGH" if edge_ou >= 0.25 else "MEDIUM" if edge_ou >= 0.12 else "LOW"
    palpites.append({
        "tipo": "OVER_UNDER",
        "opcao": opcao_ou,
        "linha": linha,
        "probabilidade": round(prob_ou, 4),
        "confianca": conf_ou,
        "justificativa": f"Total esperado de {total_esperado:.1f} pts. Linha: {linha}. Tendência de {opcao_ou}.",
        "edge": round(edge_ou, 4),
        "resultado_verificador": None,
    })

    # ── SPREAD ──────────────────────────────────────────────────────
    spread_abs = abs(pred.spread_esperado)
    conf_spread = "HIGH" if spread_abs >= 8 else "MEDIUM" if spread_abs >= 4 else "LOW"
    if pred.spread_esperado >= 0:
        opcao_spread = f"+{spread_abs:.1f}"
        desc_spread = f"{pred.time_casa} favorito por ~{spread_abs:.1f} pontos."
    else:
        opcao_spread = f"-{spread_abs:.1f}"
        desc_spread = f"{pred.time_visitante} favorito por ~{spread_abs:.1f} pontos."
    palpites.append({
        "tipo": "SPREAD",
        "opcao": opcao_spread,
        "probabilidade": round(max(pred.prob_casa, pred.prob_visitante), 4),
        "confianca": conf_spread,
        "justificativa": desc_spread,
        "edge": round(spread_abs / 20.0, 4),
        "resultado_verificador": None,
    })

    return palpites


def _gerar_leitura_rapida_nba(pred: "PredicaoJogoNBA") -> str:
    fav = pred.time_casa if pred.prob_casa >= pred.prob_visitante else pred.time_visitante
    prob_fav = max(pred.prob_casa, pred.prob_visitante)
    total = pred.pts_esperados_casa + pred.pts_esperados_visitante
    return (
        f"{fav} favorito com {round(prob_fav * 100, 1)}% de chance. "
        f"Spread esperado de {abs(pred.spread_esperado):.1f} pts. "
        f"Total projetado: {total:.1f} pts."
    )


# ── Verificação de resultados ──────────────────────────────────────
def _verificar_palpite_nba(palpite: dict, placar_casa: int, placar_visit: int) -> str:
    tipo = palpite.get("tipo", "")
    opcao = palpite.get("opcao", "")
    if tipo == "WINNER":
        vencedor = "CASA" if placar_casa > placar_visit else "VISIT"
        return "ACERTO" if opcao == vencedor else "ERRO"
    if tipo == "OVER_UNDER":
        linha = palpite.get("linha", 220.5)
        total_real = placar_casa + placar_visit
        resultado = "OVER" if total_real > linha else "UNDER"
        return "ACERTO" if opcao == resultado else "ERRO"
    if tipo == "SPREAD":
        spread_real = placar_casa - placar_visit
        spread_esperado = palpite.get("spread_esperado", 0)
        # Verifica se a casa cobriu o spread esperado
        if spread_esperado >= 0:
            return "ACERTO" if spread_real >= 0 else "ERRO"
        else:
            return "ACERTO" if spread_real < 0 else "ERRO"
    return "PENDENTE"


# ── Exportação ─────────────────────────────────────────────────────
def _pred_para_dict(pred: PredicaoJogoNBA) -> dict:
    total_pts = pred.pts_esperados_casa + pred.pts_esperados_visitante
    # Linha de over/under do palpite correspondente
    ou_palpite = next((p for p in pred.palpites if p["tipo"] == "OVER_UNDER"), {})
    over_linha = ou_palpite.get("linha", round(total_pts * 2) / 2)
    prob_over = ou_palpite.get("probabilidade", 0.5) if ou_palpite.get("opcao") == "OVER" else 1 - ou_palpite.get("probabilidade", 0.5)

    fav_nome = pred.time_casa if pred.prob_casa >= pred.prob_visitante else pred.time_visitante
    fav_prob = max(pred.prob_casa, pred.prob_visitante)
    fav_vantagem = abs(pred.prob_casa - pred.prob_visitante)

    return {
        "game_id": pred.game_id,
        "competicao": "NBA",
        "data": pred.data_jogo,
        "status": pred.status,
        "status_display": pred.status_original,
        "periodo": pred.periodo_atual,
        "tempo": pred.tempo_periodo,
        "times": {
            "casa": pred.time_casa,
            "visitante": pred.time_visitante,
            "abrev_casa": pred.abrev_casa,
            "abrev_visit": pred.abrev_visitante,
        },
        "placar_casa": pred.placar_casa,
        "placar_visitante": pred.placar_visitante,
        "quarters": {
            "casa": pred.quarters_casa,
            "visitante": pred.quarters_visitante,
        },
        "probabilidades": {
            "casa": pred.prob_casa,
            "visitante": pred.prob_visitante,
        },
        "favorito": {
            "nome": fav_nome,
            "prob": round(fav_prob, 4),
            "vantagem": round(fav_vantagem, 4),
        },
        "pts_esperados": {
            "casa": pred.pts_esperados_casa,
            "visitante": pred.pts_esperados_visitante,
            "total": round(total_pts, 1),
        },
        "spread_esperado": pred.spread_esperado,
        "mercados": {
            "over_linha": over_linha,
            "prob_over": round(prob_over, 4),
            "prob_under": round(1.0 - prob_over, 4),
        },
        "forma": {
            "casa": pred.forma_casa,
            "visitante": pred.forma_visitante,
        },
        "leitura_rapida": pred.leitura_rapida,
        "palpites": pred.palpites,
    }


def exportar_nba(predicoes: List[PredicaoJogoNBA], caminho: str) -> None:
    hoje = datetime.now(APP_TIMEZONE).date().isoformat()
    agora = datetime.now(APP_TIMEZONE).isoformat(timespec="seconds")
    season = temporada_nba_atual()

    jogos = [_pred_para_dict(p) for p in predicoes]

    # Selecionar dicas do dia: top 3 por probabilidade do favorito (excluindo finalizados)
    candidatos = [j for j in jogos if j["status"] != "FINISHED"]
    candidatos.sort(key=lambda j: j["favorito"]["prob"], reverse=True)
    daily_tips_ids = [
        {"casa": j["times"]["casa"], "visitante": j["times"]["visitante"], "data": j["data"]}
        for j in candidatos[:3]
    ]

    # Acertos do dia
    finalizados = [j for j in jogos if j["status"] == "FINISHED"]
    total_palpites = 0
    acertos = 0
    for jogo in finalizados:
        for p in jogo.get("palpites", []):
            if p.get("resultado_verificador") in ("ACERTO", "ERRO"):
                total_palpites += 1
                if p["resultado_verificador"] == "ACERTO":
                    acertos += 1
    taxa = round(acertos / total_palpites, 4) if total_palpites > 0 else None

    saida = {
        "generated_at": agora,
        "analysis_date": hoje,
        "total_jogos": len(jogos),
        "temporada": season,
        "jogos": jogos,
        "daily_tips_ids": daily_tips_ids,
        "daily_tips_date": hoje,
        "recovery_tip": {"ativo": False},
        "acertos_hoje": {"acertos": acertos, "total": total_palpites, "taxa": taxa},
    }

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    print(f"✅ {caminho} gerado com {len(jogos)} jogo(s).")


# ── Run leve: atualização de status/placar ─────────────────────────
def _atualizar_historico_nba_do_json(dados_predictions: dict, caminho_historico: str) -> None:
    """Atualiza history_nba.json usando o conteúdo atual de predictions_nba.json.

    Usado no run leve para refletir imediatamente ACERTO/ERRO dos jogos finalizados.
    """
    try:
        with open(caminho_historico, "r", encoding="utf-8") as f:
            historico = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        historico = {"dias": []}

    hoje = datetime.now(APP_TIMEZONE).date().isoformat()
    dias = historico.get("dias", [])
    dias = [d for d in dias if d.get("data") != hoje]

    jogos = dados_predictions.get("jogos", []) or []
    jogos_hoje = []
    total_p = 0
    acertos = 0

    for jogo in jogos:
        palpites_saida = []
        for p in jogo.get("palpites", []) or []:
            resultado = p.get("resultado_verificador")
            if resultado in ("ACERTO", "ERRO"):
                total_p += 1
                if resultado == "ACERTO":
                    acertos += 1

            palpites_saida.append(
                {
                    "tipo": p.get("tipo"),
                    "opcao": p.get("opcao"),
                    "confianca": p.get("confianca"),
                    "resultado": resultado,
                }
            )

        jogos_hoje.append(
            {
                "game_id": jogo.get("game_id"),
                "casa": jogo.get("times", {}).get("casa", ""),
                "visitante": jogo.get("times", {}).get("visitante", ""),
                "placar": f"{jogo.get('placar_casa', '?')} x {jogo.get('placar_visitante', '?')}",
                "status": jogo.get("status", "SCHEDULED"),
                "palpites": palpites_saida,
            }
        )

    taxa = round(acertos / total_p, 4) if total_p > 0 else None
    entrada = {
        "data": hoje,
        "total_jogos": len(jogos),
        "total_palpites": total_p,
        "total_acertos": acertos,
        "taxa_geral": taxa,
        "jogos": jogos_hoje,
    }

    dias.insert(0, entrada)
    historico["dias"] = dias[:60]

    with open(caminho_historico, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)
    print(f"✅ {caminho_historico} atualizado (run leve).")


def atualizar_status_nba(caminho: str, caminho_historico: Optional[str] = None) -> None:
    print("🔄 Run leve NBA: atualizando status/placar...")

    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"AVISO: Não foi possível ler {caminho}: {exc}")
        return

    jogos = dados.get("jogos", [])
    if not jogos:
        print("   Nenhum jogo para atualizar.")
        return

    hoje = datetime.now(APP_TIMEZONE).date().isoformat()
    datas_unicas = {j["data"][:10] for j in jogos}
    
    # Incluir dia anterior para capturar jogos finalizados que ficaram pendentes
    data_anterior = (datetime.now(APP_TIMEZONE).date() - timedelta(days=1)).isoformat()
    datas_unicas.add(data_anterior)
    jogos_api: dict = {}

    for data_str in datas_unicas:
        resultado = _api_get("/games", params={"dates[]": data_str, "per_page": 100})
        if resultado:
            for jogo in (resultado.get("data") or []):
                jogos_api[jogo["id"]] = jogo
        time.sleep(1)

    alterado = False
    for jogo in jogos:
        jogo_id = jogo.get("game_id")
        api_jogo = jogos_api.get(jogo_id)
        if not api_jogo:
            continue

        novo_status = _mapear_status_nba(api_jogo.get("status", ""), api_jogo.get("period", 0))
        jogo["status"] = novo_status
        jogo["status_display"] = api_jogo.get("status", "")
        jogo["periodo"] = api_jogo.get("period", 0)
        jogo["tempo"] = (api_jogo.get("time") or "").strip()

        if novo_status in ("IN_PLAY", "FINISHED"):
            hs = api_jogo.get("home_team_score")
            vs = api_jogo.get("visitor_team_score")
            if hs is not None:
                jogo["placar_casa"] = int(hs)
            if vs is not None:
                jogo["placar_visitante"] = int(vs)

            # Quarters
            jogo["quarters"] = {
                "casa": [api_jogo.get("home_q1"), api_jogo.get("home_q2"),
                         api_jogo.get("home_q3"), api_jogo.get("home_q4")],
                "visitante": [api_jogo.get("visitor_q1"), api_jogo.get("visitor_q2"),
                              api_jogo.get("visitor_q3"), api_jogo.get("visitor_q4")],
            }

        # Verificar palpites se finalizado
        if novo_status == "FINISHED" and jogo.get("placar_casa") is not None:
            for palpite in jogo.get("palpites", []):
                if palpite.get("resultado_verificador") is None:
                    palpite["resultado_verificador"] = _verificar_palpite_nba(
                        palpite, jogo["placar_casa"], jogo["placar_visitante"]
                    )
        alterado = True

    if alterado:
        dados["generated_at"] = datetime.now(APP_TIMEZONE).isoformat(timespec="seconds")
        # Recalcular acertos do dia
        finalizados = [j for j in jogos if j["status"] == "FINISHED"]
        total_p = 0
        acertos = 0
        for jogo in finalizados:
            for p in jogo.get("palpites", []):
                if p.get("resultado_verificador") in ("ACERTO", "ERRO"):
                    total_p += 1
                    if p["resultado_verificador"] == "ACERTO":
                        acertos += 1
        taxa = round(acertos / total_p, 4) if total_p > 0 else None
        dados["acertos_hoje"] = {"acertos": acertos, "total": total_p, "taxa": taxa}

        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        print(f"   {caminho} atualizado.")

        if caminho_historico:
            _atualizar_historico_nba_do_json(dados, caminho_historico)
    else:
        print("   Nenhuma alteração encontrada.")


# ── Histórico ──────────────────────────────────────────────────────
def atualizar_historico_nba(predicoes: List[PredicaoJogoNBA], caminho: str) -> None:
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            historico = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        historico = {"dias": []}

    hoje = datetime.now(APP_TIMEZONE).date().isoformat()
    dias = historico.get("dias", [])

    # Remover entrada do dia atual se existir (será recriada)
    dias = [d for d in dias if d.get("data") != hoje]

    jogos_hoje = []
    for pred in predicoes:
        jogos_hoje.append({
            "game_id": pred.game_id,
            "casa": pred.time_casa,
            "visitante": pred.time_visitante,
            "placar": f"{pred.placar_casa or '?'} x {pred.placar_visitante or '?'}",
            "status": pred.status,
            "palpites": [
                {"tipo": p["tipo"], "opcao": p["opcao"], "confianca": p["confianca"],
                 "resultado": p.get("resultado_verificador")}
                for p in pred.palpites
            ],
        })

    total_p = sum(
        1 for pred in predicoes for p in pred.palpites
        if p.get("resultado_verificador") in ("ACERTO", "ERRO")
    )
    acertos = sum(
        1 for pred in predicoes for p in pred.palpites
        if p.get("resultado_verificador") == "ACERTO"
    )
    taxa = round(acertos / total_p, 4) if total_p > 0 else None

    entrada = {
        "data": hoje,
        "total_jogos": len(predicoes),
        "total_palpites": total_p,
        "total_acertos": acertos,
        "taxa_geral": taxa,
        "jogos": jogos_hoje,
    }
    dias.insert(0, entrada)
    historico["dias"] = dias[:60]  # Manter máximo 60 dias

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)
    print(f"✅ {caminho} atualizado.")


# ── main ───────────────────────────────────────────────────────────
def main() -> None:
    if not NBA_API_KEY:
        raise SystemExit(
            "Defina a variável de ambiente BALLDONTLIE_API_KEY antes de executar.\n"
            "Exemplo PowerShell: $env:BALLDONTLIE_API_KEY='sua_chave'"
        )

    caminho_pred = "predictions_nba.json"
    caminho_hist = "history_nba.json"
    hoje = datetime.now(APP_TIMEZONE).date().isoformat()

    # Verificar se análise completa do dia já foi feita
    analysis_done = False
    try:
        with open(caminho_pred, "r", encoding="utf-8") as f:
            existente = json.load(f)
        if existente.get("analysis_date") == hoje and existente.get("jogos"):
            analysis_done = True
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    if analysis_done:
        print("⚡ Run leve: análise completa já feita hoje.")
        atualizar_status_nba(caminho_pred, caminho_hist)
        return

    # Antes de fazer novo run completo, finalizar jogos pendentes do arquivo atual
    if os.path.exists(caminho_pred):
        print("📋 Finalizando jogos pendentes antes de novo run completo...")
        atualizar_status_nba(caminho_pred, caminho_hist)

    # Run completo
    print(f"🔍 Run completo NBA para {hoje}...")
    jogos = buscar_jogos_nba_dia()

    if not jogos:
        print("❌ Nenhum jogo NBA hoje. Exportando JSON vazio.")
        exportar_nba([], caminho_pred)
        return

    predicoes = []
    for jogo in jogos:
        pred = analisar_jogo_nba(jogo)
        if pred:
            predicoes.append(pred)
        time.sleep(6)

    exportar_nba(predicoes, caminho_pred)
    atualizar_historico_nba(predicoes, caminho_hist)


if __name__ == "__main__":
    main()
