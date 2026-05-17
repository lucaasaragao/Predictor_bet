"""
Sistema de Previsões e Palpites para Futebol
=============================================
Combina histórico, H2H, forma recente e modelo Poisson para gerar palpites.
"""

import json
import os
import time
import unicodedata

import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional, List, Dict, Tuple
from math import factorial, e, log
from dataclasses import dataclass, asdict, field

TOKEN_ENV_VAR = "FOOTBALL_DATA_TOKEN"
TOKEN = os.getenv(TOKEN_ENV_VAR, "").strip()
if not TOKEN:
    raise SystemExit(
        "Defina a variavel de ambiente FOOTBALL_DATA_TOKEN antes de executar. "
        "Exemplo PowerShell: $env:FOOTBALL_DATA_TOKEN='seu_token'"
    )
HEADERS = {"X-Auth-Token": TOKEN}
API_BASE = "https://api.football-data.org/v4"

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_ENABLED = bool(ODDS_API_KEY)
ODDS_REGIONS = os.getenv("ODDS_REGIONS", "eu")
ODDS_BOOKMAKERS = os.getenv("ODDS_BOOKMAKERS", "").strip()
ODDS_MARKETS = "h2h"
ODDS_FORMAT = "decimal"
ODDS_MIN_EV = float(os.getenv("ODDS_MIN_EV", "0.03"))
ODDS_MIN_EDGE_GATE = float(os.getenv("ODDS_MIN_EDGE_GATE", "0.10"))
ODDS_ONLY_VALUE_GAMES = os.getenv("ODDS_ONLY_VALUE_GAMES", "true").lower() == "true"
ODDS_MAX_SPORT_CALLS = int(os.getenv("ODDS_MAX_SPORT_CALLS", "3"))
ODDS_USE_UPCOMING = os.getenv("ODDS_USE_UPCOMING", "true").lower() == "true"
ODDS_DEBUG_VISUAL = os.getenv("ODDS_DEBUG_VISUAL", "false").lower() == "true"
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL    = "gemini-flash-latest"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
SHRINKAGE_K_JOGOS = float(os.getenv("SHRINKAGE_K_JOGOS", "6"))
SHRINKAGE_PESO_MIN = float(os.getenv("SHRINKAGE_PESO_MIN", "0.20"))
EVAL_EPSILON = 1e-6

COMPETICAO_PARA_ODDS_SPORT = {
    "Premier League": "soccer_epl",
    "Primera Division": "soccer_spain_la_liga",
    "Serie A": "soccer_italy_serie_a",
    "Bundesliga": "soccer_germany_bundesliga",
    "Ligue 1": "soccer_france_ligue_one",
    "Championship": "soccer_efl_champ",
    "Primeira Liga": "soccer_portugal_primeira_liga",
    "Eredivisie": "soccer_netherlands_eredivisie",
    "Campeonato Brasileiro Série A": "soccer_brazil_campeonato",
    "Campeonato Brasileiro Série B": "soccer_brazil_serie_b",
    "UEFA Champions League": "soccer_uefa_champs_league",
    "Copa Libertadores": "soccer_conmebol_libertadores",
}

# Vantagem de mando de campo (multiplicador sobre λ)
HOME_ADVANTAGE = 1.10

# Pesos do score composto de time (soma = 1.0)
PESO_FORMA_RECENTE   = 0.35
PESO_ATAQUE          = 0.25
PESO_DEFESA          = 0.20
PESO_MANDO_CAMPO     = 0.10
PESO_H2H             = 0.10

# Fator de mando de campo no score (diferente do HOME_ADVANTAGE do modelo Poisson)
FATOR_MANDO_CASA = 1.1
FATOR_MANDO_FORA = 0.9

# Fadiga por jogos consecutivos
FADIGA_BACK_TO_BACK    = 0.86   # jogou há ≤2 dias
FADIGA_SEQUENCIA_CURTA = 0.93   # jogou há ≤4 dias
DIAS_BACK_TO_BACK      = 2
DIAS_SEQUENCIA_CURTA   = 4

# Limites de clamp para força de ataque/defesa (modelo Dixon-Coles)
CLAMP_FORCA_MIN = 0.3
CLAMP_FORCA_MAX = 3.0

# Limites de clamp para λ final (gols esperados)
CLAMP_LAMBDA_MIN = 0.3
CLAMP_LAMBDA_MAX = 5.0

# Fator de forma recente aplicado sobre λ: 0.85 + forma_recente * 0.30
FATOR_FORMA_BASE   = 0.85
FATOR_FORMA_ESCALA = 0.30

# Média histórica de gols por jogo por liga (fonte: dados públicos últimas 3 temporadas)
# Usada para normalizar força de ataque/defesa relativa à liga (modelo Dixon-Coles)
MEDIA_GOLS_LIGA: dict[str, float] = {
    "Premier League": 2.72,
    "Primera Division": 2.58,
    "Serie A": 2.50,
    "Bundesliga": 3.05,
    "Ligue 1": 2.52,
    "Campeonato Brasileiro Série A": 2.28,
    "Campeonato Brasileiro Série B": 2.18,
    "UEFA Champions League": 2.75,
    "Copa Libertadores": 2.45,
    "Primeira Liga": 2.42,
    "Championship": 2.55,
    "Eredivisie": 3.12,
}
MEDIA_GOLS_DEFAULT = 2.55  # fallback para ligas sem mapeamento

# Thresholds de confiança separados para OVER/UNDER e BTTS
# (mais altos que WINNER porque Poisson puro superestima esses mercados)
OU_BTTS_HIGH_THRESHOLD   = 0.20
OU_BTTS_MEDIUM_THRESHOLD = 0.12


def carregar_timezone_app() -> timezone:
    """Carrega o fuso da aplicação com fallback quando tzdata não está disponível."""
    timezone_key = os.getenv("APP_TIMEZONE", "America/Sao_Paulo")
    try:
        return ZoneInfo(timezone_key)
    except ZoneInfoNotFoundError:
        print(
            f"WARNING: timezone '{timezone_key}' indisponivel no ambiente. "
            "Usando fallback UTC-03:00."
        )
        return timezone(timedelta(hours=-3))


# Timezone oficial da aplicação para definir "jogos de hoje" no Brasil.
APP_TIMEZONE = carregar_timezone_app()

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
    "Bundesliga",
    "Eredivisie",
    "Ligue 1",
}

PRE_MATCH_STATUSES = {"SCHEDULED", "TIMED"}
SNAPSHOT_BASELINE_SOURCE_STATUSES = PRE_MATCH_STATUSES | {"IN_PLAY", "PAUSED"}
COMPETICOES_EXCLUIDAS_DICAS = {
    "Campeonato Brasileiro Série A",
    "Campeonato Brasileiro Série B",
}
SCORE_CONFIANCA = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


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
class TendenciaGols:
    """Tendência de gols de um time baseada nos últimos N jogos (sinal binário)."""
    prob_marca: float       # fração de jogos em que o time marcou ≥ 1 gol
    prob_sofre: float       # fração de jogos em que o time sofreu ≥ 1 gol
    sequencia_marca: int    # jogos consecutivos recentes com gol marcado
    sequencia_sofre: int    # jogos consecutivos recentes com gol sofrido
    jogos: int              # total de jogos analisados


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
    odds_h2h: Optional[Dict[str, float]] = None
    odds_match_id: Optional[str] = None
    odds_debug: Dict[str, str] = field(default_factory=dict)
    escudo_casa: Optional[str] = None
    escudo_visitante: Optional[str] = None
    tendencia_gols_casa: Optional[TendenciaGols] = None
    tendencia_gols_visitante: Optional[TendenciaGols] = None


@dataclass
class BetSuggestion:
    """Sugestão de aposta"""
    tipo: str                  # WINNER, OVER_UNDER, BTTS
    opcao: str                 # 1, X, 2, OVER, UNDER, YES, NO
    probabilidade: float
    confianca: str             # HIGH, MEDIUM, LOW
    justificativa: str
    edge: float = 0.0          # margem de vantagem sobre a segunda melhor opção
    odd_decimal: Optional[float] = None
    ev: Optional[float] = None
    ev_bruto: Optional[float] = None
    prob_mercado_justa: Optional[float] = None
    valor_esperado_positivo: bool = False
    resultado_verificador: Optional[str] = None


def buscar_jogos_permitidos() -> List[Dict]:
    """Busca jogos das competições permitidas do dia atual"""

    url = f"{API_BASE}/matches/"
    agora_local = datetime.now(APP_TIMEZONE)
    hoje_local = agora_local.date()
    inicio_local = datetime.combine(hoje_local, datetime.min.time(), tzinfo=APP_TIMEZONE)
    fim_local = inicio_local + timedelta(days=1)
    inicio_utc = inicio_local.astimezone(timezone.utc)
    fim_utc = fim_local.astimezone(timezone.utc)
    params = {
        "dateFrom": inicio_utc.date().isoformat(),
        "dateTo": fim_utc.date().isoformat(),
    }

    print(
        f"📅 Buscando jogos do dia local {hoje_local} "
        f"(janela UTC {params['dateFrom']} até {params['dateTo']})..."
    )

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

    def data_local_jogo(match: Dict) -> Optional[datetime.date]:
        data_utc = str(match.get("utcDate", "") or "")
        if not data_utc:
            return None
        try:
            dt = datetime.fromisoformat(data_utc.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(APP_TIMEZONE).date()

    # Filtrar por competições permitidas
    jogos_permitidos = []
    competicoes_rejeitadas = set()
    jogos_fora_do_dia_local = 0
    for match in todos_matches:
        competicao = match.get("competition", {}).get("name", "")
        if competicao not in COMPETICOES_PERMITIDAS:
            competicoes_rejeitadas.add(competicao)
            continue

        if data_local_jogo(match) != hoje_local:
            jogos_fora_do_dia_local += 1
            continue

        jogos_permitidos.append(match)

    if competicoes_rejeitadas:
        print(f"⚠️  Competições ignoradas (não estão na lista permitida): {sorted(competicoes_rejeitadas)}")
    if jogos_fora_do_dia_local:
        print(f"🗓️  {jogos_fora_do_dia_local} jogo(s) ignorado(s) por não serem do dia local ({hoje_local}).")

    print(f"✅ {len(jogos_permitidos)} jogo(s) encontrado(s) nas competições permitidas.")
    return jogos_permitidos


def buscar_historico_time(team_id: int, limit: int = 10) -> List[Dict]:
    """Busca histórico de um time, retornando do mais recente para o mais antigo."""
    url = f"{API_BASE}/teams/{team_id}/matches"
    params = {"limit": limit, "status": "FINISHED"}

    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if response.status_code != 200:
            return []
        matches = response.json().get("matches", [])
        matches.sort(key=lambda m: m.get("utcDate", ""), reverse=True)
        return matches
    except Exception as e:
        print(f"⚠️  Erro ao buscar histórico: {e}")
        return []


def buscar_h2h(team_id1: int, team_id2: int, limit: int = 5) -> List[Dict]:
    """Busca confrontos diretos entre dois times, do mais recente para o mais antigo."""
    url = f"{API_BASE}/matches/{team_id1}/head2head/{team_id2}"
    params = {"limit": limit}

    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if response.status_code != 200:
            return []
        matches = response.json().get("matches", [])
        matches.sort(key=lambda m: m.get("utcDate", ""), reverse=True)
        return matches
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


def _media_com_shrinkage(media_time: float, media_liga: float, jogos: int) -> float:
    """Combina média do time com média da liga para reduzir ruido em amostra curta."""
    if jogos <= 0:
        return media_liga

    if SHRINKAGE_K_JOGOS <= 0:
        peso_time = 1.0
    else:
        peso_time = jogos / (jogos + SHRINKAGE_K_JOGOS)

    peso_time = max(SHRINKAGE_PESO_MIN, min(1.0, peso_time))
    return (peso_time * media_time) + ((1.0 - peso_time) * media_liga)


def _clip_probabilidade(prob: float, epsilon: float = EVAL_EPSILON) -> float:
    return max(epsilon, min(1.0 - epsilon, prob))


def detectar_fadiga(historico: List[Dict], data_jogo_utc: str) -> float:
    """Retorna fator de fadiga (0.85–1.0) se o time jogou recentemente.

    Um time que jogou há 2 dias ou menos tem desempenho ofensivo reduzido
    em média ~10-15% segundo análises de back-to-back em grandes ligas.
    """
    if not historico:
        return 1.0
    try:
        ultimo_jogo_utc = historico[0].get("utcDate", "")
        ultimo_dt = datetime.fromisoformat(ultimo_jogo_utc.replace("Z", "+00:00"))
        jogo_dt = datetime.fromisoformat(data_jogo_utc.replace("Z", "+00:00"))
        dias = (jogo_dt - ultimo_dt).days
        if dias <= 2:
            return 0.86  # back-to-back severo
        if dias <= 4:
            return 0.93  # sequência apertada
    except (ValueError, TypeError, AttributeError):
        pass
    return 1.0


def calcular_tendencia_forma(historico: List[Dict], team_id: int) -> str:
    """Compara forma dos últimos 3 vs últimos 5 jogos para detectar time em alta/baixa"""

    def aproveitamento(matches: List[Dict]) -> float:
        pontos = 0
        total_pontos_disputa = len(matches) * 3
        for m in matches:
            home_id = m.get("homeTeam", {}).get("id")
            gols_casa = m.get("score", {}).get("fullTime", {}).get("home", 0) or 0
            gols_fora = m.get("score", {}).get("fullTime", {}).get("away", 0) or 0
            if home_id == team_id:
                if gols_casa > gols_fora: pontos += 3
                elif gols_casa == gols_fora: pontos += 1
            else:
                if gols_fora > gols_casa: pontos += 3
                elif gols_fora == gols_casa: pontos += 1
        return pontos / total_pontos_disputa if total_pontos_disputa else 0.5

    if len(historico) < 3:
        return "indefinida"

    forma_3 = aproveitamento(historico[:3])
    forma_5 = aproveitamento(historico[:5]) if len(historico) >= 5 else forma_3
    diferenca_forma = forma_3 - forma_5

    if diferenca_forma > 0.15:
        return "em alta"
    elif diferenca_forma < -0.15:
        return "em baixa"
    return "estavel"


def calcular_tendencia_gols(historico: List[Dict], team_id: int, n: int = 10) -> TendenciaGols:
    """Sinal binário de gols dos últimos N jogos: marcou ≥1 / sofreu ≥1 por partida.

    Complementa o Poisson capturando consistência recente — um time que
    marcou em 9 dos últimos 10 jogos tem padrão diferente de outro com λ
    similar mas desempenho irregular.
    """
    marcou: List[bool] = []
    sofreu: List[bool] = []

    for match in historico[:n]:
        home_id = match.get("homeTeam", {}).get("id")
        ft = match.get("score", {}).get("fullTime", {})
        g_casa = ft.get("home") or 0
        g_fora = ft.get("away") or 0
        if home_id == team_id:
            marcou.append(g_casa >= 1)
            sofreu.append(g_fora >= 1)
        else:
            marcou.append(g_fora >= 1)
            sofreu.append(g_casa >= 1)

    total = len(marcou)
    if total == 0:
        return TendenciaGols(prob_marca=0.5, prob_sofre=0.5,
                             sequencia_marca=0, sequencia_sofre=0, jogos=0)

    # Streak: quantos jogos consecutivos mais recentes com gol marcado / sofrido
    seq_marca = 0
    for v in marcou:
        if v:
            seq_marca += 1
        else:
            break

    seq_sofre = 0
    for v in sofreu:
        if v:
            seq_sofre += 1
        else:
            break

    return TendenciaGols(
        prob_marca=round(sum(marcou) / total, 3),
        prob_sofre=round(sum(sofreu) / total, 3),
        sequencia_marca=seq_marca,
        sequencia_sofre=seq_sofre,
        jogos=total,
    )


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
    fator_mando = FATOR_MANDO_CASA if eh_em_casa else FATOR_MANDO_FORA
    
    # Scores ponderados
    score_total = (
        forma * PESO_FORMA_RECENTE +
        ataque * PESO_ATAQUE +
        defesa * PESO_DEFESA +
        (fator_mando / 1.0) * PESO_MANDO_CAMPO +
        h2h_factor * PESO_H2H
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


def dixon_coles_tau(h: int, a: int, lh: float, la: float, rho: float = -0.13) -> float:
    """Fator de correção Dixon-Coles para os 4 placares baixos.

    Corrige a superestimação de BTTS YES que ocorre quando gols são tratados
    como independentes (Poisson puro). rho negativo reduz P(ambos marcam).
    """
    if h == 0 and a == 0:
        return 1.0 - lh * la * rho
    if h == 1 and a == 0:
        return 1.0 + la * rho
    if h == 0 and a == 1:
        return 1.0 + lh * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def calcular_probabilidades_mercado(lambda_home: float, lambda_away: float, max_gols: int = 7) -> Dict[str, float]:
    """Gera probabilidades agregadas para mercados comuns via Poisson."""
    matriz = {}
    for h_gols in range(max_gols + 1):
        for a_gols in range(max_gols + 1):
            tau = dixon_coles_tau(h_gols, a_gols, lambda_home, lambda_away)
            matriz[(h_gols, a_gols)] = poisson_pmf(h_gols, lambda_home) * poisson_pmf(a_gols, lambda_away) * tau

    # Renormalizar após aplicar τ (os 4 placares baixos foram perturbados)
    total = sum(matriz.values())
    if total > 0:
        matriz = {k: v / total for k, v in matriz.items()}

    prob_casa = sum(p for (h, a), p in matriz.items() if h > a)
    prob_empate = sum(p for (h, a), p in matriz.items() if h == a)
    prob_visitante = sum(p for (h, a), p in matriz.items() if h < a)
    prob_over_15 = sum(p for (h, a), p in matriz.items() if (h + a) >= 2)
    prob_over_25 = sum(p for (h, a), p in matriz.items() if (h + a) >= 3)
    prob_over_35 = sum(p for (h, a), p in matriz.items() if (h + a) >= 4)
    prob_btts_yes = sum(p for (h, a), p in matriz.items() if h > 0 and a > 0)
    prob_btts_no = 1.0 - prob_btts_yes

    return {
        "casa": prob_casa,
        "empate": prob_empate,
        "visitante": prob_visitante,
        "over_15": prob_over_15,
        "under_15": 1.0 - prob_over_15,
        "over_25": prob_over_25,
        "under_25": 1.0 - prob_over_25,
        "over_35": prob_over_35,
        "under_35": 1.0 - prob_over_35,
        "btts_yes": prob_btts_yes,
        "btts_no": prob_btts_no,
    }


def _normalizar_nome_time(nome: str) -> str:
    base = unicodedata.normalize("NFKD", str(nome or ""))
    sem_acento = "".join(ch for ch in base if not unicodedata.combining(ch))
    limpo = sem_acento.lower().replace("fc", "").replace("cf", "")
    return " ".join(limpo.split())


# Mapeia nomes abreviados (shortName da football-data.org) para a forma canônica
# usada pelas odds APIs. Chave e valor são saídas de _normalizar_nome_time().
_ALIASES_TIME: Dict[str, str] = {
    # Premier League
    "man united": "manchester united",
    "man utd": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham hotspur",
    "wolves": "wolverhampton wanderers",
    "wolverhampton": "wolverhampton wanderers",
    "forest": "nottingham forest",
    "nott forest": "nottingham forest",
    "nottm forest": "nottingham forest",
    "newcastle": "newcastle united",
    "sheff utd": "sheffield united",
    "brighton": "brighton hove albion",
    "west brom": "west bromwich albion",
    # Bundesliga
    "bayern": "bayern munich",
    "dortmund": "borussia dortmund",
    "leverkusen": "bayer leverkusen",
    "gladbach": "borussia monchengladbach",
    "frankfurt": "eintracht frankfurt",
    "eintracht": "eintracht frankfurt",
    "leipzig": "rb leipzig",
    # La Liga
    "atletico": "atletico madrid",
    "atletico de madrid": "atletico madrid",
    "betis": "real betis",
    "celta": "celta vigo",
    "celta de vigo": "celta vigo",
    "alaves": "deportivo alaves",
    "athletic": "athletic bilbao",
    "rayo": "rayo vallecano",
    # Serie A
    "inter": "inter milan",
    "milan": "ac milan",
    "roma": "as roma",
    # Ligue 1
    "psg": "paris saint-germain",
    "paris sg": "paris saint-germain",
    "lyon": "olympique lyonnais",
    "marseille": "olympique de marseille",
    # Portugal
    "sporting": "sporting cp",
    "sporting lisbon": "sporting cp",
    # Países Baixos
    "psv": "psv eindhoven",
    "az": "az alkmaar",
    # Brasil
    "atletico-mg": "atletico mineiro",
    "atletico mg": "atletico mineiro",
    "vasco": "vasco da gama",
}


def _canonicalizar_nome_time(nome: str) -> str:
    """Normaliza + resolve alias de sigla/abreviação para comparação de odds."""
    norm = _normalizar_nome_time(nome)
    return _ALIASES_TIME.get(norm, norm)


def _nomes_equivalentes(a: str, b: str) -> bool:
    """True se dois nomes (raw ou normalizados) se referem ao mesmo time.

    Tentativas em ordem:
    1. Igualdade exata após normalização + alias.
    2. Um token de comprimento > 2 de A é prefixo de um token de B (ou vice-versa)
       e ambos compartilham ao menos um token de comprimento > 3 — cobre casos
       como "Man" / "Manchester" com "United" em comum.
    """
    nome_canonico_a, nome_canonico_b = _canonicalizar_nome_time(a), _canonicalizar_nome_time(b)
    if nome_canonico_a == nome_canonico_b:
        return True
    tokens_a = set(nome_canonico_a.split())
    tokens_b = set(nome_canonico_b.split())
    tokens_em_comum = {token for token in tokens_a & tokens_b if len(token) > 3}
    if not tokens_em_comum:
        return False
    for token_a in tokens_a:
        if len(token_a) < 3:
            continue
        for token_b in tokens_b:
            if token_b.startswith(token_a) or token_a.startswith(token_b):
                return True
    return False


def _escolher_melhor_odd_h2h(evento_odds: Dict) -> Dict[str, float]:
    melhores: Dict[str, float] = {}
    for book in evento_odds.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for out in market.get("outcomes", []):
                nome = out.get("name")
                odd = out.get("price")
                if not nome or odd is None:
                    continue
                try:
                    odd_decimal = float(odd)
                except (TypeError, ValueError):
                    continue
                if odd_decimal <= 1.0:
                    continue
                atual = melhores.get(nome)
                if atual is None or odd_decimal > atual:
                    melhores[nome] = odd_decimal
    return melhores


def _buscar_odds_h2h_por_sport(sport_key: str) -> Tuple[List[Dict], Dict[str, str]]:
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ODDS_REGIONS,
        "markets": ODDS_MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": "iso",
    }
    if ODDS_BOOKMAKERS:
        params["bookmakers"] = ODDS_BOOKMAKERS

    try:
        response = requests.get(url, params=params, timeout=30)
    except requests.exceptions.RequestException as exc:
        print(f"⚠️  Odds API indisponível para {sport_key}: {exc}")
        return [], {}

    headers_quota = {
        "x-requests-remaining": response.headers.get("x-requests-remaining", "?"),
        "x-requests-used": response.headers.get("x-requests-used", "?"),
        "x-requests-last": response.headers.get("x-requests-last", "?"),
    }

    if response.status_code == 429:
        print(f"⚠️  Odds API rate limit em {sport_key}.")
        return [], headers_quota

    if response.status_code != 200:
        print(f"⚠️  Odds API erro {response.status_code} em {sport_key}: {response.text[:140]}")
        return [], headers_quota

    data = response.json() or []
    return data, headers_quota


def _buscar_odds_h2h_upcoming() -> Tuple[List[Dict], Dict[str, str]]:
    """Busca odds H2H em uma unica chamada para todos os esportes/liga upcoming.

    Custo tipico desta chamada: 1 credito por regiao para 1 market (h2h).
    """
    url = f"{ODDS_API_BASE}/sports/upcoming/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ODDS_REGIONS,
        "markets": ODDS_MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": "iso",
    }
    if ODDS_BOOKMAKERS:
        params["bookmakers"] = ODDS_BOOKMAKERS

    try:
        response = requests.get(url, params=params, timeout=30)
    except requests.exceptions.RequestException as exc:
        print(f"⚠️  Odds API indisponível no endpoint upcoming: {exc}")
        return [], {}

    headers_quota = {
        "x-requests-remaining": response.headers.get("x-requests-remaining", "?"),
        "x-requests-used": response.headers.get("x-requests-used", "?"),
        "x-requests-last": response.headers.get("x-requests-last", "?"),
    }

    if response.status_code == 429:
        print("⚠️  Odds API rate limit no endpoint upcoming.")
        return [], headers_quota

    if response.status_code != 200:
        print(f"⚠️  Odds API erro {response.status_code} em upcoming: {response.text[:140]}")
        return [], headers_quota

    data = response.json() or []
    return data, headers_quota


def _aplicar_odds_por_sport(candidatos_por_sport: Dict[str, List[PredicaoJogo]]) -> None:
    """Fallback: consulta odds por liga apenas para os sport keys relevantes."""
    sports_ordenados = sorted(candidatos_por_sport.keys(), key=lambda s: len(candidatos_por_sport[s]), reverse=True)
    sports_consultar = sports_ordenados[:max(1, ODDS_MAX_SPORT_CALLS)]

    print(f"🎯 Odds fallback: consultando {len(sports_consultar)} liga(s) relevantes.")
    for sport_key in sports_consultar:
        eventos_odds, quota_headers = _buscar_odds_h2h_por_sport(sport_key)
        if quota_headers:
            print(
                f"   ↳ {sport_key}: custo {quota_headers.get('x-requests-last')} | "
                f"usado {quota_headers.get('x-requests-used')} | restante {quota_headers.get('x-requests-remaining')}"
            )

        eventos_indexados = []
        for evento in eventos_odds:
            home = _normalizar_nome_time(evento.get("home_team"))
            away = _normalizar_nome_time(evento.get("away_team"))
            odds_h2h = _escolher_melhor_odd_h2h(evento)
            if not home or not away or not odds_h2h:
                continue
            eventos_indexados.append(
                {
                    "id": evento.get("id"),
                    "home": home,
                    "away": away,
                    "odds": odds_h2h,
                }
            )

        for pred in candidatos_por_sport[sport_key]:
            match_ev = next(
                (evento for evento in eventos_indexados
                 if _nomes_equivalentes(evento["home"], pred.time_casa)
                 and _nomes_equivalentes(evento["away"], pred.time_visitante)),
                None,
            )
            if not match_ev:
                pred.odds_debug["status"] = "no_event_match"
                pred.odds_debug["reason"] = "não encontrou evento equivalente na consulta por liga"
                continue

            pred.odds_h2h = match_ev["odds"]
            pred.odds_match_id = match_ev["id"]
            pred.odds_debug["status"] = "matched"
            pred.odds_debug["reason"] = "odds h2h encontradas com sucesso"
            pred.odds_debug["odds_match_id"] = str(match_ev["id"])
            pred.odds_debug["bookmakers_outcomes"] = str(len(pred.odds_h2h or {}))


def _mapear_opcao_para_nome(opcao: str, pred: PredicaoJogo) -> str:
    opcao_u = str(opcao or "").upper()
    if opcao_u == "1":
        return pred.time_casa
    if opcao_u == "2":
        return pred.time_visitante
    if opcao_u == "X":
        return "Draw"
    return ""


def _probabilidades_justas_1x2(pred: PredicaoJogo) -> Dict[str, float]:
    """Converte odds 1X2 em probabilidades justas (sem overround / de-vig)."""
    odds_h2h = pred.odds_h2h or {}

    def _buscar_odd(opcao: str) -> Optional[float]:
        nome_alvo = _mapear_opcao_para_nome(opcao, pred)
        if not nome_alvo:
            return None

        for nome_odds, odd in odds_h2h.items():
            if _nomes_equivalentes(nome_odds, nome_alvo):
                try:
                    odd_decimal = float(odd)
                except (TypeError, ValueError):
                    return None
                return odd_decimal if odd_decimal > 1.0 else None

        if opcao == "X":
            for nome_odds, odd in odds_h2h.items():
                if _normalizar_nome_time(nome_odds) in ("draw", "empate"):
                    try:
                        odd_decimal = float(odd)
                    except (TypeError, ValueError):
                        return None
                    return odd_decimal if odd_decimal > 1.0 else None
        return None

    odd_1 = _buscar_odd("1")
    odd_x = _buscar_odd("X")
    odd_2 = _buscar_odd("2")
    if not odd_1 or not odd_x or not odd_2:
        return {}

    inv = {
        "1": 1.0 / odd_1,
        "X": 1.0 / odd_x,
        "2": 1.0 / odd_2,
    }
    soma_inv = sum(inv.values())
    if soma_inv <= 0:
        return {}

    return {opcao: valor / soma_inv for opcao, valor in inv.items()}


def aplicar_odds_e_valor(predicoes: List[PredicaoJogo]) -> List[PredicaoJogo]:
    for pred in predicoes:
        pred.odds_debug = {
            "enabled": str(ODDS_DEBUG_VISUAL).lower(),
            "status": "pending",
            "reason": "aguardando processamento de odds",
            "competition": pred.competicao,
            "sport_key": COMPETICAO_PARA_ODDS_SPORT.get(pred.competicao, ""),
        }

    if not ODDS_ENABLED:
        print("ℹ️  ODDS_API_KEY não definido. Seguindo sem odds externas.")
        for pred in predicoes:
            pred.odds_debug["status"] = "skip_no_api_key"
            pred.odds_debug["reason"] = "ODDS_API_KEY não configurada"
        return predicoes

    # Pré-gate para economizar cota: só busca odds para jogos com edge mínimo.
    candidatos = []
    for pred in predicoes:
        probs = sorted([pred.prob_casa, pred.prob_empate, pred.prob_visitante], reverse=True)
        edge_1x2 = probs[0] - probs[1]
        if edge_1x2 >= ODDS_MIN_EDGE_GATE:
            candidatos.append(pred)
            pred.odds_debug["status"] = "candidate"
            pred.odds_debug["reason"] = f"passou no gate de edge ({edge_1x2*100:.1f} p.p.)"
        else:
            pred.odds_debug["status"] = "skip_edge_gate"
            pred.odds_debug["reason"] = f"edge abaixo do gate ({edge_1x2*100:.1f} p.p. < {ODDS_MIN_EDGE_GATE*100:.1f} p.p.)"

    if not candidatos:
        print("ℹ️  Nenhum jogo passou no pré-filtro de edge para consulta de odds.")
        return [] if ODDS_ONLY_VALUE_GAMES else predicoes

    candidatos_por_sport: Dict[str, List[PredicaoJogo]] = {}
    for pred in candidatos:
        sport_key = COMPETICAO_PARA_ODDS_SPORT.get(pred.competicao)
        if not sport_key:
            pred.odds_debug["status"] = "skip_no_sport_mapping"
            pred.odds_debug["reason"] = "competição sem mapeamento para sport_key da Odds API"
            continue
        candidatos_por_sport.setdefault(sport_key, []).append(pred)

    if ODDS_USE_UPCOMING:
        origem = f"bookmakers={ODDS_BOOKMAKERS}" if ODDS_BOOKMAKERS else f"regions={ODDS_REGIONS}"
        print(f"🎯 Odds: consultando endpoint unico /sports/upcoming/odds para economizar cota ({origem}).")
        eventos_odds, quota_headers = _buscar_odds_h2h_upcoming()
        if quota_headers:
            print(
                f"   ↳ upcoming: custo {quota_headers.get('x-requests-last')} | "
                f"usado {quota_headers.get('x-requests-used')} | restante {quota_headers.get('x-requests-remaining')}"
            )

        eventos_indexados: Dict[str, List[Dict]] = {}
        sport_keys_relevantes = set(candidatos_por_sport.keys())
        eventos_relevantes = 0
        for evento in eventos_odds:
            sport_key = evento.get("sport_key")
            home = _normalizar_nome_time(evento.get("home_team"))
            away = _normalizar_nome_time(evento.get("away_team"))
            odds_h2h = _escolher_melhor_odd_h2h(evento)
            if not sport_key or not home or not away or not odds_h2h:
                continue

            if sport_key in sport_keys_relevantes:
                eventos_relevantes += 1

            eventos_indexados.setdefault(sport_key, []).append({
                "id": evento.get("id"),
                "home": home,
                "away": away,
                "odds": odds_h2h,
            })

        for sport_key, jogos in candidatos_por_sport.items():
            pool = eventos_indexados.get(sport_key, [])
            for pred in jogos:
                match_ev = next(
                    (evento for evento in pool
                     if _nomes_equivalentes(evento["home"], pred.time_casa)
                     and _nomes_equivalentes(evento["away"], pred.time_visitante)),
                    None,
                )
                if not match_ev:
                    pred.odds_debug["status"] = "no_event_match"
                    pred.odds_debug["reason"] = "não encontrou evento equivalente no retorno do endpoint upcoming"
                    continue
                pred.odds_h2h = match_ev["odds"]
                pred.odds_match_id = match_ev["id"]
                pred.odds_debug["status"] = "matched"
                pred.odds_debug["reason"] = "odds h2h encontradas com sucesso"
                pred.odds_debug["odds_match_id"] = str(match_ev["id"])
                pred.odds_debug["bookmakers_outcomes"] = str(len(pred.odds_h2h or {}))

        total_matches = sum(1 for pred in candidatos if pred.odds_match_id)
        if eventos_relevantes == 0 or total_matches == 0:
            motivo = "sem eventos relevantes" if eventos_relevantes == 0 else "sem matches de times"
            print(f"⚠️  Upcoming não trouxe futebol utilizável ({motivo}). Ativando fallback por liga.")
            _aplicar_odds_por_sport(candidatos_por_sport)
    else:
        _aplicar_odds_por_sport(candidatos_por_sport)

    jogos_valor = 0
    for pred in predicoes:
        palpites = gerar_palpites(pred)
        if any(p.valor_esperado_positivo for p in palpites):
            jogos_valor += 1
            pred.odds_debug["ev_filter"] = "pass"
            pred.odds_debug["ev_reason"] = f"há palpite com EV >= {ODDS_MIN_EV*100:.1f}%"
        else:
            pred.odds_debug["ev_filter"] = "fail"
            pred.odds_debug["ev_reason"] = f"nenhum palpite atingiu EV >= {ODDS_MIN_EV*100:.1f}%"

    print(f"✅ Jogos com EV >= {ODDS_MIN_EV*100:.1f}%: {jogos_valor} de {len(predicoes)}")
    if ODDS_ONLY_VALUE_GAMES:
        print("ℹ️  Modo visual atual: todos os jogos exibidos; jogos com valor recebem destaque especial.")
    return predicoes


def prever_jogo(match: Dict) -> PredicaoJogo:
    """Prevê resultado de um jogo"""
    
    home_team = match.get("homeTeam") or {}
    away_team = match.get("awayTeam") or {}
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    
    # Buscar históricos
    hist_home = buscar_historico_time(home_id, limit=10)
    hist_away = buscar_historico_time(away_id, limit=10)
    h2h = buscar_h2h(home_id, away_id, limit=5)
    
    # Calcular scores (forma, H2H) — mantidos para exibição e ajuste de forma
    score_home = calcular_score_time(hist_home, h2h, home_id, eh_em_casa=True)
    score_away = calcular_score_time(hist_away, h2h, away_id, eh_em_casa=False)

    # --- Modelo Dixon-Coles de gols esperados (λ) ---
    # Estatísticas brutas por posição (casa/fora)
    stats_home = calcular_estatisticas(hist_home, home_id, eh_em_casa=True)
    stats_away = calcular_estatisticas(hist_away, away_id, eh_em_casa=False)

    competicao_nome = match.get("competition", {}).get("name", "")
    media_liga = MEDIA_GOLS_LIGA.get(competicao_nome, MEDIA_GOLS_DEFAULT)
    media_por_time = media_liga / 2.0  # média de gols marcados por time por jogo na liga

    # Shrinkage: reduz volatilidade quando há poucos jogos casa/fora no recorte.
    home_marcados_aj = _media_com_shrinkage(stats_home.gols_marcados_media, media_por_time, stats_home.jogos)
    home_sofridos_aj = _media_com_shrinkage(stats_home.gols_sofridos_media, media_por_time, stats_home.jogos)
    away_marcados_aj = _media_com_shrinkage(stats_away.gols_marcados_media, media_por_time, stats_away.jogos)
    away_sofridos_aj = _media_com_shrinkage(stats_away.gols_sofridos_media, media_por_time, stats_away.jogos)

    # Força ofensiva/defensiva relativa à média da liga
    atk_home = home_marcados_aj / media_por_time if media_por_time else 1.0
    def_home = home_sofridos_aj / media_por_time if media_por_time else 1.0
    atk_away = away_marcados_aj / media_por_time if media_por_time else 1.0
    def_away = away_sofridos_aj / media_por_time if media_por_time else 1.0

    # Clamp: evitar distorções com poucos jogos no histórico
    atk_home = max(CLAMP_FORCA_MIN, min(atk_home, CLAMP_FORCA_MAX))
    def_home = max(CLAMP_FORCA_MIN, min(def_home, CLAMP_FORCA_MAX))
    atk_away = max(CLAMP_FORCA_MIN, min(atk_away, CLAMP_FORCA_MAX))
    def_away = max(CLAMP_FORCA_MIN, min(def_away, CLAMP_FORCA_MAX))

    # Fator de forma recente (±15% sobre λ com base nos últimos jogos)
    forma_fator_home = FATOR_FORMA_BASE + (score_home.forma_recente * FATOR_FORMA_ESCALA)
    forma_fator_away = FATOR_FORMA_BASE + (score_away.forma_recente * FATOR_FORMA_ESCALA)

    # Fadiga (back-to-back)
    fadiga_home = detectar_fadiga(hist_home, match.get("utcDate", ""))
    fadiga_away = detectar_fadiga(hist_away, match.get("utcDate", ""))

    # λ final: ataque × fraqueza defensiva adversária × média da liga × mando × forma × fadiga
    lambda_home = atk_home * def_away * media_por_time * HOME_ADVANTAGE * forma_fator_home * fadiga_home
    lambda_away = atk_away * def_home * media_por_time * forma_fator_away * fadiga_away

    # Clamp final de λ em valores plausíveis
    lambda_home = max(CLAMP_LAMBDA_MIN, min(lambda_home, CLAMP_LAMBDA_MAX))
    lambda_away = max(CLAMP_LAMBDA_MIN, min(lambda_away, CLAMP_LAMBDA_MAX))
    # --- fim Dixon-Coles ---

    mercados = calcular_probabilidades_mercado(lambda_home, lambda_away)
    
    tendencia_casa = calcular_tendencia_forma(hist_home, home_id)
    tendencia_visitante = calcular_tendencia_forma(hist_away, away_id)
    tg_home = calcular_tendencia_gols(hist_home, home_id)
    tg_away = calcular_tendencia_gols(hist_away, away_id)

    placar_casa, placar_visitante = _extrair_placar_partida_api(match)

    return PredicaoJogo(
        data_jogo=match.get("utcDate", ""),
        time_casa=home_team.get("shortName") or home_team.get("name") or "Time da casa",
        time_visitante=away_team.get("shortName") or away_team.get("name") or "Time visitante",
        escudo_casa=home_team.get("crest"),
        escudo_visitante=away_team.get("crest"),
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
        tendencia_gols_casa=tg_home,
        tendencia_gols_visitante=tg_away,
    )


def gerar_palpites(predicao: PredicaoJogo) -> List[BetSuggestion]:
    """Gera sugestões de aposta baseado na previsão.

    Confiança calculada por EDGE (margem sobre a segunda opção), não por probabilidade
    absoluta — evita classificar como HIGH mercados intrinsecamente incertos.
    """
    palpites = []
    mercados = calcular_probabilidades_mercado(
        predicao.gols_esperados_casa,
        predicao.gols_esperados_visitante,
    )

    odds_h2h = predicao.odds_h2h or {}

    def obter_odd_opcao(opcao: str) -> Optional[float]:
        nome_alvo = _mapear_opcao_para_nome(opcao, predicao)
        if not nome_alvo:
            return None

        for nome_odds, odd in odds_h2h.items():
            if _nomes_equivalentes(nome_odds, nome_alvo):
                return float(odd)

        if str(opcao).upper() == "X":
            for nome_odds, odd in odds_h2h.items():
                if _normalizar_nome_time(nome_odds) in ("draw", "empate"):
                    return float(odd)
        return None

    probs_mercado_justas = _probabilidades_justas_1x2(predicao)

    # ── Palpite: Vencedor ──────────────────────────────────────────────────────
    probs_1x2 = sorted(
        [(predicao.prob_casa, "1"), (predicao.prob_empate, "X"), (predicao.prob_visitante, "2")],
        key=lambda x: x[0], reverse=True,
    )
    prob_max, opcao = probs_1x2[0]
    # Edge = diferença entre 1° e 2° lugar (quanto o favorito se destaca)
    edge_winner = prob_max - probs_1x2[1][0]

    if edge_winner > 0.35:
        confianca = "HIGH"
    elif edge_winner > 0.12:
        confianca = "MEDIUM"
    else:
        confianca = "LOW"

    if opcao == "1":
        nome_fav = predicao.time_casa
        xg_fav = predicao.gols_esperados_casa
        xg_adv = predicao.gols_esperados_visitante
    elif opcao == "2":
        nome_fav = predicao.time_visitante
        xg_fav = predicao.gols_esperados_visitante
        xg_adv = predicao.gols_esperados_casa
    else:
        nome_fav = "Empate"
        xg_fav = xg_adv = None

    if xg_fav is not None:
        just_winner = (
            f"{nome_fav} projeta ≈{xg_fav:.1f} gol(s) vs ≈{xg_adv:.1f} do adversário. "
            f"Prob vitória: {prob_max*100:.1f}% (margem: {edge_winner*100:.1f} p.p.)"
        )
    else:
        just_winner = f"Jogo muito equilibrado. Prob empate: {prob_max*100:.1f}% (margem: {edge_winner*100:.1f} p.p.)"

    palpites.append(BetSuggestion(
        tipo="WINNER",
        opcao=opcao,
        probabilidade=prob_max,
        confianca=confianca,
        justificativa=just_winner,
        edge=round(edge_winner, 4),
        odd_decimal=obter_odd_opcao(opcao),
    ))

    p_winner = palpites[-1]
    if p_winner.odd_decimal is not None:
        p_winner.ev_bruto = round((p_winner.probabilidade * p_winner.odd_decimal) - 1.0, 4)
        prob_justa = probs_mercado_justas.get(p_winner.opcao)
        if prob_justa is not None and prob_justa > 0:
            p_winner.prob_mercado_justa = round(prob_justa, 4)
            p_winner.ev = round((p_winner.probabilidade / prob_justa) - 1.0, 4)
        else:
            p_winner.ev = p_winner.ev_bruto
        p_winner.valor_esperado_positivo = bool(p_winner.ev >= ODDS_MIN_EV)

    # ── Palpite: Over/Under (linha dinâmica) ──────────────────────────────────
    total_esperado = predicao.gols_esperados_casa + predicao.gols_esperados_visitante
    if total_esperado < 1.8:
        linha_ou = 1.5
        prob_over = mercados["over_15"]
        prob_under = mercados["under_15"]
    elif total_esperado > 3.2:
        linha_ou = 3.5
        prob_over = mercados["over_35"]
        prob_under = mercados["under_35"]
    else:
        linha_ou = 2.5
        prob_over = mercados["over_25"]
        prob_under = mercados["under_25"]

    side_ou = "OVER" if prob_over > prob_under else "UNDER"
    prob_ou = max(prob_over, prob_under)
    # Edge = distância de 50% (mercado binário — qualquer lado "bate" com 50%)
    edge_ou = prob_ou - 0.50
    opcao_ou = f"{side_ou}_{linha_ou:.1f}"

    if edge_ou > OU_BTTS_HIGH_THRESHOLD:
        confianca = "HIGH"
    elif edge_ou > OU_BTTS_MEDIUM_THRESHOLD:
        confianca = "MEDIUM"
    else:
        confianca = "LOW"

    # xG muito próximo da linha → incerteza alta, cap em MEDIUM
    if abs(total_esperado - linha_ou) < 0.4 and confianca == "HIGH":
        confianca = "MEDIUM"

    palpites.append(BetSuggestion(
        tipo="OVER_UNDER",
        opcao=opcao_ou,
        probabilidade=prob_ou,
        confianca=confianca,
        justificativa=(
            f"Gols esperados no jogo: ≈{total_esperado:.1f}. "
            f"{side_ou} {linha_ou}: {prob_ou*100:.1f}% de probabilidade"
        ),
        edge=round(edge_ou, 4),
    ))

    # ── Over 1.5 sempre disponível como palpite independente ─────────────────
    # (a linha dinâmica acima pode usar 2.5 ou 3.5; Over 1.5 existe separado)
    tg_casa = predicao.tendencia_gols_casa
    tg_visit = predicao.tendencia_gols_visitante
    tem_forma = tg_casa is not None and tg_visit is not None and tg_casa.jogos >= 5 and tg_visit.jogos >= 5

    prob_over15 = mercados["over_15"]
    if tem_forma:
        # Blenda Poisson com forma: P(ambos marcam) é subconjunto de Over 1.5
        # + P(um time marca 2+, outro não marca) capturado via Poisson residual
        btts_forma = tg_casa.prob_marca * tg_visit.prob_marca
        residuo_poisson = mercados["over_15"] - mercados["btts_yes"]  # P(só um time, mas ≥2 gols)
        prob_over15 = _clip_probabilidade(0.65 * mercados["over_15"] + 0.35 * (btts_forma + max(residuo_poisson, 0)))

    edge_over15 = prob_over15 - 0.50
    if edge_over15 > OU_BTTS_HIGH_THRESHOLD:
        conf_over15 = "HIGH"
    elif edge_over15 > OU_BTTS_MEDIUM_THRESHOLD:
        conf_over15 = "MEDIUM"
    else:
        conf_over15 = "LOW"

    forma_txt_over15 = ""
    if tem_forma:
        forma_txt_over15 = (
            f" | Forma: {tg_casa.prob_marca*100:.0f}% casa marca, "
            f"{tg_visit.prob_marca*100:.0f}% visit marca"
        )
    palpites.append(BetSuggestion(
        tipo="OVER_UNDER",
        opcao="OVER_1.5",
        probabilidade=round(prob_over15, 4),
        confianca=conf_over15,
        justificativa=(
            f"Pelo menos 2 gols no jogo. xG total: ≈{total_esperado:.1f}.{forma_txt_over15}"
        ),
        edge=round(edge_over15, 4),
    ))

    # ── Palpite: BTTS ──────────────────────────────────────────────────────────
    btts_yes = mercados["btts_yes"]
    btts_no = mercados["btts_no"]

    # Blenda Poisson (60%) com forma recente (40%) se houver dados suficientes
    if tem_forma:
        btts_forma = tg_casa.prob_marca * tg_visit.prob_marca
        btts_yes = _clip_probabilidade(0.60 * btts_yes + 0.40 * btts_forma)
        btts_no  = 1.0 - btts_yes

    # P(clean sheet) = e^(-λ): se qualquer time tem >30% de chance de não marcar,
    # forçar NO independentemente da matriz Poisson
    p_cs_casa = e ** (-predicao.gols_esperados_casa)
    p_cs_visitante = e ** (-predicao.gols_esperados_visitante)
    if p_cs_casa > 0.30 or p_cs_visitante > 0.30:
        btts_opcao = "NO"
        btts_prob = btts_no
    else:
        btts_opcao = "YES" if btts_yes >= btts_no else "NO"
        btts_prob = max(btts_yes, btts_no)

    edge_btts = btts_prob - 0.50

    if edge_btts > OU_BTTS_HIGH_THRESHOLD:
        confianca = "HIGH"
    elif edge_btts > OU_BTTS_MEDIUM_THRESHOLD:
        confianca = "MEDIUM"
    else:
        confianca = "LOW"

    xg_casa = predicao.gols_esperados_casa
    xg_fora = predicao.gols_esperados_visitante
    forma_txt_btts = ""
    if tem_forma:
        forma_txt_btts = (
            f" | Forma {tg_casa.sequencia_marca}j/{tg_visit.sequencia_marca}j consecutivos com gol"
        )
    palpites.append(BetSuggestion(
        tipo="BTTS",
        opcao=btts_opcao,
        probabilidade=round(btts_prob, 4),
        confianca=confianca,
        justificativa=(
            f"xG: {xg_casa:.1f} (casa) x {xg_fora:.1f} (fora). "
            f"Ambas marcam - {'Sim' if btts_opcao == 'YES' else 'Nao'}: {btts_prob*100:.1f}%{forma_txt_btts}"
        ),
        edge=round(edge_btts, 4),
    ))

    # ── Palpite: Empate vantajoso ──────────────────────────────────────────────
    defesa_casa = predicao.score_casa.defesa
    defesa_fora = predicao.score_visitante.defesa
    if predicao.prob_empate > 0.30 and defesa_casa > 0.50 and defesa_fora > 0.50:
        edge_emp = predicao.prob_empate - probs_1x2[1][0]
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
            edge=round(max(edge_emp, 0.0), 4),
            odd_decimal=obter_odd_opcao("X"),
        ))

        p_emp = palpites[-1]
        if p_emp.odd_decimal is not None:
            p_emp.ev_bruto = round((p_emp.probabilidade * p_emp.odd_decimal) - 1.0, 4)
            prob_justa = probs_mercado_justas.get("X")
            if prob_justa is not None and prob_justa > 0:
                p_emp.prob_mercado_justa = round(prob_justa, 4)
                p_emp.ev = round((p_emp.probabilidade / prob_justa) - 1.0, 4)
            else:
                p_emp.ev = p_emp.ev_bruto
            p_emp.valor_esperado_positivo = bool(p_emp.ev >= ODDS_MIN_EV)

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
                _ou_parts = p.opcao.split("_", 1)
                _ou_side  = _ou_parts[0]
                _ou_linha = float(_ou_parts[1]) if len(_ou_parts) > 1 else 2.5
                if total > _ou_linha and _ou_side == "OVER": p.resultado_verificador = "ACERTO"
                elif total < _ou_linha and _ou_side == "UNDER": p.resultado_verificador = "ACERTO"
                else: p.resultado_verificador = "ERRO"
            elif p.tipo == "BTTS":
                if home_g > 0 and away_g > 0 and p.opcao == "YES": p.resultado_verificador = "ACERTO"
                elif (home_g == 0 or away_g == 0) and p.opcao == "NO": p.resultado_verificador = "ACERTO"
                else: p.resultado_verificador = "ERRO"
            elif p.tipo == "EMPATE":
                if home_g == away_g and p.opcao == "X": p.resultado_verificador = "ACERTO"
                else: p.resultado_verificador = "ERRO"

    return palpites


def _verificar_palpites_dict(palpites: List[Dict], placar_casa: int, placar_visitante: int) -> None:
    """Atualiza resultado_verificador nos palpites (lista de dicts) com base no placar final.

    Mesma lógica de `gerar_palpites`, mas opera sobre dicts do JSON em vez de
    dataclasses BetSuggestion — usada pelo caminho de atualização leve.
    """
    home_g, away_g = placar_casa, placar_visitante
    for p in palpites:
        tipo  = p.get("tipo")
        opcao = p.get("opcao")
        if tipo == "WINNER":
            if   home_g > away_g  and opcao == "1": p["resultado_verificador"] = "ACERTO"
            elif home_g == away_g and opcao == "X": p["resultado_verificador"] = "ACERTO"
            elif home_g < away_g  and opcao == "2": p["resultado_verificador"] = "ACERTO"
            else:                                    p["resultado_verificador"] = "ERRO"
        elif tipo == "OVER_UNDER":
            total = home_g + away_g
            _ou_parts = opcao.split("_", 1)
            _ou_side  = _ou_parts[0]
            _ou_linha = float(_ou_parts[1]) if len(_ou_parts) > 1 else 2.5
            if   total > _ou_linha and _ou_side == "OVER":  p["resultado_verificador"] = "ACERTO"
            elif total < _ou_linha and _ou_side == "UNDER": p["resultado_verificador"] = "ACERTO"
            else:                                           p["resultado_verificador"] = "ERRO"
        elif tipo == "BTTS":
            ambos = home_g > 0 and away_g > 0
            if   ambos     and opcao == "YES": p["resultado_verificador"] = "ACERTO"
            elif not ambos and opcao == "NO":  p["resultado_verificador"] = "ACERTO"
            else:                              p["resultado_verificador"] = "ERRO"
        elif tipo == "EMPATE":
            if home_g == away_g and opcao == "X": p["resultado_verificador"] = "ACERTO"
            else:                                  p["resultado_verificador"] = "ERRO"


def _extrair_placar_jogo_json(jogo: Dict) -> Tuple[Optional[int], Optional[int]]:
    """Lê o placar do jogo no formato atual (placar_atual) com fallback legado."""
    placar = jogo.get("placar_atual") or {}
    casa = placar.get("casa")
    visitante = placar.get("visitante")

    # Compatibilidade com arquivos antigos que usavam campos no nível raiz.
    if casa is None:
        casa = jogo.get("placar_casa")
    if visitante is None:
        visitante = jogo.get("placar_visitante")

    return casa, visitante


def _coletar_placar_bloco(score: Dict, chave: str) -> Tuple[Optional[int], Optional[int]]:
    bloco = score.get(chave) or {}
    casa = bloco.get("home")
    visitante = bloco.get("away")
    if casa is None or visitante is None:
        return None, None
    return casa, visitante


def _extrair_placar_partida_api(match: Dict) -> Tuple[Optional[int], Optional[int]]:
    """Extrai placar da API com prioridade por status para evitar inconsistências."""
    status = str(match.get("status", "")).upper()
    score = match.get("score") or {}

    if status in ("IN_PLAY", "PAUSED"):
        # football-data.org usa fullTime como placar ao vivo durante IN_PLAY.
        # regularTime e halfTime só são populados em marcos (intervalo, fim de jogo).
        # Prioridade: fullTime → regularTime → halfTime.
        for chave in ("fullTime", "regularTime", "halfTime"):
            casa, visitante = _coletar_placar_bloco(score, chave)
            if casa is not None and visitante is not None:
                return int(casa), int(visitante)
        return None, None

    if status in ("FINISHED", "AWARDED"):
        for chave in ("fullTime", "regularTime", "halfTime"):
            casa, visitante = _coletar_placar_bloco(score, chave)
            if casa is not None and visitante is not None:
                return casa, visitante
        return None, None

    return None, None


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


def _normalizar_data_chave(data_utc: str) -> str:
    """Normaliza data para chave estável de identificação de jogo."""
    texto = str(data_utc or "")
    if not texto:
        return ""
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return texto[:16]


def _chave_jogo(data_utc: str, time_casa: str, time_visitante: str) -> str:
    data_norm = _normalizar_data_chave(data_utc)
    casa_norm = _normalizar_nome_time(time_casa)
    visit_norm = _normalizar_nome_time(time_visitante)
    return f"{data_norm}|{casa_norm}|{visit_norm}"


def _carregar_snapshots_pre_jogo(caminho_predicoes: str) -> Dict[str, Dict]:
    """Carrega snapshot do estado pré-jogo salvo no predictions.json anterior."""
    try:
        with open(caminho_predicoes, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    snapshots: Dict[str, Dict] = {}
    for jogo in dados.get("jogos", []):
        status = str(jogo.get("status", "")).upper()
        if status not in SNAPSHOT_BASELINE_SOURCE_STATUSES:
            continue

        times = jogo.get("times", {})
        probs = jogo.get("probabilidades", {})
        gols_esp = jogo.get("gols_esperados", {})
        scores = jogo.get("scores", {})

        chave = _chave_jogo(
            jogo.get("data", ""),
            times.get("casa", ""),
            times.get("visitante", ""),
        )
        if not chave:
            continue

        snapshots[chave] = {
            "prob_casa": probs.get("casa"),
            "prob_empate": probs.get("empate"),
            "prob_visitante": probs.get("visitante"),
            "gols_casa": gols_esp.get("casa"),
            "gols_visitante": gols_esp.get("visitante"),
            "score_casa": scores.get("casa", {}),
            "score_visitante": scores.get("visitante", {}),
            "tendencia": jogo.get("tendencia", {}),
        }

    return snapshots


def congelar_modelo_pre_jogo(predicoes: List[PredicaoJogo], caminho_predicoes: str = "predictions.json") -> List[PredicaoJogo]:
    """Evita drift de favorito após início da partida usando snapshot pré-jogo.

    Regras:
    - Jogos pré-jogo (SCHEDULED/TIMED): seguem cálculo atual.
    - Jogos iniciados/finalizados: usam snapshot pré-jogo salvo anteriormente.
    - Jogos iniciados sem snapshot: removidos da saída para não contaminar métricas.
    """
    snapshots = _carregar_snapshots_pre_jogo(caminho_predicoes)
    if not snapshots:
        return predicoes

    saida: List[PredicaoJogo] = []
    travados = 0
    removidos_sem_baseline = 0

    for pred in predicoes:
        status = str(pred.status or "").upper()
        if status in PRE_MATCH_STATUSES:
            saida.append(pred)
            continue

        chave = _chave_jogo(pred.data_jogo, pred.time_casa, pred.time_visitante)
        snap = snapshots.get(chave)
        if not snap:
            removidos_sem_baseline += 1
            continue

        try:
            pred.prob_casa = float(snap.get("prob_casa", pred.prob_casa))
            pred.prob_empate = float(snap.get("prob_empate", pred.prob_empate))
            pred.prob_visitante = float(snap.get("prob_visitante", pred.prob_visitante))
            pred.gols_esperados_casa = float(snap.get("gols_casa", pred.gols_esperados_casa))
            pred.gols_esperados_visitante = float(snap.get("gols_visitante", pred.gols_esperados_visitante))
        except (TypeError, ValueError):
            pass

        score_casa = snap.get("score_casa", {}) or {}
        score_visitante = snap.get("score_visitante", {}) or {}

        pred.score_casa = ScoreTempo(
            forma_recente=float(score_casa.get("forma_recente", pred.score_casa.forma_recente)),
            ataque=float(score_casa.get("ataque", pred.score_casa.ataque)),
            defesa=float(score_casa.get("defesa", pred.score_casa.defesa)),
            fator_mando=float(score_casa.get("fator_mando", pred.score_casa.fator_mando)),
            h2h_factor=float(score_casa.get("h2h_factor", pred.score_casa.h2h_factor)),
            score_total=float(score_casa.get("score_total", pred.score_casa.score_total)),
        )
        pred.score_visitante = ScoreTempo(
            forma_recente=float(score_visitante.get("forma_recente", pred.score_visitante.forma_recente)),
            ataque=float(score_visitante.get("ataque", pred.score_visitante.ataque)),
            defesa=float(score_visitante.get("defesa", pred.score_visitante.defesa)),
            fator_mando=float(score_visitante.get("fator_mando", pred.score_visitante.fator_mando)),
            h2h_factor=float(score_visitante.get("h2h_factor", pred.score_visitante.h2h_factor)),
            score_total=float(score_visitante.get("score_total", pred.score_visitante.score_total)),
        )

        tendencia = snap.get("tendencia", {}) or {}
        pred.tendencia_casa = str(tendencia.get("casa", pred.tendencia_casa))
        pred.tendencia_visitante = str(tendencia.get("visitante", pred.tendencia_visitante))

        pred.odds_debug["pre_match_locked"] = "true"
        pred.odds_debug["pre_match_lock_reason"] = "snapshot_pre_jogo"
        travados += 1
        saida.append(pred)

    if travados:
        print(f"🔒 Predições travadas no baseline pré-jogo para {travados} jogo(s) iniciado(s)/finalizado(s).")
    if removidos_sem_baseline:
        print(f"⚠️  {removidos_sem_baseline} jogo(s) iniciado(s)/finalizado(s) sem baseline pré-jogo foram ignorados para evitar viés.")

    return saida


def _montar_ranking_1x2(pred: PredicaoJogo) -> List[Dict[str, float | str]]:
    ranking = [
        {"nome": pred.time_casa, "prob": pred.prob_casa},
        {"nome": "Empate", "prob": pred.prob_empate},
        {"nome": pred.time_visitante, "prob": pred.prob_visitante},
    ]
    ranking.sort(key=lambda item: item["prob"], reverse=True)
    return ranking


def _descrever_cenario_gols(mercados: Dict[str, float], total_gols: float) -> str:
    if mercados["under_25"] >= 0.58:
        return (
            f"Jogo fechado esperado (xG total ≈{total_gols:.1f}). "
            f"Under 2.5 com {mercados['under_25']*100:.0f}%."
        )
    if mercados["over_25"] >= 0.55:
        return (
            f"Jogo mais aberto (xG total ≈{total_gols:.1f}). "
            f"Over 2.5 com {mercados['over_25']*100:.0f}%."
        )
    return f"Mercado de gols equilibrado (xG total ≈{total_gols:.1f})."


def _montar_texto_tendencia(pred: PredicaoJogo) -> str:
    tendencia_partes = []
    if pred.tendencia_casa not in ("estavel", "indefinida"):
        tendencia_partes.append(f"{pred.time_casa} {pred.tendencia_casa}")
    if pred.tendencia_visitante not in ("estavel", "indefinida"):
        tendencia_partes.append(f"{pred.time_visitante} {pred.tendencia_visitante}")
    if not tendencia_partes:
        return ""
    return " | Forma recente: " + ", ".join(tendencia_partes) + "."


def _montar_leitura_rapida_front(
    pred: PredicaoJogo,
    favorito: Dict[str, float | str],
    mercados: Dict[str, float],
) -> str:
    total_gols = pred.gols_esperados_casa + pred.gols_esperados_visitante
    confianca_fav = _texto_risco(float(favorito["prob"]))
    return (
        f"{favorito['nome']} favorito ({float(favorito['prob'])*100:.0f}%, risco {confianca_fav}). "
        f"{_descrever_cenario_gols(mercados, total_gols)}"
        f"{_montar_texto_tendencia(pred)}"
    )


def _coletar_alertas_front(pred: PredicaoJogo) -> List[str]:
    alertas = []
    fadiga_casa = detectar_fadiga(pred.historico_casa, pred.data_jogo)
    fadiga_visit = detectar_fadiga(pred.historico_visitante, pred.data_jogo)
    if fadiga_casa < 1.0:
        alertas.append(f"{pred.time_casa} jogou recentemente — possível desgaste físico.")
    if fadiga_visit < 1.0:
        alertas.append(f"{pred.time_visitante} jogou recentemente — possível desgaste físico.")
    return alertas


def _serializar_jogo_front(pred: PredicaoJogo) -> Dict:
    mercados = calcular_probabilidades_mercado(pred.gols_esperados_casa, pred.gols_esperados_visitante)
    ranking = _montar_ranking_1x2(pred)
    favorito = ranking[0]
    diferenca = max(0.0, float(ranking[0]["prob"]) - float(ranking[1]["prob"]))
    palpites = [asdict(item) for item in gerar_palpites(pred)]

    return {
        "competicao": pred.competicao,
        "data": pred.data_jogo,
        "status": pred.status,
        "placar_atual": {"casa": pred.placar_casa, "visitante": pred.placar_visitante},
        "times": {
            "casa": pred.time_casa,
            "visitante": pred.time_visitante,
            "escudo_casa": pred.escudo_casa,
            "escudo_visitante": pred.escudo_visitante,
        },
        "probabilidades": {
            "casa": pred.prob_casa,
            "empate": pred.prob_empate,
            "visitante": pred.prob_visitante,
        },
        "favorito": {"nome": favorito["nome"], "prob": favorito["prob"], "vantagem": diferenca},
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
        "scores": {"casa": asdict(pred.score_casa), "visitante": asdict(pred.score_visitante)},
        "leitura_rapida": _montar_leitura_rapida_front(pred, favorito, mercados),
        "tendencia": {"casa": pred.tendencia_casa, "visitante": pred.tendencia_visitante},
        "tendencia_gols": {
            "casa": (
                {
                    "prob_marca": pred.tendencia_gols_casa.prob_marca,
                    "prob_sofre": pred.tendencia_gols_casa.prob_sofre,
                    "sequencia_marca": pred.tendencia_gols_casa.sequencia_marca,
                    "sequencia_sofre": pred.tendencia_gols_casa.sequencia_sofre,
                    "jogos": pred.tendencia_gols_casa.jogos,
                }
                if pred.tendencia_gols_casa else None
            ),
            "visitante": (
                {
                    "prob_marca": pred.tendencia_gols_visitante.prob_marca,
                    "prob_sofre": pred.tendencia_gols_visitante.prob_sofre,
                    "sequencia_marca": pred.tendencia_gols_visitante.sequencia_marca,
                    "sequencia_sofre": pred.tendencia_gols_visitante.sequencia_sofre,
                    "jogos": pred.tendencia_gols_visitante.jogos,
                }
                if pred.tendencia_gols_visitante else None
            ),
        },
        "alertas": _coletar_alertas_front(pred),
        "alerta_ia": None,
        "odds_debug": pred.odds_debug,
        "odds_integradas": any(item.get("odd_decimal") is not None for item in palpites),
        "odds_valor_alto": any(item.get("valor_esperado_positivo") for item in palpites),
        "historico": {
            "casa": _normalizar_historico_para_front(pred.historico_casa, pred.time_casa),
            "visitante": _normalizar_historico_para_front(pred.historico_visitante, pred.time_visitante),
        },
        "palpites": palpites,
    }


def _calcular_resumo_acertos_front(jogos: List[Dict]) -> Dict[str, Optional[float] | int]:
    total_acertos = sum(
        1 for jogo in jogos
        for palpite in jogo.get("palpites", [])
        if palpite.get("resultado_verificador") == "ACERTO"
    )
    total_com_resultado = sum(
        1 for jogo in jogos
        for palpite in jogo.get("palpites", [])
        if palpite.get("resultado_verificador") is not None
    )
    return {
        "acertos": total_acertos,
        "total": total_com_resultado,
        "taxa": round(total_acertos / total_com_resultado, 3) if total_com_resultado else None,
    }


def _carregar_json_existente(caminho_saida: str) -> Dict:
    try:
        with open(caminho_saida, "r", encoding="utf-8") as arquivo:
            return json.load(arquivo)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _chave_id_jogo_front(jogo: Dict) -> Tuple[str, str, str]:
    return (
        jogo.get("times", {}).get("casa", ""),
        jogo.get("times", {}).get("visitante", ""),
        jogo.get("data", ""),
    )


def _palpite_principal_front(jogo: Optional[Dict]) -> Optional[Dict]:
    if not jogo:
        return None
    palpites = jogo.get("palpites", []) or []
    return next((p for p in palpites if p.get("valor_esperado_positivo") is True), palpites[0] if palpites else None)


def _selecionar_daily_tips_ids(jogos: List[Dict], existing_data: Dict, hoje: str) -> List[Dict]:
    """Seleciona top N palpites com maior probabilidade (mais seguros).
    
    Retorna palpites com: casa, visitante, data, tipo, opcao, probabilidade.
    """
    if existing_data.get("daily_tips_date") == hoje and existing_data.get("daily_tips_ids"):
        return existing_data["daily_tips_ids"]

    # Coletar todos os palpites dos jogos válidos com probabilidade
    candidatos_palpites = []
    for jogo in jogos:
        if (jogo["status"] in ("FINISHED", "AWARDED") or 
            jogo["competicao"] in COMPETICOES_EXCLUIDAS_DICAS):
            continue
        
        for palpite in jogo.get("palpites", []):
            candidatos_palpites.append({
                "casa": jogo["times"]["casa"],
                "visitante": jogo["times"]["visitante"],
                "data": jogo["data"],
                "tipo": palpite.get("tipo"),
                "opcao": palpite.get("opcao"),
                "probabilidade": palpite.get("probabilidade", 0.0),
            })
    
    # Ordenar por probabilidade (descendente)
    candidatos_palpites.sort(key=lambda p: p.get("probabilidade", 0.0), reverse=True)
    
    n_total = len(jogos)
    n_dicas = 3 if n_total >= 10 else (2 if n_total > 5 else 1)
    
    return candidatos_palpites[:n_dicas]


def _normalizar_recovery_tip(recovery_tip: Optional[Dict]) -> Optional[Dict]:
    if not recovery_tip or not recovery_tip.get("ativo"):
        return recovery_tip

    jogo_recovery = recovery_tip.get("jogo") or {}
    casa_recovery = (jogo_recovery.get("times") or {}).get("casa") or jogo_recovery.get("casa") or ""
    visitante_recovery = (jogo_recovery.get("times") or {}).get("visitante") or jogo_recovery.get("visitante") or ""
    escudo_casa = (jogo_recovery.get("times") or {}).get("escudo_casa")
    escudo_visitante = (jogo_recovery.get("times") or {}).get("escudo_visitante")

    recovery_tip["jogo"] = {
        **jogo_recovery,
        "casa": casa_recovery,
        "visitante": visitante_recovery,
        "times": {
            **(jogo_recovery.get("times") or {}),
            "casa": casa_recovery,
            "visitante": visitante_recovery,
            "escudo_casa": escudo_casa,
            "escudo_visitante": escudo_visitante,
        },
    }
    return recovery_tip


def _criar_recovery_tip(jogos: List[Dict], ids_dicas: set[Tuple[str, str, str]]) -> Dict:
    melhor_jogo = None
    melhor_palpite = None
    melhor_prob = -1.0
    melhor_conf = -1

    for jogo in jogos:
        jid = _chave_id_jogo_front(jogo)
        if jid in ids_dicas:
            continue
        if jogo.get("status") in ("FINISHED", "AWARDED"):
            continue
        if jogo.get("competicao") in COMPETICOES_EXCLUIDAS_DICAS:
            continue

        for palpite in jogo.get("palpites", []) or []:
            conf = str(palpite.get("confianca", "LOW")).upper()
            prob = float(palpite.get("probabilidade") or 0.0)
            conf_score = SCORE_CONFIANCA.get(conf, 1)
            if prob > melhor_prob or (prob == melhor_prob and conf_score > melhor_conf):
                melhor_prob = prob
                melhor_conf = conf_score
                melhor_jogo = jogo
                melhor_palpite = palpite

    if not melhor_jogo or not melhor_palpite:
        return {"ativo": False}

    return {
        "ativo": True,
        "disparado_em": datetime.now(APP_TIMEZONE).isoformat(timespec="seconds"),
        "jogo": {
            "casa": melhor_jogo.get("times", {}).get("casa", ""),
            "visitante": melhor_jogo.get("times", {}).get("visitante", ""),
            "data": melhor_jogo.get("data", ""),
            "competicao": melhor_jogo.get("competicao", ""),
            "times": {
                "casa": melhor_jogo.get("times", {}).get("casa", ""),
                "visitante": melhor_jogo.get("times", {}).get("visitante", ""),
                "escudo_casa": melhor_jogo.get("times", {}).get("escudo_casa"),
                "escudo_visitante": melhor_jogo.get("times", {}).get("escudo_visitante"),
            },
        },
        "palpite": {
            "tipo": melhor_palpite.get("tipo"),
            "opcao": melhor_palpite.get("opcao"),
            "probabilidade": melhor_palpite.get("probabilidade"),
            "confianca": melhor_palpite.get("confianca"),
        },
    }


def _resolver_recovery_tip(jogos: List[Dict], daily_tips_ids: List[Dict], existing_data: Dict, hoje: str) -> Dict:
    jogos_por_id = {_chave_id_jogo_front(jogo): jogo for jogo in jogos}

    dica_1_palpite = None
    dica_1_jogo = None
    
    # Buscar o primeiro palpite (dica mais segura)
    for item in daily_tips_ids:
        jogo = jogos_por_id.get((item.get("casa", ""), item.get("visitante", ""), item.get("data", "")))
        if jogo:
            # Buscar o palpite específico desta dica
            for palpite in jogo.get("palpites", []):
                if (palpite.get("tipo") == item.get("tipo") and 
                    palpite.get("opcao") == item.get("opcao")):
                    dica_1_palpite = palpite
                    dica_1_jogo = jogo
                    break
        if dica_1_palpite:
            break

    erro_na_dica_1 = (dica_1_palpite or {}).get("resultado_verificador") == "ERRO"
    recovery_tip = None
    if existing_data.get("daily_tips_date") == hoje:
        recovery_tip = _normalizar_recovery_tip(existing_data.get("recovery_tip"))

    if (recovery_tip or {}).get("ativo"):
        return recovery_tip
    if not erro_na_dica_1:
        return {"ativo": False}

    # Se a dica 1 errou, buscar um palpite alternativo que não seja das dicas
    ids_dicas = {
        (item.get("casa", ""), item.get("visitante", ""), item.get("data", ""))
        for item in daily_tips_ids
    }
    return _criar_recovery_tip(jogos, ids_dicas)


def exportar_predicoes_front(predicoes: List[PredicaoJogo], caminho_saida: str = "predictions.json") -> None:
    hoje = datetime.now(APP_TIMEZONE).date().isoformat()
    dados = {
        "generated_at": datetime.now(APP_TIMEZONE).isoformat(timespec="seconds"),
        "analysis_date": hoje,
        "total_jogos": len(predicoes),
        "odds_debug_visual": ODDS_DEBUG_VISUAL,
        "odds_only_value_games": ODDS_ONLY_VALUE_GAMES,
        "odds_min_ev": ODDS_MIN_EV,
        "jogos": [_serializar_jogo_front(pred) for pred in predicoes],
    }

    dados["acertos_hoje"] = _calcular_resumo_acertos_front(dados["jogos"])

    existing_data = _carregar_json_existente(caminho_saida)
    daily_tips_ids = _selecionar_daily_tips_ids(dados["jogos"], existing_data, hoje)
    dados["daily_tips_ids"] = daily_tips_ids
    dados["daily_tips_date"] = hoje
    dados["recovery_tip"] = _resolver_recovery_tip(dados["jogos"], daily_tips_ids, existing_data, hoje)
    dados["recovery_tip_date"] = hoje

    with open(caminho_saida, "w", encoding="utf-8") as arquivo_saida:
        json.dump(dados, arquivo_saida, ensure_ascii=False, indent=2)


def atualizar_historico_do_json(dados_predictions: Dict, caminho: str = "history.json") -> None:
    """Versão leve de atualizar_historico: lê jogos finalizados diretamente do
    dicionário predictions (já em memória) em vez de receber List[PredicaoJogo].

    Usada pelo caminho de atualização rápida para não reprocessar análises.
    """
    agora_local = datetime.now(APP_TIMEZONE)
    hoje = agora_local.date().isoformat()
    agora = agora_local.isoformat(timespec="seconds")

    try:
        with open(caminho, "r", encoding="utf-8") as f:
            historico = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        historico = {"dias": []}

    dias = historico.get("dias", [])
    idx_existente = next((i for i, d in enumerate(dias) if d["data"] == hoje), None)
    dia_existente = dias[idx_existente] if idx_existente is not None else {}
    jogos_existentes = list(dia_existente.get("jogos", []) or [])

    def _chave_hist(data_jogo: str, casa: str, visitante: str) -> Tuple[str, str, str]:
        return (
            _normalizar_data_chave(data_jogo),
            _normalizar_nome_time(casa),
            _normalizar_nome_time(visitante),
        )

    chaves_existentes = {
        _chave_hist(j.get("data_jogo", ""), j.get("casa", ""), j.get("visitante", ""))
        for j in jogos_existentes
    }

    mercados_stats: Dict[str, Dict] = {}
    metricas_prob = {
        "1X2":       {"n": 0, "brier_soma": 0.0, "logloss_soma": 0.0},
        "OVER_UNDER": {"n": 0, "brier_soma": 0.0, "logloss_soma": 0.0},
        "BTTS":       {"n": 0, "brier_soma": 0.0, "logloss_soma": 0.0},
    }
    jogos_novos = []

    finalizados_json = []
    for j in dados_predictions.get("jogos", []):
        if j.get("status") not in ("FINISHED", "AWARDED"):
            continue
        placar_casa, placar_visit = _extrair_placar_jogo_json(j)
        if placar_casa is None or placar_visit is None:
            continue
        finalizados_json.append(j)

    for jogo in finalizados_json:
        times = jogo.get("times", {})
        casa = times.get("casa", "")
        visitante = times.get("visitante", "")
        chave = _chave_hist(jogo.get("data", ""), casa, visitante)
        if chave in chaves_existentes:
            # Atualizar resultado_verificador nos jogos existentes se mudou
            for j_ex in jogos_existentes:
                if _chave_hist(j_ex.get("data_jogo", ""), j_ex.get("casa", ""), j_ex.get("visitante", "")) == chave:
                    palpites_json = {p["tipo"]: p for p in jogo.get("palpites", []) if "tipo" in p}
                    for p_ex in j_ex.get("palpites", []):
                        tipo = p_ex.get("tipo")
                        atualizado = palpites_json.get(tipo, {})
                        novo_res = atualizado.get("resultado_verificador")
                        if novo_res and not p_ex.get("resultado"):
                            p_ex["resultado"] = novo_res
            continue

        palpites_raw = jogo.get("palpites", []) or []
        com_resultado = [p for p in palpites_raw if p.get("resultado_verificador") is not None]
        if not com_resultado:
            continue

        placar_casa_raw, placar_visit_raw = _extrair_placar_jogo_json(jogo)
        if placar_casa_raw is None or placar_visit_raw is None:
            continue
        placar_casa = int(placar_casa_raw)
        placar_visit = int(placar_visit_raw)

        jogos_novos.append({
            "data_jogo": jogo.get("data", ""),
            "casa": casa,
            "visitante": visitante,
            "competicao": jogo.get("competicao", ""),
            "placar": f"{placar_casa}-{placar_visit}",
            "palpites": [
                {
                    "tipo": p.get("tipo"),
                    "opcao": p.get("opcao"),
                    "confianca": p.get("confianca"),
                    "probabilidade": round(float(p.get("probabilidade") or 0), 3),
                    "resultado": p.get("resultado_verificador"),
                }
                for p in com_resultado
            ],
        })

        # Métricas probabilísticas
        prob_casa   = float(jogo.get("probabilidades", {}).get("casa", 0.5) or 0.5)
        prob_emp    = float(jogo.get("probabilidades", {}).get("empate", 0.25) or 0.25)
        prob_visit  = float(jogo.get("probabilidades", {}).get("visitante", 0.25) or 0.25)
        over_25     = float(jogo.get("mercados", {}).get("over_25", 0.5) or 0.5)
        btts_yes    = float(jogo.get("mercados", {}).get("btts_yes", 0.5) or 0.5)
        total_gols  = placar_casa + placar_visit

        if placar_casa > placar_visit:   idx_real = 0
        elif placar_casa == placar_visit: idx_real = 1
        else:                             idx_real = 2

        probs_1x2  = [prob_casa, prob_emp, prob_visit]
        one_hot    = [1.0 if i == idx_real else 0.0 for i in range(3)]
        brier_1x2  = sum((probs_1x2[i] - one_hot[i]) ** 2 for i in range(3))
        logloss_1x2 = -log(_clip_probabilidade(probs_1x2[idx_real]))
        metricas_prob["1X2"]["n"] += 1
        metricas_prob["1X2"]["brier_soma"]   += brier_1x2
        metricas_prob["1X2"]["logloss_soma"] += logloss_1x2

        y_over  = 1.0 if total_gols > 2.5 else 0.0
        p_over  = _clip_probabilidade(over_25)
        metricas_prob["OVER_UNDER"]["n"] += 1
        metricas_prob["OVER_UNDER"]["brier_soma"]   += (p_over - y_over) ** 2
        metricas_prob["OVER_UNDER"]["logloss_soma"] += -(y_over * log(p_over) + (1 - y_over) * log(1 - p_over))

        y_btts  = 1.0 if (placar_casa > 0 and placar_visit > 0) else 0.0
        p_btts  = _clip_probabilidade(btts_yes)
        metricas_prob["BTTS"]["n"] += 1
        metricas_prob["BTTS"]["brier_soma"]   += (p_btts - y_btts) ** 2
        metricas_prob["BTTS"]["logloss_soma"] += -(y_btts * log(p_btts) + (1 - y_btts) * log(1 - p_btts))

    jogos_dia = jogos_existentes + jogos_novos
    total_acertos = 0
    total_com_resultado = 0

    for jogo_hist in jogos_dia:
        for palpite in jogo_hist.get("palpites", []):
            resultado = palpite.get("resultado")
            tipo = palpite.get("tipo")
            if resultado is None or not tipo:
                continue
            est = mercados_stats.setdefault(tipo, {"acertos": 0, "total": 0})
            est["total"] += 1
            total_com_resultado += 1
            if resultado == "ACERTO":
                est["acertos"] += 1
                total_acertos += 1

    for est in mercados_stats.values():
        est["taxa"] = round(est["acertos"] / est["total"], 3) if est["total"] else 0.0

    metricas_resumo: Dict[str, Dict] = {}
    metricas_antigas = dia_existente.get("metricas_probabilisticas", {}) if dia_existente else {}
    for mercado, valores in metricas_prob.items():
        n_novo = valores["n"]
        antigo = metricas_antigas.get(mercado, {}) if isinstance(metricas_antigas, dict) else {}
        n_antigo = int(antigo.get("n") or 0)
        brier_ant = antigo.get("brier")
        logloss_ant = antigo.get("log_loss")
        soma_b_ant  = (float(brier_ant)   * n_antigo) if (n_antigo and brier_ant   is not None) else 0.0
        soma_l_ant  = (float(logloss_ant) * n_antigo) if (n_antigo and logloss_ant is not None) else 0.0
        n_total = n_antigo + n_novo
        soma_b  = soma_b_ant  + valores["brier_soma"]
        soma_l  = soma_l_ant  + valores["logloss_soma"]
        metricas_resumo[mercado] = {
            "n": n_total,
            "brier":    round(soma_b / n_total, 4) if n_total else None,
            "log_loss": round(soma_l / n_total, 4) if n_total else None,
        }

    entrada = {
        "data": hoje,
        "ultima_atualizacao": agora,
        "finalizados": len(jogos_dia),
        "taxa_geral": round(total_acertos / total_com_resultado, 3) if total_com_resultado else 0.0,
        "total_acertos": total_acertos,
        "total_palpites": total_com_resultado,
        "mercados": mercados_stats,
        "metricas_probabilisticas": metricas_resumo,
        "jogos": jogos_dia,
    }

    if idx_existente is not None:
        dias[idx_existente] = entrada
    else:
        dias.insert(0, entrada)

    historico["dias"] = dias[:5]
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)

    if total_com_resultado:
        b = entrada["metricas_probabilisticas"]["1X2"]["brier"]
        l = entrada["metricas_probabilisticas"]["1X2"]["log_loss"]
        print(
            f"📈 Histórico: {total_acertos}/{total_com_resultado} acertos hoje ({entrada['taxa_geral']*100:.0f}%)"
            f" | Brier 1X2: {b if b is not None else '-'}"
            f" | LogLoss 1X2: {l if l is not None else '-'}"
            f" → {caminho}"
        )
    else:
        print(f"📈 Histórico atualizado (sem resultado verificável ainda) → {caminho}")


def atualizar_historico(predicoes: List[PredicaoJogo], caminho: str = "history.json") -> None:
    """Acumula resultados dos jogos finalizados em history.json (últimos 5 dias)."""
    agora_local = datetime.now(APP_TIMEZONE)
    hoje = agora_local.date().isoformat()
    agora = agora_local.isoformat(timespec="seconds")

    try:
        with open(caminho, "r", encoding="utf-8") as arquivo_leitura:
            historico = json.load(arquivo_leitura)
    except (FileNotFoundError, json.JSONDecodeError):
        historico = {"dias": []}

    dias = historico.get("dias", [])
    idx_existente = next((i for i, d in enumerate(dias) if d["data"] == hoje), None)
    dia_existente = dias[idx_existente] if idx_existente is not None else {}
    jogos_existentes = list(dia_existente.get("jogos", []) or [])

    def _chave_historico_jogo(data_jogo: str, casa: str, visitante: str) -> Tuple[str, str, str]:
        return (
            _normalizar_data_chave(data_jogo),
            _normalizar_nome_time(casa),
            _normalizar_nome_time(visitante),
        )

    chaves_existentes = {
        _chave_historico_jogo(j.get("data_jogo", ""), j.get("casa", ""), j.get("visitante", ""))
        for j in jogos_existentes
    }

    finalizados = [
        p for p in predicoes
        if p.status == "FINISHED" and p.placar_casa is not None and p.placar_visitante is not None
    ]

    mercados_stats: Dict[str, Dict] = {}
    metricas_prob = {
        "1X2": {"n": 0, "brier_soma": 0.0, "logloss_soma": 0.0},
        "OVER_UNDER": {"n": 0, "brier_soma": 0.0, "logloss_soma": 0.0},
        "BTTS": {"n": 0, "brier_soma": 0.0, "logloss_soma": 0.0},
    }
    jogos_novos = []

    for predicao_finalizada in finalizados:
        chave_jogo = _chave_historico_jogo(
            predicao_finalizada.data_jogo,
            predicao_finalizada.time_casa,
            predicao_finalizada.time_visitante,
        )
        if chave_jogo in chaves_existentes:
            continue

        palpites_pred = gerar_palpites(predicao_finalizada)
        com_resultado = [p for p in palpites_pred if p.resultado_verificador is not None]
        if not com_resultado:
            continue

        jogos_novos.append({
            "data_jogo": predicao_finalizada.data_jogo,
            "casa": predicao_finalizada.time_casa,
            "visitante": predicao_finalizada.time_visitante,
            "competicao": predicao_finalizada.competicao,
            "placar": f"{predicao_finalizada.placar_casa}-{predicao_finalizada.placar_visitante}",
            "palpites": [
                {
                    "tipo": p.tipo,
                    "opcao": p.opcao,
                    "confianca": p.confianca,
                    "probabilidade": round(p.probabilidade, 3),
                    "resultado": p.resultado_verificador,
                }
                for p in com_resultado
            ],
        })

        total_gols = predicao_finalizada.placar_casa + predicao_finalizada.placar_visitante
        mercados_partida = calcular_probabilidades_mercado(
            predicao_finalizada.gols_esperados_casa,
            predicao_finalizada.gols_esperados_visitante,
        )

        # Avaliacao probabilistica multiclasse para 1X2.
        if predicao_finalizada.placar_casa > predicao_finalizada.placar_visitante:
            idx_real = 0
        elif predicao_finalizada.placar_casa == predicao_finalizada.placar_visitante:
            idx_real = 1
        else:
            idx_real = 2

        probs_1x2 = [
            predicao_finalizada.prob_casa,
            predicao_finalizada.prob_empate,
            predicao_finalizada.prob_visitante,
        ]
        one_hot_1x2 = [1.0 if i == idx_real else 0.0 for i in range(3)]
        brier_1x2 = sum((probs_1x2[i] - one_hot_1x2[i]) ** 2 for i in range(3))
        logloss_1x2 = -log(_clip_probabilidade(probs_1x2[idx_real]))
        metricas_prob["1X2"]["n"] += 1
        metricas_prob["1X2"]["brier_soma"] += brier_1x2
        metricas_prob["1X2"]["logloss_soma"] += logloss_1x2

        # Avaliacao binaria para OVER/UNDER 2.5.
        y_over = 1.0 if total_gols > 2.5 else 0.0
        p_over = _clip_probabilidade(mercados_partida["over_25"])
        brier_over = (p_over - y_over) ** 2
        logloss_over = -(y_over * log(p_over) + (1.0 - y_over) * log(1.0 - p_over))
        metricas_prob["OVER_UNDER"]["n"] += 1
        metricas_prob["OVER_UNDER"]["brier_soma"] += brier_over
        metricas_prob["OVER_UNDER"]["logloss_soma"] += logloss_over

        # Avaliacao binaria para BTTS.
        y_btts = 1.0 if (predicao_finalizada.placar_casa > 0 and predicao_finalizada.placar_visitante > 0) else 0.0
        p_btts = _clip_probabilidade(mercados_partida["btts_yes"])
        brier_btts = (p_btts - y_btts) ** 2
        logloss_btts = -(y_btts * log(p_btts) + (1.0 - y_btts) * log(1.0 - p_btts))
        metricas_prob["BTTS"]["n"] += 1
        metricas_prob["BTTS"]["brier_soma"] += brier_btts
        metricas_prob["BTTS"]["logloss_soma"] += logloss_btts

    jogos_dia = jogos_existentes + jogos_novos
    total_acertos = 0
    total_com_resultado = 0

    for jogo in jogos_dia:
        for palpite in jogo.get("palpites", []):
            resultado = palpite.get("resultado")
            tipo = palpite.get("tipo")
            if resultado is None or not tipo:
                continue
            estatisticas = mercados_stats.setdefault(tipo, {"acertos": 0, "total": 0})
            estatisticas["total"] += 1
            total_com_resultado += 1
            if resultado == "ACERTO":
                estatisticas["acertos"] += 1
                total_acertos += 1

    for estatisticas in mercados_stats.values():
        estatisticas["taxa"] = round(estatisticas["acertos"] / estatisticas["total"], 3) if estatisticas["total"] else 0.0

    metricas_prob_resumo: Dict[str, Dict[str, Optional[float]]] = {}
    metricas_antigas = dia_existente.get("metricas_probabilisticas", {}) if dia_existente else {}
    for mercado, valores in metricas_prob.items():
        n_novo = valores["n"]
        soma_brier_novo = valores["brier_soma"]
        soma_logloss_novo = valores["logloss_soma"]

        antigo = metricas_antigas.get(mercado, {}) if isinstance(metricas_antigas, dict) else {}
        n_antigo = int(antigo.get("n") or 0)
        brier_antigo = antigo.get("brier")
        logloss_antigo = antigo.get("log_loss")

        soma_brier_antigo = (float(brier_antigo) * n_antigo) if (n_antigo and brier_antigo is not None) else 0.0
        soma_logloss_antigo = (float(logloss_antigo) * n_antigo) if (n_antigo and logloss_antigo is not None) else 0.0

        n_total = n_antigo + n_novo
        soma_brier_total = soma_brier_antigo + soma_brier_novo
        soma_logloss_total = soma_logloss_antigo + soma_logloss_novo

        metricas_prob_resumo[mercado] = {
            "n": n_total,
            "brier": round(soma_brier_total / n_total, 4) if n_total else None,
            "log_loss": round(soma_logloss_total / n_total, 4) if n_total else None,
        }

    entrada = {
        "data": hoje,
        "ultima_atualizacao": agora,
        "finalizados": len(jogos_dia),
        "taxa_geral": round(total_acertos / total_com_resultado, 3) if total_com_resultado else 0.0,
        "total_acertos": total_acertos,
        "total_palpites": total_com_resultado,
        "mercados": mercados_stats,
        "metricas_probabilisticas": metricas_prob_resumo,
        "jogos": jogos_dia,
    }

    if idx_existente is not None:
        dias[idx_existente] = entrada
    else:
        dias.insert(0, entrada)

    historico["dias"] = dias[:5]

    with open(caminho, "w", encoding="utf-8") as arquivo_escrita:
        json.dump(historico, arquivo_escrita, ensure_ascii=False, indent=2)

    if total_com_resultado:
        brier_1x2 = entrada["metricas_probabilisticas"]["1X2"]["brier"]
        logloss_1x2 = entrada["metricas_probabilisticas"]["1X2"]["log_loss"]
        print(
            f"📈 Histórico: {total_acertos}/{total_com_resultado} acertos hoje ({entrada['taxa_geral']*100:.0f}%)"
            f" | Brier 1X2: {brier_1x2 if brier_1x2 is not None else '-'}"
            f" | LogLoss 1X2: {logloss_1x2 if logloss_1x2 is not None else '-'}"
            f" → {caminho}"
        )
    else:
        print(f"📈 Histórico atualizado ({len(finalizados)} finalizado(s), sem resultado verificável ainda) → {caminho}")


def atualizar_status_jogos(
    caminho_predicoes: str = "predictions.json",
    caminho_historico: str = "history.json",
) -> None:
    """Atualização leve: atualiza só status, placar e resultado_verificador.

    Executado quando a análise completa do dia já foi realizada. Faz apenas
    1 chamada de API (busca os jogos do dia) em vez de N × 3 chamadas mais
    N × 12 s de espera da análise completa. Todas as probabilidades, scores,
    gols esperados e palpites são preservados intactos do run anterior.
    """
    print("🔄 Análise já concluída hoje — atualizando apenas status e placares...")

    # ── 1. Buscar estado atual dos jogos (1 chamada de API) ──────────────────
    matches_atuais = buscar_jogos_permitidos()

    # Alerta de possível atraso da fonte (API mantém status pré-jogo por muito tempo).
    stale_warning_hours = float(os.getenv("API_STALE_WARNING_HOURS", "6"))
    agora_utc = datetime.now(timezone.utc)
    jogos_potencialmente_desatualizados: List[Dict[str, str]] = []

    for m in matches_atuais:
        status_atual = str(m.get("status", "") or "").upper()
        if status_atual not in PRE_MATCH_STATUSES:
            continue

        try:
            data_jogo = datetime.fromisoformat(str(m.get("utcDate", "")).replace("Z", "+00:00"))
            if data_jogo.tzinfo is None:
                data_jogo = data_jogo.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if agora_utc < data_jogo:
            continue

        last_updated_raw = str(m.get("lastUpdated", "") or "")
        try:
            last_updated = datetime.fromisoformat(last_updated_raw.replace("Z", "+00:00"))
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        horas_sem_update = (agora_utc - last_updated).total_seconds() / 3600.0
        if horas_sem_update < stale_warning_hours:
            continue

        home = m.get("homeTeam", {}).get("shortName") or m.get("homeTeam", {}).get("name", "")
        away = m.get("awayTeam", {}).get("shortName") or m.get("awayTeam", {}).get("name", "")
        jogos_potencialmente_desatualizados.append(
            {
                "id": str(m.get("id", "?")),
                "status": status_atual,
                "home": str(home),
                "away": str(away),
                "last_updated": last_updated.isoformat(),
                "hours": f"{horas_sem_update:.1f}",
            }
        )

    if jogos_potencialmente_desatualizados:
        print(
            "⚠️  API possivelmente desatualizada para "
            f"{len(jogos_potencialmente_desatualizados)} jogo(s) do dia "
            f"(sem atualização há >= {stale_warning_hours:.1f}h)."
        )
        print("⏳ Processando resultado: aguardando consolidação oficial da API para os jogos abaixo.")
        for item in jogos_potencialmente_desatualizados:
            print(
                f"   - ID {item['id']} | {item['home']} x {item['away']} "
                f"| status={item['status']} | aviso=Processando resultado "
                f"| lastUpdated={item['last_updated']} "
                f"({item['hours']}h)"
            )

    lookup: Dict[str, Dict] = {}
    for m in matches_atuais:
        home = m.get("homeTeam", {}).get("shortName") or m.get("homeTeam", {}).get("name", "")
        away = m.get("awayTeam", {}).get("shortName") or m.get("awayTeam", {}).get("name", "")
        lookup[_chave_jogo(m.get("utcDate", ""), home, away)] = m

    def _buscar_match_aproximado(jogo_json: Dict) -> Optional[Dict]:
        """Fallback para variações de nome (shortName/nome completo) no pós-jogo."""
        times = jogo_json.get("times", {})
        data_norm = _normalizar_data_chave(jogo_json.get("data", ""))
        casa_json = str(times.get("casa", "") or "")
        visitante_json = str(times.get("visitante", "") or "")
        competicao_json = str(jogo_json.get("competicao", "") or "")

        candidatos: List[Dict] = []
        for match in matches_atuais:
            if _normalizar_data_chave(match.get("utcDate", "")) != data_norm:
                continue

            home_api = match.get("homeTeam", {}).get("shortName") or match.get("homeTeam", {}).get("name", "")
            away_api = match.get("awayTeam", {}).get("shortName") or match.get("awayTeam", {}).get("name", "")
            if _nomes_equivalentes(casa_json, home_api) and _nomes_equivalentes(visitante_json, away_api):
                candidatos.append(match)

        if not candidatos:
            return None

        if len(candidatos) == 1:
            return candidatos[0]

        # Critério de desempate: mesma competição do jogo salvo.
        for match in candidatos:
            comp_api = str(match.get("competition", {}).get("name", "") or "")
            if comp_api == competicao_json:
                return match

        return candidatos[0]

    # ── 2. Carregar predictions existente ────────────────────────────────────
    try:
        with open(caminho_predicoes, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"❌ Não foi possível ler {caminho_predicoes}: {exc}")
        return

    hoje = datetime.now(APP_TIMEZONE).date().isoformat()
    atualizados = 0

    # ── 3. Aplicar updates de status/placar ──────────────────────────────────
    for jogo in dados.get("jogos", []):
        times = jogo.get("times", {})
        chave = _chave_jogo(
            jogo.get("data", ""),
            times.get("casa", ""),
            times.get("visitante", ""),
        )
        match = lookup.get(chave)
        if not match:
            match = _buscar_match_aproximado(jogo)
        if not match:
            continue

        novo_status = match.get("status", jogo.get("status"))
        novo_casa, novo_visit = _extrair_placar_partida_api(match)
        placar_atual = jogo.get("placar_atual")
        if not isinstance(placar_atual, dict):
            placar_atual = {}
            jogo["placar_atual"] = placar_atual

        casa_ant, visit_ant = _extrair_placar_jogo_json(jogo)

        mudou = (
            jogo.get("status") != novo_status
            or (novo_casa is not None and casa_ant != novo_casa)
            or (novo_visit is not None and visit_ant != novo_visit)
        )
        if not mudou:
            continue

        atualizados    += 1
        jogo["status"] = novo_status
        if novo_casa is not None:
            placar_atual["casa"] = novo_casa
            if "placar_casa" in jogo:
                del jogo["placar_casa"]
        if novo_visit is not None:
            placar_atual["visitante"] = novo_visit
            if "placar_visitante" in jogo:
                del jogo["placar_visitante"]

        # Re-verificar palpites se jogo finalizado
        if novo_status in ("FINISHED", "AWARDED") and novo_casa is not None and novo_visit is not None:
            _verificar_palpites_dict(jogo.get("palpites", []), int(novo_casa), int(novo_visit))

    print(f"{'✅' if atualizados else 'ℹ️ '} {atualizados} jogo(s) com mudanças de status/placar.")

    # ── 4. Recalcular acertos_hoje ───────────────────────────────────────────
    total_acertos = sum(
        1 for j in dados["jogos"]
        for p in j.get("palpites", [])
        if p.get("resultado_verificador") == "ACERTO"
    )
    total_com_resultado = sum(
        1 for j in dados["jogos"]
        for p in j.get("palpites", [])
        if p.get("resultado_verificador") is not None
    )
    dados["acertos_hoje"] = {
        "acertos":      total_acertos,
        "total":        total_com_resultado,
        "taxa": round(total_acertos / total_com_resultado, 3) if total_com_resultado else None,
    }

    # ── 5. Recovery tip ──────────────────────────────────────────────────────
    # Reutiliza a mesma lógica do exportar_predicoes_front sem duplicar código.
    # Determinar se dica_1 falhou.
    def _chave_id(jogo: Dict) -> Tuple[str, str, str]:
        return (
            jogo.get("times", {}).get("casa", ""),
            jogo.get("times", {}).get("visitante", ""),
            jogo.get("data", ""),
        )

    daily_tips_ids = dados.get("daily_tips_ids") or []
    ids_dicas = {
        (item.get("casa", ""), item.get("visitante", ""), item.get("data", ""))
        for item in daily_tips_ids
    }
    jogos_por_id: Dict[Tuple[str, str, str], Dict] = {
        _chave_id(j): j for j in dados.get("jogos", [])
    }

    dica_1 = None
    for item in daily_tips_ids:
        jid = (item.get("casa", ""), item.get("visitante", ""), item.get("data", ""))
        j = jogos_por_id.get(jid)
        if j:
            dica_1 = j
            break

    def _palpite_principal(jogo: Optional[Dict]) -> Optional[Dict]:
        if not jogo:
            return None
        pals = jogo.get("palpites", []) or []
        return next((p for p in pals if p.get("valor_esperado_positivo")), pals[0] if pals else None)

    palpite_dica_1 = _palpite_principal(dica_1)
    erro_na_dica_1 = (palpite_dica_1 or {}).get("resultado_verificador") == "ERRO"

    recovery_tip = dados.get("recovery_tip") if dados.get("recovery_tip_date") == hoje else None

    if recovery_tip and recovery_tip.get("ativo"):
        jogo_recovery = recovery_tip.get("jogo") or {}
        casa_recovery = (jogo_recovery.get("times") or {}).get("casa") or jogo_recovery.get("casa") or ""
        visitante_recovery = (jogo_recovery.get("times") or {}).get("visitante") or jogo_recovery.get("visitante") or ""
        recovery_tip["jogo"] = {
            **jogo_recovery,
            "casa": casa_recovery,
            "visitante": visitante_recovery,
            "times": {
                **(jogo_recovery.get("times") or {}),
                "casa": casa_recovery,
                "visitante": visitante_recovery,
            },
        }

    recovery_ativo = bool((recovery_tip or {}).get("ativo"))

    if erro_na_dica_1 or recovery_ativo:
        if not recovery_ativo:
            _excluidas = {"Campeonato Brasileiro Série A", "Campeonato Brasileiro Série B"}
            melhor_jogo, melhor_palpite, melhor_prob, melhor_conf = None, None, -1.0, -1
            score_conf = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
            for jogo in dados.get("jogos", []):
                if _chave_id(jogo) in ids_dicas: continue
                if jogo.get("status") in ("FINISHED", "AWARDED"): continue
                if jogo.get("competicao") in _excluidas: continue
                for p in jogo.get("palpites", []) or []:
                    conf = str(p.get("confianca", "LOW")).upper()
                    prob = float(p.get("probabilidade") or 0.0)
                    cs = score_conf.get(conf, 1)
                    if prob > melhor_prob or (prob == melhor_prob and cs > melhor_conf):
                        melhor_prob, melhor_conf = prob, cs
                        melhor_jogo, melhor_palpite = jogo, p
            if melhor_jogo and melhor_palpite:
                recovery_tip = {
                    "ativo": True,
                    "disparado_em": datetime.now(APP_TIMEZONE).isoformat(timespec="seconds"),
                    "jogo": {
                        "casa":       melhor_jogo.get("times", {}).get("casa", ""),
                        "visitante":  melhor_jogo.get("times", {}).get("visitante", ""),
                        "data":       melhor_jogo.get("data", ""),
                        "competicao": melhor_jogo.get("competicao", ""),
                        "times": {
                            "casa": melhor_jogo.get("times", {}).get("casa", ""),
                            "visitante": melhor_jogo.get("times", {}).get("visitante", ""),
                        },
                    },
                    "palpite": {
                        "tipo":         melhor_palpite.get("tipo"),
                        "opcao":        melhor_palpite.get("opcao"),
                        "probabilidade":melhor_palpite.get("probabilidade"),
                        "confianca":    melhor_palpite.get("confianca"),
                    },
                }

    dados["recovery_tip"]      = recovery_tip if recovery_tip else {"ativo": False}
    dados["recovery_tip_date"] = hoje

    # Sincronizar resultado_verificador do palpite de recuperação com o jogo finalizado
    rt = dados["recovery_tip"]
    if rt.get("ativo") and rt.get("palpite"):
        rt_times = (rt.get("jogo") or {}).get("times") or rt.get("jogo") or {}
        rt_casa   = rt_times.get("casa", "")
        rt_visit  = rt_times.get("visitante", "")
        rt_tipo   = rt["palpite"].get("tipo")
        rt_opcao  = rt["palpite"].get("opcao")
        for _jogo in dados.get("jogos", []):
            if (_jogo.get("times", {}).get("casa") == rt_casa
                    and _jogo.get("times", {}).get("visitante") == rt_visit):
                for _p in _jogo.get("palpites", []):
                    if _p.get("tipo") == rt_tipo and _p.get("opcao") == rt_opcao:
                        rt["palpite"]["resultado_verificador"] = _p.get("resultado_verificador")
                        break
                break

    # ── 6. Revisão Gemini (se ainda não feita hoje) ───────────────────────────
    if dados.get("gemini_revisado_em") != hoje:
        ia_ok = revisar_predicoes_com_ia(dados.get("jogos", []))
        if ia_ok:
            dados["gemini_revisado_em"] = hoje

    # ── 7. Timestamp e salvar ─────────────────────────────────────────────────
    dados["generated_at"] = datetime.now(APP_TIMEZONE).isoformat(timespec="seconds")

    with open(caminho_predicoes, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    print(f"💾 {caminho_predicoes} atualizado.")

    # ── 7. Atualizar histórico ────────────────────────────────────────────────
    atualizar_historico_do_json(dados, caminho_historico)
    print("💾 Arquivos atualizados: predictions.json | history.json")


def exibir_predicoes(predicoes: List[PredicaoJogo]) -> None:
    """Exibe todas as previsões e palpites"""
    
    print("\n" + "=" * 100)
    print("  🎯  ANÁLISE E PALPITES")
    print("=" * 100 + "\n")
    
    for pred in predicoes:
        nome_casa = pred.time_casa or "Time da casa"
        nome_visitante = pred.time_visitante or "Time visitante"

        mercados = calcular_probabilidades_mercado(
            pred.gols_esperados_casa,
            pred.gols_esperados_visitante,
        )

        ranking = [
            (nome_casa, pred.prob_casa),
            ("Empate", pred.prob_empate),
            (nome_visitante, pred.prob_visitante),
        ]
        ranking.sort(key=lambda item: item[1], reverse=True)
        favorito, prob_favorito = ranking[0]
        segunda_forca, prob_segunda = ranking[1]
        diferenca = max(0.0, prob_favorito - prob_segunda)

        print(f"🏟️  {nome_casa} vs {nome_visitante}")
        print(f"  ├─ Mercado 1X2: Casa {pred.prob_casa*100:>5.1f}% | X {pred.prob_empate*100:>5.1f}% | Fora {pred.prob_visitante*100:>5.1f}%")
        print(f"  ├─ Ranking de chance:")
        print(f"  │    1) {ranking[0][0]:<18} {ranking[0][1]*100:>5.1f}% [{_barra_percentual(ranking[0][1])}]")
        print(f"  │    2) {ranking[1][0]:<18} {ranking[1][1]*100:>5.1f}% [{_barra_percentual(ranking[1][1])}]")
        print(f"  │    3) {ranking[2][0]:<18} {ranking[2][1]*100:>5.1f}% [{_barra_percentual(ranking[2][1])}]")
        print(f"  ├─ Favorito: {favorito} ({prob_favorito*100:.1f}%) | vantagem: {diferenca*100:.1f} p.p. sobre {segunda_forca}")
        print(f"  ├─ Gols esperados (xG simplificado): {pred.gols_esperados_casa:.2f} x {pred.gols_esperados_visitante:.2f} | total {pred.gols_esperados_casa + pred.gols_esperados_visitante:.2f}")
        print(f"  ├─ Mercado de gols: Under 2.5 {mercados['under_25']*100:.1f}% | Over 2.5 {mercados['over_25']*100:.1f}%")
        print(f"  ├─ Ambos marcam (BTTS): SIM {mercados['btts_yes']*100:.1f}% | NÃO {mercados['btts_no']*100:.1f}%")
        print(f"  ├─ Score {nome_casa}: {pred.score_casa.score_total:.2f} (Forma: {pred.score_casa.forma_recente:.2f}, Ataque: {pred.score_casa.ataque:.2f}, Defesa: {pred.score_casa.defesa:.2f})")
        print(f"  ├─ Score {nome_visitante}: {pred.score_visitante.score_total:.2f} (Forma: {pred.score_visitante.forma_recente:.2f}, Ataque: {pred.score_visitante.ataque:.2f}, Defesa: {pred.score_visitante.defesa:.2f})")
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
            extra = ""
            if p.odd_decimal is not None and p.ev is not None:
                sinal_valor = "💰" if p.valor_esperado_positivo else ""
                if p.ev_bruto is not None and abs(p.ev - p.ev_bruto) > 1e-9:
                    extra = (
                        f" | odd {p.odd_decimal:.2f}"
                        f" | EV justo {p.ev*100:.1f}%"
                        f" | EV bruto {p.ev_bruto*100:.1f}% {sinal_valor}"
                    )
                else:
                    extra = f" | odd {p.odd_decimal:.2f} | EV {p.ev*100:.1f}% {sinal_valor}"
            print(f"     {icon_conf} [{p.tipo}] {p.opcao}: {p.probabilidade*100:.1f}% ({p.confianca}) - {p.justificativa}{extra}")
        
        print("\n" + "-" * 100 + "\n")


def _analise_do_dia_concluida(caminho_predicoes: str, hoje: str) -> bool:
    dados_existentes = _carregar_json_existente(caminho_predicoes)
    return dados_existentes.get("analysis_date") == hoje and bool(dados_existentes.get("jogos"))


def _gerar_predicoes_do_dia(jogos: List[Dict]) -> List[PredicaoJogo]:
    predicoes = []
    print(f"⏳ Processando jogos... (~{len(jogos) * 12 // 60} min estimados)")
    for match in jogos:
        try:
            predicoes.append(prever_jogo(match))
            time.sleep(12)
        except Exception as e:
            print(f"⚠️  Erro ao processar jogo: {e}")
    return predicoes


def revisar_predicoes_com_ia(jogos: List[Dict]) -> None:
    """Revisão contextual diária com Gemini Flash + web search.
    Para cada jogo, o Gemini busca contexto que o modelo estatístico não
    captura (motivação, lesões, jogo de volta, rebaixamento confirmado,
    poupança de titulares) e retorna um alerta curto em português ou null.
    Modifica os dicts de jogos in-place, adicionando o campo `alerta_ia`.
    Falhas silenciosas — nunca interrompe o fluxo principal.
    """
    if not GEMINI_API_KEY:
        print("ℹ️  GEMINI_API_KEY não definida. Pulando revisão com IA.")
        return False
    # ── Montar payload compacto para economizar tokens ──────────────────
    jogos_resumo = []
    for jogo in jogos:
        times   = jogo.get("times", {})
        fav     = jogo.get("favorito", {})
        palpites = jogo.get("palpites", []) or []
        winner_p = next((p for p in palpites if p.get("tipo") == "WINNER"), {})
        def _form(historico: List[Dict]) -> str:
            return " ".join(
                j.get("resultado", "?") for j in (historico or [])[:3]
            )
        hist = jogo.get("historico", {})
        jogos_resumo.append({
            "competicao":   jogo.get("competicao", ""),
            "data":         jogo.get("data", "")[:10],
            "casa":         times.get("casa", ""),
            "visitante":    times.get("visitante", ""),
            "favorito":     fav.get("nome", ""),
            "prob_fav":     round(float(fav.get("prob", 0)), 2),
            "winner_opcao": winner_p.get("opcao", ""),
            "winner_conf":  winner_p.get("confianca", ""),
            "forma_casa":   _form(hist.get("casa", [])),
            "forma_visit":  _form(hist.get("visitante", [])),
            "alertas_modelo": jogo.get("alertas", []),
        })
    # ── Prompt ───────────────────────────────────────────────────────────
    prompt = f"""Você é um analista de futebol. Analise as previsões abaixo geradas por modelo estatístico.
Para CADA jogo, avalie se existe algum contexto importante que o modelo não captura e que possa invalidar ou enfraquecer a previsão. Exemplos: time já rebaixado ou campeão sem motivação, jogo de volta com agregado favorável ao visitante, titulares poupados para outra competição, lesão de jogador chave, derby com dinâmica histórica especial, time viajando para altitude extrema.
REGRAS ESTRITAS:
- Retorne APENAS um array JSON compacto (sem indentação, sem quebras de linha entre campos).
- Um objeto por linha, na mesma ordem recebida.
- Campo "alerta": string curta em português, máximo 80 caracteres, SEM quebras de linha. Use null se não houver risco concreto.
- Seja conservador: só alerte quando houver informação concreta, não suposições.
FORMATO EXATO (uma linha por jogo):
[{{"casa":"NomeExato","visitante":"NomeExato","alerta":"texto"}},{{"casa":"NomeExato","visitante":"NomeExato","alerta":null}}]
JOGOS:
{json.dumps(jogos_resumo, ensure_ascii=False)}
"""
    # ── Chamada à API ────────────────────────────────────────────────────
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":        0.2,
            "maxOutputTokens":    4096,
            "responseMimeType":   "application/json",
        },
    }
    try:
        print(f"🤖 Revisando {len(jogos)} jogo(s) com Gemini Flash ({GEMINI_MODEL})...")
        resp = requests.post(
            GEMINI_ENDPOINT,
            headers={"X-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        print("⚠️  Gemini: timeout após 90s — revisão ignorada neste ciclo.")
        return False
    except requests.exceptions.ConnectionError as exc:
        print(f"⚠️  Gemini: falha de conexão (DNS/rede) — {exc}")
        return False
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        corpo  = exc.response.text[:300] if exc.response is not None else ""
        if status == 400:
            print(f"⚠️  Gemini 400 Bad Request — payload inválido. Detalhe: {corpo}")
        elif status in (401, 403):
            print(f"⚠️  Gemini {status} — GEMINI_API_KEY inválida ou sem permissão. Verifique a chave.")
        elif status == 429:
            print("⚠️  Gemini 429 — quota excedida. Revisão ignorada neste ciclo.")
        else:
            print(f"⚠️  Gemini HTTP {status}: {corpo}")
        return False
    except requests.exceptions.RequestException as exc:
        print(f"⚠️  Gemini erro inesperado: {exc}")
        return False
    # ── Extrair texto da resposta ────────────────────────────────────────
    try:
        candidates = data.get("candidates", [])
        candidate  = candidates[0]
        finish     = candidate.get("finishReason", "UNKNOWN")
        if finish not in ("STOP", "MAX_TOKENS"):
            print(f"⚠️  Gemini finishReason inesperado: {finish}")
        if finish == "MAX_TOKENS":
            print("⚠️  Gemini atingiu MAX_TOKENS — resposta pode estar truncada.")
        texto = candidate["content"]["parts"][0]["text"].strip()
    except (IndexError, KeyError, TypeError) as exc:
        print(f"⚠️  Resposta Gemini inesperada (estrutura fora do padrão): {exc}")
        print(f"    Resposta recebida: {str(data)[:300]}")
        return False
    # Remove possível markdown ```json ... ``` que o modelo às vezes adiciona
    if texto.startswith("```"):
        linhas = texto.splitlines()
        texto  = "\n".join(
            l for l in linhas
            if not l.strip().startswith("```")
        ).strip()
    # Sanitizar newlines literais dentro de strings JSON (o modelo às vezes quebra linhas)
    # Percorre char a char para substituir \n literal por espaço apenas dentro de strings
    _buf: List[str] = []
    _in_str = False
    _i = 0
    while _i < len(texto):
        _c = texto[_i]
        if _c == "\\" and _in_str:
            _buf.append(_c)
            _i += 1
            if _i < len(texto):
                _buf.append(texto[_i])
            _i += 1
            continue
        if _c == '"':
            _in_str = not _in_str
        if _c == "\n" and _in_str:
            _buf.append(" ")
        else:
            _buf.append(_c)
        _i += 1
    texto = "".join(_buf)

    # ── Parsear JSON e injetar alertas ───────────────────────────────────
    try:
        alertas_ia: List[Dict] = json.loads(texto)
    except json.JSONDecodeError as exc:
        print(f"⚠️  JSON inválido do Gemini: {exc}\nTexto recebido: {texto[:300]}")
        return False
    # Indexar por (casa, visitante) para matching rápido
    mapa_alertas: Dict[tuple, Optional[str]] = {}
    for item in alertas_ia:
        chave = (
            _normalizar_nome_time(item.get("casa", "")),
            _normalizar_nome_time(item.get("visitante", "")),
        )
        mapa_alertas[chave] = item.get("alerta") or None
    alertas_aplicados = 0
    for jogo in jogos:
        times = jogo.get("times", {})
        chave = (
            _normalizar_nome_time(times.get("casa", "")),
            _normalizar_nome_time(times.get("visitante", "")),
        )
        alerta = mapa_alertas.get(chave)
        jogo["alerta_ia"] = alerta
        if alerta:
            alertas_aplicados += 1
    print(
        f"✅ Revisão IA concluída: {alertas_aplicados} alerta(s) gerado(s) "
        f"em {len(jogos)} jogo(s)."
    )
    return True


def _executar_analise_completa() -> None:
    print("🌐 Buscando jogos das competições permitidas...")
    jogos = buscar_jogos_permitidos()

    if not jogos:
        print("❌ Nenhum jogo encontrado.")
        return

    print(f"📊 Encontrados {len(jogos)} jogo(s). Analisando...\n")
    predicoes = _gerar_predicoes_do_dia(jogos)
    predicoes = aplicar_odds_e_valor(predicoes)

    if not predicoes:
        print("ℹ️  Nenhum jogo com valor esperado positivo para exibir no momento.")
        exportar_predicoes_front([], "predictions.json")
        return

    predicoes.sort(key=lambda pred: pred.data_jogo)
    predicoes = congelar_modelo_pre_jogo(predicoes, "predictions.json")

    if not predicoes:
        print("ℹ️  Nenhum jogo elegível após aplicar baseline pré-jogo.")
        exportar_predicoes_front([], "predictions.json")
        return

    exibir_predicoes(predicoes)
    exportar_predicoes_front(predicoes, "predictions.json")
    # Revisão contextual com IA — roda 1x por dia; flag impede re-chamada na pista rápida
    dados_exportados = _carregar_json_existente("predictions.json")
    ia_ok = revisar_predicoes_com_ia(dados_exportados.get("jogos", []))
    if ia_ok:
        dados_exportados["gemini_revisado_em"] = datetime.now(APP_TIMEZONE).date().isoformat()
    with open("predictions.json", "w", encoding="utf-8") as _f_ia:
        json.dump(dados_exportados, _f_ia, ensure_ascii=False, indent=2)
    print("💾 predictions.json atualizado com revisão da IA.")
    atualizar_historico(predicoes, "history.json")
    print("💾 Arquivos gerados: predictions.json | history.json")


def main():
    """Fluxo principal.

    Decisão de execução:
    - Se predictions.json já tiver `analysis_date == hoje` → atualização leve
      (1 chamada de API, sem re-analisar histórico/H2H dos times).
    - Caso contrário → análise completa (pipeline original).
    """
    hoje = datetime.now(APP_TIMEZONE).date().isoformat()

    if _analise_do_dia_concluida("predictions.json", hoje):
        atualizar_status_jogos("predictions.json", "history.json")
        return
    _executar_analise_completa()


if __name__ == "__main__":
    main()