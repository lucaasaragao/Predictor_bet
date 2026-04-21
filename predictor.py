"""
Sistema de Previsões e Palpites para Futebol
=============================================
Combina histórico, H2H, forma recente e modelo Poisson para gerar palpites.
"""

import json
import os

import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from math import factorial, e
from dataclasses import dataclass, asdict

TOKEN_ENV_VAR = "FOOTBALL_DATA_TOKEN"
TOKEN = os.getenv(TOKEN_ENV_VAR, "").strip()
if not TOKEN:
    raise SystemExit(
        "Defina a variavel de ambiente FOOTBALL_DATA_TOKEN antes de executar. "
        "Exemplo PowerShell: $env:FOOTBALL_DATA_TOKEN='seu_token'"
    )
HEADERS = {"X-Auth-Token": TOKEN}
API_BASE = "https://api.football-data.org/v4"

# Competições permitidas
COMPETICOES_PERMITIDAS = {
    "Campeonato Brasileiro Série A",
    "Campeonato Brasileiro Série B", 
    "UEFA Champions League",
    "Copa Libertadores",
    "Premier League",
    "Primera Division", # La Liga
    "Serie A",
    "Primeira Liga",
    "Championship", # Segunda divisão inglesa
}


@dataclass
class EstatisticaTime:
    """Estatísticas de um time em casa ou fora"""
    gols_marcados_media: float
    gols_sofridos_media: float
    escanteios_media: float
    cartoes_media: float
    jogos: int


@dataclass
class ScoreTempo:
    """Score de um jogo com análise temporal"""
    forma_recente: float       # 35%
    ataque: float              # 25%
    defesa: float              # 20%
    fator_mando: float         # 10%
    h2h_factor: float          # 10%
    score_total: float


@dataclass
class PredicaoJogo:
    """Previsão de um jogo"""
    data_jogo: str
    time_casa: str
    time_visitante: str
    status: str
    placar_casa: Optional[int]
    placar_visitante: Optional[int]
    prob_casa: float
    prob_empate: float
    prob_visitante: float
    gols_esperados_casa: float
    gols_esperados_visitante: float
    score_casa: ScoreTempo
    score_visitante: ScoreTempo
    competicao: str
    historico_casa: List[Dict]
    historico_visitante: List[Dict]
    tendencia_casa: str
    tendencia_visitante: str


@dataclass
class BetSuggestion:
    """Sugestão de aposta"""
    tipo: str                  # WINNER, OVER_UNDER, BTTS
    opcao: str                 # 1, X, 2, OVER, UNDER, YES, NO
    probabilidade: float
    confianca: str             # HIGH, MEDIUM, LOW
    justificativa: str
    resultado_verificador: Optional[str] = None


def buscar_jogos_permitidos() -> List[Dict]:
    """Busca jogos das competições permitidas nos próximos 7 dias"""

    hoje = datetime.now()
    date_from = hoje.strftime("%Y-%m-%d")
    date_to = (hoje + timedelta(days=7)).strftime("%Y-%m-%d")

    url = f"{API_BASE}/matches/"
    params = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "status": "SCHEDULED",
    }

    print(f"📅 Buscando jogos de {date_from} até {date_to} (status=SCHEDULED)...")

    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=30)
    except requests.exceptions.RequestException as e:
        print(f"❌ Erro de conexão ao buscar jogos: {e}")
        return []

    if response.status_code != 200:
        print(f"❌ Erro ao buscar jogos: HTTP {response.status_code} - {response.text[:200]}")
        return []

    dados = response.json()
    todos_matches = dados.get("matches", [])
    print(f"🔎 API retornou {len(todos_matches)} jogo(s) no período.")

    # Filtrar por competições permitidas
    jogos_permitidos = []
    competicoes_rejeitadas = set()
    for match in todos_matches:
        competicao = match.get("competition", {}).get("name", "")
        if competicao in COMPETICOES_PERMITIDAS:
            jogos_permitidos.append(match)
        else:
            competicoes_rejeitadas.add(competicao)

    if competicoes_rejeitadas:
        print(f"⚠️  Competições ignoradas (não estão na lista permitida): {sorted(competicoes_rejeitadas)}")

    print(f"✅ {len(jogos_permitidos)} jogo(s) encontrado(s) nas competições permitidas.")
    return jogos_permitidos


def buscar_historico_time(team_id: int, limit: int = 10) -> List[Dict]:
    """Busca histórico de um time"""
    
    url = f"{API_BASE}/teams/{team_id}/matches"
    params = {"limit": limit, "status": "FINISHED"}
    
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if response.status_code != 200:
            return []
        return response.json().get("matches", [])
    except Exception as e:
        print(f"⚠️  Erro ao buscar histórico: {e}")
        return []


def buscar_h2h(team_id1: int, team_id2: int, limit: int = 5) -> List[Dict]:
    """Busca confrontos diretos entre dois times"""
    
    url = f"{API_BASE}/matches/{team_id1}/head2head/{team_id2}"
    params = {"limit": limit}
    
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if response.status_code != 200:
            return []
        return response.json().get("matches", [])
    except Exception as e:
        return []


def calcular_estatisticas(historico: List[Dict], team_id: int, eh_em_casa: bool) -> EstatisticaTime:
    """Calcula estatísticas de um time baseado no histórico"""
    
    gols_marcados = []
    gols_sofridos = []
    
    for match in historico:
        home_id = match.get("homeTeam", {}).get("id")
        is_home = (home_id == team_id)
        
        if eh_em_casa and not is_home:
            continue
        if not eh_em_casa and is_home:
            continue
        
        score = match.get("score", {}).get("fullTime", {})
        home_goals = score.get("home", 0)
        away_goals = score.get("away", 0)
        
        if is_home:
            gols_marcados.append(home_goals)
            gols_sofridos.append(away_goals)
        else:
            gols_marcados.append(away_goals)
            gols_sofridos.append(home_goals)
    
    media_marcados = sum(gols_marcados) / len(gols_marcados) if gols_marcados else 1.0
    media_sofridos = sum(gols_sofridos) / len(gols_sofridos) if gols_sofridos else 1.0
    
    return EstatisticaTime(
        gols_marcados_media=media_marcados,
        gols_sofridos_media=media_sofridos,
        escanteios_media=5.5,  # Placeholder
        cartoes_media=2.0,      # Placeholder
        jogos=len(gols_marcados)
    )


def calcular_tendencia_forma(historico: List[Dict], team_id: int) -> str:
    """Compara forma dos últimos 3 vs últimos 5 jogos para detectar time em alta/baixa"""

    def aproveitamento(matches: List[Dict]) -> float:
        pts = 0
        total = len(matches) * 3
        for m in matches:
            home_id = m.get("homeTeam", {}).get("id")
            h = m.get("score", {}).get("fullTime", {}).get("home", 0) or 0
            a = m.get("score", {}).get("fullTime", {}).get("away", 0) or 0
            if home_id == team_id:
                if h > a: pts += 3
                elif h == a: pts += 1
            else:
                if a > h: pts += 3
                elif a == h: pts += 1
        return pts / total if total else 0.5

    if len(historico) < 3:
        return "indefinida"

    forma_3 = aproveitamento(historico[:3])
    forma_5 = aproveitamento(historico[:5]) if len(historico) >= 5 else forma_3
    diff = forma_3 - forma_5

    if diff > 0.15:
        return "em alta"
    elif diff < -0.15:
        return "em baixa"
    return "estavel"


def aplicar_pesos_temporais(historico: List[Dict], team_id: int) -> float:
    """Calcula score de forma recente com pesos decrescentes"""
    
    if not historico:
        return 0.5
    
    score = 0.0
    pesos = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]
    
    for idx, match in enumerate(historico[:10]):
        if idx >= len(pesos):
            break
        
        home_id = match.get("homeTeam", {}).get("id")
        home_score = match.get("score", {}).get("fullTime", {}).get("home", 0)
        away_score = match.get("score", {}).get("fullTime", {}).get("away", 0)
        
        if home_id == team_id:
            resultado = 1.0 if home_score > away_score else (0.5 if home_score == away_score else 0.0)
        else:
            resultado = 1.0 if away_score > home_score else (0.5 if away_score == home_score else 0.0)
        
        score += resultado * pesos[idx]
    
    return score / sum(pesos[:min(len(historico), 10)])


def calcular_h2h_factor(h2h: List[Dict], team_id: int) -> float:
    """Calcula fator baseado em H2H"""
    
    if not h2h:
        return 0.5
    
    vitorias = 0
    for match in h2h:
        home_id = match.get("homeTeam", {}).get("id")
        home_score = match.get("score", {}).get("fullTime", {}).get("home", 0)
        away_score = match.get("score", {}).get("fullTime", {}).get("away", 0)
        
        if home_id == team_id:
            if home_score > away_score:
                vitorias += 1
        else:
            if away_score > home_score:
                vitorias += 1
    
    return vitorias / len(h2h) if h2h else 0.5


def calcular_score_time(historico: List[Dict], h2h: List[Dict], team_id: int, eh_em_casa: bool) -> ScoreTempo:
    """Calcula score composto de um time"""
    
    forma = aplicar_pesos_temporais(historico, team_id)
    stats = calcular_estatisticas(historico, team_id, eh_em_casa)
    h2h_factor = calcular_h2h_factor(h2h, team_id)
    
    # Normalizar estatísticas
    ataque = min(stats.gols_marcados_media / 2.5, 1.0)  # 0-2.5 gols = 0-100%
    defesa = max(1.0 - (stats.gols_sofridos_media / 2.5), 0.0)
    fator_mando = 1.1 if eh_em_casa else 0.9
    
    # Scores ponderados
    score_total = (
        forma * 0.35 +
        ataque * 0.25 +
        defesa * 0.20 +
        (fator_mando / 1.0) * 0.10 +
        h2h_factor * 0.10
    )
    
    return ScoreTempo(
        forma_recente=forma,
        ataque=ataque,
        defesa=defesa,
        fator_mando=fator_mando,
        h2h_factor=h2h_factor,
        score_total=score_total
    )


def poisson_pmf(k: int, lambda_param: float) -> float:
    """Calcula probabilidade de Poisson para k gols com λ esperado"""
    if lambda_param < 0 or k < 0:
        return 0.0
    return (lambda_param ** k * e ** (-lambda_param)) / factorial(k)


def calcular_probabilidades_mercado(lambda_home: float, lambda_away: float, max_gols: int = 7) -> Dict[str, float]:
    """Gera probabilidades agregadas para mercados comuns via Poisson."""
    matriz = {}
    for h_gols in range(max_gols + 1):
        for a_gols in range(max_gols + 1):
            matriz[(h_gols, a_gols)] = poisson_pmf(h_gols, lambda_home) * poisson_pmf(a_gols, lambda_away)

    prob_casa = sum(p for (h, a), p in matriz.items() if h > a)
    prob_empate = sum(p for (h, a), p in matriz.items() if h == a)
    prob_visitante = sum(p for (h, a), p in matriz.items() if h < a)
    prob_over_25 = sum(p for (h, a), p in matriz.items() if (h + a) >= 3)
    prob_under_25 = 1.0 - prob_over_25
    prob_btts_yes = sum(p for (h, a), p in matriz.items() if h > 0 and a > 0)
    prob_btts_no = 1.0 - prob_btts_yes

    return {
        "casa": prob_casa,
        "empate": prob_empate,
        "visitante": prob_visitante,
        "over_25": prob_over_25,
        "under_25": prob_under_25,
        "btts_yes": prob_btts_yes,
        "btts_no": prob_btts_no,
    }


def prever_jogo(match: Dict) -> PredicaoJogo:
    """Prevê resultado de um jogo"""
    
    home_team = match.get("homeTeam", {})
    away_team = match.get("awayTeam", {})
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    
    # Buscar históricos
    hist_home = buscar_historico_time(home_id, limit=10)
    hist_away = buscar_historico_time(away_id, limit=10)
    h2h = buscar_h2h(home_id, away_id, limit=5)
    
    # Calcular scores
    score_home = calcular_score_time(hist_home, h2h, home_id, eh_em_casa=True)
    score_away = calcular_score_time(hist_away, h2h, away_id, eh_em_casa=False)
    
    # Gols esperados (λ)
    lambda_home = score_home.ataque * 1.8 + (1.0 - score_away.defesa) * 0.5
    lambda_away = score_away.ataque * 1.5 + (1.0 - score_home.defesa) * 0.5
    
    mercados = calcular_probabilidades_mercado(lambda_home, lambda_away)
    
    tendencia_casa = calcular_tendencia_forma(hist_home, home_id)
    tendencia_visitante = calcular_tendencia_forma(hist_away, away_id)
    
    score_real = match.get("score", {}).get("fullTime", {})
    placar_casa = score_real.get("home") if score_real else None
    placar_visitante = score_real.get("away") if score_real else None

    return PredicaoJogo(
        data_jogo=match.get("utcDate", ""),
        time_casa=home_team.get("shortName") or home_team.get("name", ""),
        time_visitante=away_team.get("shortName") or away_team.get("name", ""),
        status=match.get("status", "SCHEDULED"),
        placar_casa=placar_casa,
        placar_visitante=placar_visitante,
        prob_casa=mercados["casa"],
        prob_empate=mercados["empate"],
        prob_visitante=mercados["visitante"],
        gols_esperados_casa=lambda_home,
        gols_esperados_visitante=lambda_away,
        score_casa=score_home,
        score_visitante=score_away,
        competicao=match.get("competition", {}).get("name", "Desconhecido"),
        historico_casa=hist_home,
        historico_visitante=hist_away,
        tendencia_casa=tendencia_casa,
        tendencia_visitante=tendencia_visitante,
    )


def gerar_palpites(predicao: PredicaoJogo) -> List[BetSuggestion]:
    """Gera sugestões de aposta baseado na previsão"""
    
    palpites = []
    mercados = calcular_probabilidades_mercado(
        predicao.gols_esperados_casa,
        predicao.gols_esperados_visitante,
    )
    
    # Palpite: Vencedor
    probs = [
        (predicao.prob_casa, "1"),
        (predicao.prob_empate, "X"),
        (predicao.prob_visitante, "2"),
    ]
    prob_max, opcao = max(probs, key=lambda x: x[0])

    if prob_max > 0.55:
        confianca = "HIGH"
    elif prob_max > 0.45:
        confianca = "MEDIUM"
    else:
        confianca = "LOW"

    # Justificativa cruzada: ataque do favorito vs defesa do adversário
    if opcao == "1":
        ataque_fav = predicao.score_casa.ataque * 2.5
        defesa_adv = (1.0 - predicao.score_visitante.defesa) * 2.5
        nome_fav = predicao.time_casa
    elif opcao == "2":
        ataque_fav = predicao.score_visitante.ataque * 2.5
        defesa_adv = (1.0 - predicao.score_casa.defesa) * 2.5
        nome_fav = predicao.time_visitante
    else:
        ataque_fav = defesa_adv = None
        nome_fav = "Empate"

    if ataque_fav is not None:
        just_winner = (
            f"{nome_fav}: ataque ≈{ataque_fav:.1f} gols/jogo vs defesa adversária ≈{defesa_adv:.1f} sofridos/jogo. "
            f"Prob vitória: {prob_max*100:.1f}%"
        )
    else:
        just_winner = f"Jogo equilibrado. Prob empate: {prob_max*100:.1f}%"

    palpites.append(BetSuggestion(
        tipo="WINNER",
        opcao=opcao,
        probabilidade=prob_max,
        confianca=confianca,
        justificativa=just_winner,
    ))

    # Palpite: Over/Under 2.5
    prob_over = mercados["over_25"]
    prob_under = mercados["under_25"]

    bet_type = "OVER" if prob_over > prob_under else "UNDER"
    prob = max(prob_over, prob_under)
    total_esperado = predicao.gols_esperados_casa + predicao.gols_esperados_visitante

    if prob > 0.60:
        confianca = "HIGH"
    elif prob > 0.50:
        confianca = "MEDIUM"
    else:
        confianca = "LOW"

    palpites.append(BetSuggestion(
        tipo="OVER_UNDER",
        opcao=bet_type,
        probabilidade=prob,
        confianca=confianca,
        justificativa=(
            f"Gols esperados no jogo: ≈{total_esperado:.1f}. "
            f"{'UNDER' if bet_type == 'UNDER' else 'OVER'} 2.5: {prob*100:.1f}% de probabilidade"
        ),
    ))

    # Palpite: BTTS (ambos marcam)
    btts_yes = mercados["btts_yes"]
    btts_no = mercados["btts_no"]
    btts_opcao = "YES" if btts_yes >= btts_no else "NO"
    btts_prob = max(btts_yes, btts_no)

    if btts_prob > 0.60:
        confianca = "HIGH"
    elif btts_prob > 0.50:
        confianca = "MEDIUM"
    else:
        confianca = "LOW"

    xg_casa = predicao.gols_esperados_casa
    xg_fora = predicao.gols_esperados_visitante
    palpites.append(BetSuggestion(
        tipo="BTTS",
        opcao=btts_opcao,
        probabilidade=btts_prob,
        confianca=confianca,
        justificativa=(
            f"xG: {xg_casa:.1f} (casa) x {xg_fora:.1f} (fora). "
            f"Ambas marcam - {'Sim' if btts_opcao == 'YES' else 'Nao'}: {btts_prob*100:.1f}%"
        ),
    ))

    # Palpite: Empate vantajoso — defesas sólidas e prob > 30%
    defesa_casa = predicao.score_casa.defesa
    defesa_fora = predicao.score_visitante.defesa
    if predicao.prob_empate > 0.30 and defesa_casa > 0.50 and defesa_fora > 0.50:
        confianca_emp = "MEDIUM" if predicao.prob_empate > 0.35 else "LOW"
        palpites.append(BetSuggestion(
            tipo="EMPATE",
            opcao="X",
            probabilidade=predicao.prob_empate,
            confianca=confianca_emp,
            justificativa=(
                f"Ambas defesas solidas ({defesa_casa*100:.0f}% / {defesa_fora*100:.0f}% de aproveitamento defensivo). "
                f"Empate com {predicao.prob_empate*100:.1f}% de probabilidade"
            ),
        ))
    if predicao.status == "FINISHED" and predicao.placar_casa is not None and predicao.placar_visitante is not None:
        home_g = predicao.placar_casa
        away_g = predicao.placar_visitante
        for p in palpites:
            if p.tipo == "WINNER":
                if home_g > away_g and p.opcao == "1": p.resultado_verificador = "ACERTO"
                elif home_g == away_g and p.opcao == "X": p.resultado_verificador = "ACERTO"
                elif home_g < away_g and p.opcao == "2": p.resultado_verificador = "ACERTO"
                else: p.resultado_verificador = "ERRO"
            elif p.tipo == "OVER_UNDER":
                total = home_g + away_g
                if total > 2.5 and p.opcao == "OVER": p.resultado_verificador = "ACERTO"
                elif total < 2.5 and p.opcao == "UNDER": p.resultado_verificador = "ACERTO"
                else: p.resultado_verificador = "ERRO"
            elif p.tipo == "BTTS":
                if home_g > 0 and away_g > 0 and p.opcao == "YES": p.resultado_verificador = "ACERTO"
                elif (home_g == 0 or away_g == 0) and p.opcao == "NO": p.resultado_verificador = "ACERTO"
                else: p.resultado_verificador = "ERRO"
            elif p.tipo == "EMPATE":
                if home_g == away_g and p.opcao == "X": p.resultado_verificador = "ACERTO"
                else: p.resultado_verificador = "ERRO"

    return palpites


def _barra_percentual(valor: float, largura: int = 18) -> str:
    preenchido = int(max(0.0, min(1.0, valor)) * largura)
    return "#" * preenchido + "-" * (largura - preenchido)


def _texto_risco(prob: float) -> str:
    if prob >= 0.60:
        return "forte"
    if prob >= 0.45:
        return "moderado"
    return "alto"


def _resultado_rotulo(resultado: str) -> str:
    if resultado == "V":
        return "Vitoria"
    if resultado == "D":
        return "Derrota"
    if resultado == "E":
        return "Empate"
    return "Indefinido"


def _normalizar_historico_para_front(historico: List[Dict], team_name: str, limite: int = 5) -> List[Dict]:
    historico_saida = []
    for match in historico[:limite]:
        home = match.get("homeTeam", {}).get("shortName") or match.get("homeTeam", {}).get("name", "")
        away = match.get("awayTeam", {}).get("shortName") or match.get("awayTeam", {}).get("name", "")
        placar = match.get("score", {}).get("fullTime", {})
        gols_home = placar.get("home")
        gols_away = placar.get("away")
        data_utc = match.get("utcDate", "")

        try:
            data_fmt = datetime.fromisoformat(data_utc.replace("Z", "+00:00")).strftime("%d/%m %H:%M")
        except ValueError:
            data_fmt = data_utc

        resultado = "?"
        if gols_home is not None and gols_away is not None:
            if home == team_name:
                if gols_home > gols_away:
                    resultado = "V"
                elif gols_home < gols_away:
                    resultado = "D"
                else:
                    resultado = "E"
            else:
                if gols_away > gols_home:
                    resultado = "V"
                elif gols_away < gols_home:
                    resultado = "D"
                else:
                    resultado = "E"

        historico_saida.append(
            {
                "data": data_fmt,
                "mandante": home,
                "visitante": away,
                "placar": f"{gols_home} x {gols_away}" if gols_home is not None and gols_away is not None else "-",
                "resultado": resultado,
                "resultado_label": _resultado_rotulo(resultado),
            }
        )

    return historico_saida


def exportar_predicoes_front(predicoes: List[PredicaoJogo], caminho_saida: str = "predictions.json") -> None:
    dados = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_jogos": len(predicoes),
        "jogos": [],
    }

    for pred in predicoes:
        mercados = calcular_probabilidades_mercado(pred.gols_esperados_casa, pred.gols_esperados_visitante)
        ranking = [
            {"nome": pred.time_casa, "prob": pred.prob_casa},
            {"nome": "Empate", "prob": pred.prob_empate},
            {"nome": pred.time_visitante, "prob": pred.prob_visitante},
        ]
        ranking.sort(key=lambda item: item["prob"], reverse=True)
        favorito = ranking[0]
        diferenca = max(0.0, ranking[0]["prob"] - ranking[1]["prob"])

        total_gols = pred.gols_esperados_casa + pred.gols_esperados_visitante
        if mercados["under_25"] >= 0.58:
            cenario_gols = f"Jogo fechado esperado (xG total ≈{total_gols:.1f}). Under 2.5 com {mercados['under_25']*100:.0f}%."
        elif mercados["over_25"] >= 0.55:
            cenario_gols = f"Jogo mais aberto (xG total ≈{total_gols:.1f}). Over 2.5 com {mercados['over_25']*100:.0f}%."
        else:
            cenario_gols = f"Mercado de gols equilibrado (xG total ≈{total_gols:.1f})."

        tendencia_partes = []
        if pred.tendencia_casa not in ("estavel", "indefinida"):
            tendencia_partes.append(f"{pred.time_casa} {pred.tendencia_casa}")
        if pred.tendencia_visitante not in ("estavel", "indefinida"):
            tendencia_partes.append(f"{pred.time_visitante} {pred.tendencia_visitante}")
        tendencia_txt = (" | Forma recente: " + ", ".join(tendencia_partes) + ".") if tendencia_partes else ""

        confianca_fav = _texto_risco(favorito["prob"])
        leitura = (
            f"{favorito['nome']} favorito ({favorito['prob']*100:.0f}%, risco {confianca_fav}). "
            f"{cenario_gols}"
            f"{tendencia_txt}"
        )

        palpites = [asdict(item) for item in gerar_palpites(pred)]
        dados["jogos"].append(
            {
                "competicao": pred.competicao,
                "data": pred.data_jogo,
                "status": pred.status,
                "placar_atual": {
                    "casa": pred.placar_casa,
                    "visitante": pred.placar_visitante
                },
                "times": {
                    "casa": pred.time_casa,
                    "visitante": pred.time_visitante,
                },
                "probabilidades": {
                    "casa": pred.prob_casa,
                    "empate": pred.prob_empate,
                    "visitante": pred.prob_visitante,
                },
                "favorito": {
                    "nome": favorito["nome"],
                    "prob": favorito["prob"],
                    "vantagem": diferenca,
                },
                "gols_esperados": {
                    "casa": pred.gols_esperados_casa,
                    "visitante": pred.gols_esperados_visitante,
                    "total": pred.gols_esperados_casa + pred.gols_esperados_visitante,
                },
                "mercados": {
                    "under_25": mercados["under_25"],
                    "over_25": mercados["over_25"],
                    "btts_yes": mercados["btts_yes"],
                    "btts_no": mercados["btts_no"],
                },
                "scores": {
                    "casa": asdict(pred.score_casa),
                    "visitante": asdict(pred.score_visitante),
                },
                "leitura_rapida": leitura,
                "tendencia": {
                    "casa": pred.tendencia_casa,
                    "visitante": pred.tendencia_visitante,
                },
                "historico": {
                    "casa": _normalizar_historico_para_front(pred.historico_casa, pred.time_casa),
                    "visitante": _normalizar_historico_para_front(pred.historico_visitante, pred.time_visitante),
                },
                "palpites": palpites,
            }
        )

    with open(caminho_saida, "w", encoding="utf-8") as file_handle:
        json.dump(dados, file_handle, ensure_ascii=False, indent=2)


def exibir_predicoes(predicoes: List[PredicaoJogo]) -> None:
    """Exibe todas as previsões e palpites"""
    
    print("\n" + "=" * 100)
    print("  🎯  ANÁLISE E PALPITES")
    print("=" * 100 + "\n")
    
    for pred in predicoes:
        mercados = calcular_probabilidades_mercado(
            pred.gols_esperados_casa,
            pred.gols_esperados_visitante,
        )

        ranking = [
            (pred.time_casa, pred.prob_casa),
            ("Empate", pred.prob_empate),
            (pred.time_visitante, pred.prob_visitante),
        ]
        ranking.sort(key=lambda item: item[1], reverse=True)
        favorito, prob_favorito = ranking[0]
        segunda_forca, prob_segunda = ranking[1]
        diferenca = max(0.0, prob_favorito - prob_segunda)

        print(f"🏟️  {pred.time_casa} vs {pred.time_visitante}")
        print(f"  ├─ Mercado 1X2: Casa {pred.prob_casa*100:>5.1f}% | X {pred.prob_empate*100:>5.1f}% | Fora {pred.prob_visitante*100:>5.1f}%")
        print(f"  ├─ Ranking de chance:")
        print(f"  │    1) {ranking[0][0]:<18} {ranking[0][1]*100:>5.1f}% [{_barra_percentual(ranking[0][1])}]")
        print(f"  │    2) {ranking[1][0]:<18} {ranking[1][1]*100:>5.1f}% [{_barra_percentual(ranking[1][1])}]")
        print(f"  │    3) {ranking[2][0]:<18} {ranking[2][1]*100:>5.1f}% [{_barra_percentual(ranking[2][1])}]")
        print(f"  ├─ Favorito: {favorito} ({prob_favorito*100:.1f}%) | vantagem: {diferenca*100:.1f} p.p. sobre {segunda_forca}")
        print(f"  ├─ Gols esperados (xG simplificado): {pred.gols_esperados_casa:.2f} x {pred.gols_esperados_visitante:.2f} | total {pred.gols_esperados_casa + pred.gols_esperados_visitante:.2f}")
        print(f"  ├─ Mercado de gols: Under 2.5 {mercados['under_25']*100:.1f}% | Over 2.5 {mercados['over_25']*100:.1f}%")
        print(f"  ├─ Ambos marcam (BTTS): SIM {mercados['btts_yes']*100:.1f}% | NÃO {mercados['btts_no']*100:.1f}%")
        print(f"  ├─ Score {pred.time_casa}: {pred.score_casa.score_total:.2f} (Forma: {pred.score_casa.forma_recente:.2f}, Ataque: {pred.score_casa.ataque:.2f}, Defesa: {pred.score_casa.defesa:.2f})")
        print(f"  ├─ Score {pred.time_visitante}: {pred.score_visitante.score_total:.2f} (Forma: {pred.score_visitante.forma_recente:.2f}, Ataque: {pred.score_visitante.ataque:.2f}, Defesa: {pred.score_visitante.defesa:.2f})")
        print("  └─ Cartões e escanteios: ainda não modelados por falta de dados confiáveis neste endpoint.")

        leitura = (
            f"     Leitura rápida: {favorito} e favorito com risco {_texto_risco(prob_favorito)}. "
            f"Cenário de gols tende a {'UNDER' if mercados['under_25'] >= mercados['over_25'] else 'OVER'} 2.5."
        )
        print(f"\n{leitura}")
        
        palpites = gerar_palpites(pred)
        print(f"\n  💡 Palpites:")
        for p in palpites:
            icon_conf = "🟢" if p.confianca == "HIGH" else "🟡" if p.confianca == "MEDIUM" else "🔴"
            print(f"     {icon_conf} [{p.tipo}] {p.opcao}: {p.probabilidade*100:.1f}% ({p.confianca}) - {p.justificativa}")
        
        print("\n" + "-" * 100 + "\n")


def main():
    """Fluxo principal"""
    
    print("🌐 Buscando jogos das competições permitidas...")
    jogos = buscar_jogos_permitidos()
    
    if not jogos:
        print("❌ Nenhum jogo encontrado.")
        return
    
    print(f"📊 Encontrados {len(jogos)} jogo(s). Analisando...\n")
    
    predicoes = []
    for match in jogos[:5]:  # Limitar a 5 para não sobrecarregar
        try:
            pred = prever_jogo(match)
            predicoes.append(pred)
        except Exception as e:
            print(f"⚠️  Erro ao processar jogo: {e}")
    
    exibir_predicoes(predicoes)
    exportar_predicoes_front(predicoes, "predictions.json")
    print("💾 Arquivo para front gerado em: predictions.json")


if __name__ == "__main__":
    main()
