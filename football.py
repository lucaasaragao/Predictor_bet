"""
Cliente simples para football-data.org
======================================
Busca e organiza jogos por competição.
"""

import requests
import os
from datetime import datetime
from typing import Optional

# Configuração
API_URL = "https://api.football-data.org/v4/matches/"
TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "")

if not TOKEN:
    raise SystemExit(
        "Defina a variavel de ambiente FOOTBALL_DATA_TOKEN antes de executar. "
        "Exemplo PowerShell: $env:FOOTBALL_DATA_TOKEN='seu_token'"
    )

HEADERS = {
    "X-Auth-Token": TOKEN
}

HISTORICO_CACHE = {}


def buscar_jogos(data_inicio: Optional[str] = None, data_fim: Optional[str] = None) -> dict:
    """Busca jogos da API football-data.org"""
    
    params = {}
    if data_inicio:
        params["dateFrom"] = data_inicio
    if data_fim:
        params["dateTo"] = data_fim
    
    print(f"🌐 Consultando API...")
    response = requests.get(API_URL, headers=HEADERS, params=params, timeout=30)
    
    if response.status_code != 200:
        print(f"❌ Erro {response.status_code}: {response.text}")
        return {}
    
    return response.json()


def organizar_jogos(dados: dict) -> dict:
    """Organiza os jogos por campeonato"""
    
    jogos_por_campeonato = {}
    
    for match in dados.get("matches", []):
        competicao = match.get("competition", {}).get("name", "Desconhecido")
        
        if competicao not in jogos_por_campeonato:
            jogos_por_campeonato[competicao] = []
        
        home_team = match.get("homeTeam", {})
        away_team = match.get("awayTeam", {})
        
        jogo = {
            "id": match.get("id"),
            "horario": _formatar_hora(match.get("utcDate", "")),
            "time_casa": home_team.get("shortName") or home_team.get("name", ""),
            "time_casa_id": home_team.get("id"),
            "time_visitante": away_team.get("shortName") or away_team.get("name", ""),
            "time_visitante_id": away_team.get("id"),
            "placar": _formatar_placar(match.get("score", {})),
            "status": match.get("status", ""),
            "historico_casa": None,
            "historico_visitante": None,
        }
        
        jogos_por_campeonato[competicao].append(jogo)
    
    return jogos_por_campeonato


def _formatar_hora(utc_date: str) -> str:
    """Converte UTC para hora (HH:MM)"""
    if not utc_date:
        return ""
    
    try:
        dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except ValueError:
        return utc_date


def _formatar_placar(score: dict) -> str:
    """Formata o placar como 'X x Y' ou vazio se não há placar"""
    full_time = score.get("fullTime", {})
    home = full_time.get("home")
    away = full_time.get("away")
    
    if home is not None and away is not None:
        return f"{home} x {away}"
    
    return ""


def buscar_historico_time(team_id: int, limit: int = 5) -> list:
    """Busca os últimos jogos de um time"""
    cache_key = (team_id, limit)
    if cache_key in HISTORICO_CACHE:
        return HISTORICO_CACHE[cache_key]
    
    url = f"https://api.football-data.org/v4/teams/{team_id}/matches"
    params = {
        "limit": limit,
        "status": "FINISHED"
    }
    
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if response.status_code != 200:
            return []
        
        dados = response.json()
        jogos = []
        
        matches = sorted(
            dados.get("matches", []),
            key=lambda item: item.get("utcDate", ""),
            reverse=True,
        )

        for match in matches:
            jogo_hist = {
                "data": _formatar_data(match.get("utcDate", "")),
                "time1": match.get("homeTeam", {}).get("shortName") or match.get("homeTeam", {}).get("name", ""),
                "time2": match.get("awayTeam", {}).get("shortName") or match.get("awayTeam", {}).get("name", ""),
                "placar": _formatar_placar(match.get("score", {})),
                "resultado": _determinar_resultado(match, team_id)
            }
            jogos.append(jogo_hist)

        HISTORICO_CACHE[cache_key] = jogos[:limit]
        return HISTORICO_CACHE[cache_key]
    
    except Exception as e:
        print(f"⚠️  Erro ao buscar histórico do time {team_id}: {e}")
        return []


def _determinar_resultado(match: dict, team_id: int) -> str:
    """Determina se foi vitória, derrota ou empate"""
    
    full_time = match.get("score", {}).get("fullTime", {})
    home = full_time.get("home")
    away = full_time.get("away")
    home_team_id = match.get("homeTeam", {}).get("id")
    
    if home is None or away is None:
        return "?"
    
    if team_id == home_team_id:
        if home > away:
            return "V"  # Vitória
        elif home < away:
            return "D"  # Derrota
        else:
            return "E"  # Empate
    else:
        if away > home:
            return "V"
        elif away < home:
            return "D"
        else:
            return "E"


def _formatar_data(utc_date: str) -> str:
    """Converte UTC para data e hora no formato DD/MM HH:MM"""
    if not utc_date:
        return ""

    try:
        dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        return dt.strftime("%d/%m %H:%M")
    except ValueError:
        return utc_date


def exibir_jogos(jogos_por_campeonato: dict) -> None:
    """Exibe os jogos organizados no terminal com histórico dos times"""
    
    if not jogos_por_campeonato:
        print("❌ Nenhum jogo encontrado.")
        return
    
    print("\n" + "=" * 90)
    print("  ⚽  JOGOS DE FUTEBOL COM HISTÓRICO")
    print("=" * 90 + "\n")
    
    for campeonato, jogos in sorted(jogos_por_campeonato.items()):
        print(f"\n🏆  {campeonato}")
        print("  " + "-" * 86)
        
        for idx, jogo in enumerate(jogos):
            horario = jogo["horario"] or "TBD"
            placar = jogo["placar"]
            
            # Exibir o jogo principal
            if placar:
                linha = f"  ✅  {horario}  {jogo['time_casa']:<18} {placar:>5} {jogo['time_visitante']:<18}"
            else:
                linha = f"  🕐  {horario}  {jogo['time_casa']:<18} vs {jogo['time_visitante']:<18}"
            
            print(linha)
            
            # Buscar e exibir histórico
            if jogo['time_casa_id'] and jogo['time_visitante_id']:
                print(f"      📋 Últimos jogos:")
                
                # Histórico do time da casa
                hist_casa = buscar_historico_time(jogo['time_casa_id'], limit=5)
                if hist_casa:
                    print(f"         {jogo['time_casa']}:", end="")
                    for h in hist_casa:
                        icone = "✅" if h['resultado'] == "V" else "❌" if h['resultado'] == "D" else "⚪"
                        print(f" {icone}", end="")
                    print()
                
                # Histórico do time visitante
                hist_visitante = buscar_historico_time(jogo['time_visitante_id'], limit=5)
                if hist_visitante:
                    print(f"         {jogo['time_visitante']}:", end="")
                    for h in hist_visitante:
                        icone = "✅" if h['resultado'] == "V" else "❌" if h['resultado'] == "D" else "⚪"
                        print(f" {icone}", end="")
                    print()
            
            if idx < len(jogos) - 1:
                print()
    
    print("\n" + "=" * 90 + "\n")


def main():
    """Fluxo principal"""
    
    # Buscar dados
    dados = buscar_jogos()
    
    if not dados:
        print("❌ Não foi possível buscar os dados.")
        return
    
    # Informações gerais
    filters = dados.get("filters", {})
    result_set = dados.get("resultSet", {})
    
    print(f"\n📊  Informações da consulta:")
    print(f"    Data: {filters.get('dateFrom')} a {filters.get('dateTo')}")
    print(f"    Total de jogos: {result_set.get('count', 0)}")
    print(f"    Competições: {result_set.get('competitions', 'N/A')}")
    
    # Organizar e exibir
    jogos_organizados = organizar_jogos(dados)
    exibir_jogos(jogos_organizados)


if __name__ == "__main__":
    main()
