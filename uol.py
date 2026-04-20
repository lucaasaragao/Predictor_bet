"""
Cliente de partidas via football-data.org
========================================
Consulta jogos de futebol por data, com opção de filtrar por competição.

Configuração:
    PowerShell:
        $env:FOOTBALL_DATA_TOKEN="seu_token"

Uso:
    python uol.py                               # jogos do dia
    python uol.py --data 2026-04-19            # data específica
    python uol.py --competicao CL              # apenas Champions League
    python uol.py --data 2026-04-19 --json     # salva em jogos_2026-04-19.json
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

try:
    import requests
except ImportError:
    print("❌  A biblioteca requests não está instalada.")
    print("    Execute: pip install requests")
    sys.exit(1)


API_BASE_URL = "https://api.football-data.org/v4"
TOKEN_ENV_VAR = "FOOTBALL_DATA_TOKEN"


@dataclass
class Jogo:
    campeonato: str
    time_casa: str
    time_visitante: str
    placar_casa: Optional[str]
    placar_visitante: Optional[str]
    horario: str
    status: str
    data: str


@dataclass
class Resultado:
    data_consulta: str
    data_jogos: str
    total_jogos: int
    campeonatos: int
    jogos: list = field(default_factory=list)


def consultar_jogos(data: str, competicao: Optional[str] = None) -> Resultado:
    token = os.getenv(TOKEN_ENV_VAR)
    if not token:
        print(f"❌  Variável de ambiente {TOKEN_ENV_VAR} não encontrada.")
        print("    No PowerShell, execute:")
        print(f"    $env:{TOKEN_ENV_VAR}=\"seu_token\"")
        sys.exit(1)

    endpoint = "/matches/"
    if competicao:
        endpoint = f"/competitions/{competicao}/matches"

    params = {
        "dateFrom": data,
        "dateTo": data,
    }
    payload, headers = _fazer_requisicao(endpoint, token, params)

    matches = sorted(
        payload.get("matches", []),
        key=lambda partida: (
            partida.get("competition", {}).get("name", ""),
            partida.get("utcDate", ""),
        ),
    )
    jogos = [_converter_partida(partida, data) for partida in matches]
    campeonatos_unicos = len({jogo.campeonato for jogo in jogos})
    filtros = payload.get("filters", {})
    result_set = payload.get("resultSet", {})
    data_jogos = filtros.get("dateFrom", data)
    total_jogos = result_set.get("count", len(jogos))

    _exibir_limites(headers)

    return Resultado(
        data_consulta=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data_jogos=data_jogos,
        total_jogos=total_jogos,
        campeonatos=campeonatos_unicos,
        jogos=[asdict(jogo) for jogo in jogos],
    )


def _fazer_requisicao(endpoint: str, token: str, params: dict) -> tuple[dict, dict]:
    url = f"{API_BASE_URL}{endpoint}"
    headers = {
        "X-Auth-Token": token,
        "User-Agent": "LucasFootballClient/1.0",
    }

    for tentativa in range(2):
        try:
            response = requests.request(
                "GET",
                url,
                headers=headers,
                params=params,
                data={},
                timeout=30,
            )
            if response.status_code == 429 and tentativa == 0:
                retry_after = _obter_retry_after(response.headers)
                print(f"⚠️  Rate limit atingido. Tentando novamente em {retry_after}s...")
                time.sleep(retry_after)
                continue
            if response.status_code >= 400:
                _encerrar_com_erro_http(response.status_code, response.text)
            return response.json(), dict(response.headers.items())
        except requests.RequestException as exc:
            print(f"❌  Falha de conexão com a API: {exc}")
            sys.exit(1)

    print("❌  Não foi possível concluir a requisição.")
    sys.exit(1)


def _obter_retry_after(headers) -> int:
    raw_value = headers.get("Retry-After", "60")
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return 60


def _encerrar_com_erro_http(status_code: int, body: str) -> None:
    mensagem = _extrair_mensagem_erro(body)

    if status_code == 401:
        print("❌  401 Unauthorized: token ausente, inválido ou enviado de forma incorreta.")
    elif status_code == 403:
        print("❌  403 Forbidden: seu plano não tem acesso a este recurso.")
    elif status_code == 429:
        print("❌  429 Too Many Requests: o rate limit da API foi atingido.")
    else:
        print(f"❌  Erro HTTP {status_code} ao consultar a API.")

    if mensagem:
        print(f"    Detalhe: {mensagem}")

    sys.exit(1)


def _extrair_mensagem_erro(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()

    if isinstance(payload, dict):
        for chave in ["message", "error", "details"]:
            valor = payload.get(chave)
            if valor:
                return str(valor)

    return ""


def _converter_partida(partida: dict, data: str) -> Jogo:
    score = partida.get("score", {})
    full_time = score.get("fullTime", {})
    home_team = partida.get("homeTeam", {})
    away_team = partida.get("awayTeam", {})
    competition = partida.get("competition", {})

    return Jogo(
        campeonato=competition.get("name", "Desconhecido"),
        time_casa=home_team.get("shortName") or home_team.get("name", ""),
        time_visitante=away_team.get("shortName") or away_team.get("name", ""),
        placar_casa=_normalizar_placar(full_time.get("home")),
        placar_visitante=_normalizar_placar(full_time.get("away")),
        horario=_formatar_horario(partida.get("utcDate", "")),
        status=_normalizar_status_api(partida.get("status", "")),
        data=data,
    )


def _normalizar_placar(valor: Optional[int]) -> Optional[str]:
    if valor is None:
        return None
    return str(valor)


def _formatar_horario(utc_date: str) -> str:
    if not utc_date:
        return ""

    try:
        horario = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
    except ValueError:
        return utc_date

    return horario.strftime("%H:%M")


def _normalizar_status_api(raw: str) -> str:
    status = raw.upper()
    if status in {"LIVE", "IN_PLAY", "PAUSED"}:
        return "ao_vivo"
    if status == "FINISHED":
        return "encerrado"
    return "agendado"


def _exibir_limites(headers: dict) -> None:
    campos = [
        "X-Requests-Available",
        "X-RequestCounter-Reset",
        "Retry-After",
    ]
    encontrados = [(campo, headers.get(campo)) for campo in campos if headers.get(campo)]
    if not encontrados:
        return

    print("📊  Headers de limite da API:")
    for campo, valor in encontrados:
        print(f"    {campo}: {valor}")


STATUS_ICON = {
    "ao_vivo": "🔴",
    "encerrado": "✅",
    "agendado": "🕐",
}


def imprimir(resultado: Resultado) -> None:
    print(f"\n{'=' * 60}")
    print(f"  📅  Jogos de {resultado.data_jogos}")
    print(f"  🔍  Consultado em: {resultado.data_consulta}")
    print(f"  ⚽  Total: {resultado.total_jogos} jogos | {resultado.campeonatos} campeonatos")
    print(f"{'=' * 60}\n")

    if not resultado.jogos:
        print("Nenhum jogo encontrado para os filtros informados.\n")
        print(f"{'=' * 60}\n")
        return

    campeonato_atual = None
    for jogo in resultado.jogos:
        if jogo["campeonato"] != campeonato_atual:
            campeonato_atual = jogo["campeonato"]
            print(f"\n🏆  {campeonato_atual}")
            print(f"  {'-' * 50}")

        icone = STATUS_ICON.get(jogo["status"], "❓")
        detalhe = ""
        if jogo["placar_casa"] is not None and jogo["placar_visitante"] is not None:
            detalhe = f"  {jogo['placar_casa']} x {jogo['placar_visitante']}"
        elif jogo["horario"]:
            detalhe = f"  {jogo['horario']}"

        print(
            f"  {icone}  {jogo['horario']:>5}  "
            f"{jogo['time_casa']:<22} vs  {jogo['time_visitante']:<22}"
            f"{detalhe}"
        )

    print(f"\n{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cliente de jogos via football-data.org")
    parser.add_argument(
        "--data",
        "-d",
        default=datetime.today().strftime("%Y-%m-%d"),
        help="Data no formato YYYY-MM-DD (padrão: hoje)",
    )
    parser.add_argument(
        "--competicao",
        "-c",
        help="Código da competição, ex: CL, PL, SA, DED",
    )
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Salvar resultado em jogos_<data>.json",
    )
    args = parser.parse_args()

    try:
        datetime.strptime(args.data, "%Y-%m-%d")
    except ValueError:
        print("❌  Data inválida. Use o formato YYYY-MM-DD  (ex: 2026-04-19)")
        sys.exit(1)

    resultado = consultar_jogos(data=args.data, competicao=args.competicao)
    imprimir(resultado)

    if args.json:
        arquivo = f"jogos_{args.data}.json"
        with open(arquivo, "w", encoding="utf-8") as file_handle:
            json.dump(asdict(resultado), file_handle, ensure_ascii=False, indent=2)
        print(f"💾  Salvo em: {arquivo}\n")


if __name__ == "__main__":
    main()