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
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from math import factorial, e
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
HOME_ADVANTAGE = 1.22

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
    odds_h2h: Optional[Dict[str, float]] = None
    odds_match_id: Optional[str] = None
    odds_debug: Dict[str, str] = field(default_factory=dict)


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
    valor_esperado_positivo: bool = False
    resultado_verificador: Optional[str] = None


def buscar_jogos_permitidos() -> List[Dict]:
    """Busca jogos das competições permitidas do dia atual"""

    url = f"{API_BASE}/matches/"

    print("📅 Buscando jogos de hoje...")

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
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
    
    home_team = match.get("homeTeam", {})
    away_team = match.get("awayTeam", {})
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

    # Força ofensiva/defensiva relativa à média da liga
    atk_home = stats_home.gols_marcados_media / media_por_time if media_por_time else 1.0
    def_home = stats_home.gols_sofridos_media / media_por_time if media_por_time else 1.0
    atk_away = stats_away.gols_marcados_media / media_por_time if media_por_time else 1.0
    def_away = stats_away.gols_sofridos_media / media_por_time if media_por_time else 1.0

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

    # ── Palpite: Vencedor ──────────────────────────────────────────────────────
    probs_1x2 = sorted(
        [(predicao.prob_casa, "1"), (predicao.prob_empate, "X"), (predicao.prob_visitante, "2")],
        key=lambda x: x[0], reverse=True,
    )
    prob_max, opcao = probs_1x2[0]
    # Edge = diferença entre 1° e 2° lugar (quanto o favorito se destaca)
    edge_winner = prob_max - probs_1x2[1][0]

    if edge_winner > 0.25:
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
        p_winner.ev = round((p_winner.probabilidade * p_winner.odd_decimal) - 1.0, 4)
        p_winner.valor_esperado_positivo = bool(p_winner.ev >= ODDS_MIN_EV)

    # ── Palpite: Over/Under 2.5 ────────────────────────────────────────────────
    prob_over = mercados["over_25"]
    prob_under = mercados["under_25"]
    bet_type = "OVER" if prob_over > prob_under else "UNDER"
    prob_ou = max(prob_over, prob_under)
    # Edge = distância de 50% (mercado binário — qualquer lado "bate" com 50%)
    edge_ou = prob_ou - 0.50
    total_esperado = predicao.gols_esperados_casa + predicao.gols_esperados_visitante

    if edge_ou > 0.15:
        confianca = "HIGH"
    elif edge_ou > 0.07:
        confianca = "MEDIUM"
    else:
        confianca = "LOW"

    palpites.append(BetSuggestion(
        tipo="OVER_UNDER",
        opcao=bet_type,
        probabilidade=prob_ou,
        confianca=confianca,
        justificativa=(
            f"Gols esperados no jogo: ≈{total_esperado:.1f}. "
            f"{'UNDER' if bet_type == 'UNDER' else 'OVER'} 2.5: {prob_ou*100:.1f}% de probabilidade"
        ),
        edge=round(edge_ou, 4),
    ))

    # ── Palpite: BTTS ──────────────────────────────────────────────────────────
    btts_yes = mercados["btts_yes"]
    btts_no = mercados["btts_no"]
    btts_opcao = "YES" if btts_yes >= btts_no else "NO"
    btts_prob = max(btts_yes, btts_no)
    edge_btts = btts_prob - 0.50

    if edge_btts > 0.15:
        confianca = "HIGH"
    elif edge_btts > 0.07:
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
            p_emp.ev = round((p_emp.probabilidade * p_emp.odd_decimal) - 1.0, 4)
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
        "odds_debug_visual": ODDS_DEBUG_VISUAL,
        "odds_only_value_games": ODDS_ONLY_VALUE_GAMES,
        "odds_min_ev": ODDS_MIN_EV,
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

        palpites_brutos = gerar_palpites(pred)
        palpites = [asdict(item) for item in palpites_brutos]
        odds_integradas = any(item.get("odd_decimal") is not None for item in palpites)
        odds_valor_alto = any(item.get("valor_esperado_positivo") for item in palpites)

        # Alertas contextuais para o front-end
        alertas = []
        fadiga_casa = detectar_fadiga(pred.historico_casa, pred.data_jogo)
        fadiga_visit = detectar_fadiga(pred.historico_visitante, pred.data_jogo)
        if fadiga_casa < 1.0:
            alertas.append(f"{pred.time_casa} jogou recentemente — possível desgaste físico.")
        if fadiga_visit < 1.0:
            alertas.append(f"{pred.time_visitante} jogou recentemente — possível desgaste físico.")

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
                "alertas": alertas,
                "odds_debug": pred.odds_debug,
                "odds_integradas": odds_integradas,
                "odds_valor_alto": odds_valor_alto,
                "historico": {
                    "casa": _normalizar_historico_para_front(pred.historico_casa, pred.time_casa),
                    "visitante": _normalizar_historico_para_front(pred.historico_visitante, pred.time_visitante),
                },
                "palpites": palpites,
            }
        )

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
        "acertos": total_acertos,
        "total": total_com_resultado,
        "taxa": round(total_acertos / total_com_resultado, 3) if total_com_resultado else None,
    }

    # Congela as dicas do dia no primeiro run; preserva nas atualizações seguintes
    hoje = datetime.now().strftime("%Y-%m-%d")
    daily_tips_ids = None
    try:
        with open(caminho_saida, "r", encoding="utf-8") as f_existing:
            existing_data = json.load(f_existing)
        if existing_data.get("daily_tips_date") == hoje:
            daily_tips_ids = existing_data.get("daily_tips_ids")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    if daily_tips_ids is None:
        _excluidas_dicas = {"Campeonato Brasileiro Série A", "Campeonato Brasileiro Série B"}
        candidatos_dicas = [
            j for j in dados["jogos"]
            if j["status"] not in ("FINISHED", "AWARDED") and j["competicao"] not in _excluidas_dicas
        ]
        candidatos_dicas.sort(key=lambda j: j["favorito"]["prob"], reverse=True)
        n_total = len(dados["jogos"])
        n_dicas = 3 if n_total >= 10 else (2 if n_total > 5 else 1)
        daily_tips_ids = [
            {"casa": j["times"]["casa"], "visitante": j["times"]["visitante"], "data": j["data"]}
            for j in candidatos_dicas[:n_dicas]
        ]

    dados["daily_tips_ids"] = daily_tips_ids
    dados["daily_tips_date"] = hoje

    with open(caminho_saida, "w", encoding="utf-8") as arquivo_saida:
        json.dump(dados, arquivo_saida, ensure_ascii=False, indent=2)


def atualizar_historico(predicoes: List[PredicaoJogo], caminho: str = "history.json") -> None:
    """Acumula resultados dos jogos finalizados em history.json (últimos 2 dias)."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(caminho, "r", encoding="utf-8") as arquivo_leitura:
            historico = json.load(arquivo_leitura)
    except (FileNotFoundError, json.JSONDecodeError):
        historico = {"dias": []}

    finalizados = [
        p for p in predicoes
        if p.status == "FINISHED" and p.placar_casa is not None and p.placar_visitante is not None
    ]

    mercados_stats: Dict[str, Dict] = {}
    jogos_dia = []
    total_acertos = 0
    total_com_resultado = 0

    for predicao_finalizada in finalizados:
        palpites_pred = gerar_palpites(predicao_finalizada)
        com_resultado = [p for p in palpites_pred if p.resultado_verificador is not None]
        if not com_resultado:
            continue

        jogos_dia.append({
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

        for palpite in com_resultado:
            estatisticas = mercados_stats.setdefault(palpite.tipo, {"acertos": 0, "total": 0})
            estatisticas["total"] += 1
            if palpite.resultado_verificador == "ACERTO":
                estatisticas["acertos"] += 1
                total_acertos += 1
            total_com_resultado += 1

    for estatisticas in mercados_stats.values():
        estatisticas["taxa"] = round(estatisticas["acertos"] / estatisticas["total"], 3) if estatisticas["total"] else 0.0

    entrada = {
        "data": hoje,
        "ultima_atualizacao": agora,
        "finalizados": len(finalizados),
        "taxa_geral": round(total_acertos / total_com_resultado, 3) if total_com_resultado else 0.0,
        "total_acertos": total_acertos,
        "total_palpites": total_com_resultado,
        "mercados": mercados_stats,
        "jogos": jogos_dia,
    }

    dias = historico.get("dias", [])
    idx = next((i for i, d in enumerate(dias) if d["data"] == hoje), None)
    if idx is not None:
        dias[idx] = entrada
    else:
        dias.insert(0, entrada)

    historico["dias"] = dias[:2]

    with open(caminho, "w", encoding="utf-8") as arquivo_escrita:
        json.dump(historico, arquivo_escrita, ensure_ascii=False, indent=2)

    if total_com_resultado:
        print(f"📈 Histórico: {total_acertos}/{total_com_resultado} acertos hoje ({entrada['taxa_geral']*100:.0f}%) → {caminho}")
    else:
        print(f"📈 Histórico atualizado ({len(finalizados)} finalizado(s), sem resultado verificável ainda) → {caminho}")


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
            extra = ""
            if p.odd_decimal is not None and p.ev is not None:
                sinal_valor = "💰" if p.valor_esperado_positivo else ""
                extra = f" | odd {p.odd_decimal:.2f} | EV {p.ev*100:.1f}% {sinal_valor}"
            print(f"     {icon_conf} [{p.tipo}] {p.opcao}: {p.probabilidade*100:.1f}% ({p.confianca}) - {p.justificativa}{extra}")
        
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
    print(f"⏳ Processando jogos... (~{len(jogos) * 12 // 60} min estimados)")
    for match in jogos:
        try:
            pred = prever_jogo(match)
            predicoes.append(pred)
            time.sleep(12)
        except Exception as e:
            print(f"⚠️  Erro ao processar jogo: {e}")

    predicoes = aplicar_odds_e_valor(predicoes)
    if not predicoes:
        print("ℹ️  Nenhum jogo com valor esperado positivo para exibir no momento.")
        exportar_predicoes_front([], "predictions.json")
        return

    predicoes.sort(key=lambda p: p.data_jogo)

    exibir_predicoes(predicoes)
    exportar_predicoes_front(predicoes, "predictions.json")
    atualizar_historico(predicoes, "history.json")
    print("💾 Arquivos gerados: predictions.json | history.json")


if __name__ == "__main__":
    main()
