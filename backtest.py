"""
Backtesting do modelo Predictor_bet
====================================
Busca jogos finalizados dos últimos N dias, roda o modelo (com os dados
históricos atuais — leve look-ahead bias para partidas muito recentes) e
compara previsões contra resultados reais.

Saída: acurácia e Brier score por mercado + por tier de confiança +
       tabela de calibração por faixa de probabilidade, com sugestão de
       ajuste dos thresholds de edge.

Uso:
    python backtest.py              # últimos 14 dias
    python backtest.py --days 30    # últimos 30 dias
"""

import argparse
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import log2
from typing import Dict, List, Optional

import requests

from predictor import (
    API_BASE,
    COMPETICOES_PERMITIDAS,
    HEADERS,
    gerar_palpites,
    prever_jogo,
)

# Thresholds atuais (referência para o relatório final)
_THRESHOLDS = {
    "WINNER":     {"HIGH": 0.25, "MEDIUM": 0.12},
    "OVER_UNDER": {"HIGH": 0.15, "MEDIUM": 0.07},
    "BTTS":       {"HIGH": 0.15, "MEDIUM": 0.07},
}


def buscar_jogos_finalizados(days_back: int) -> List[Dict]:
    hoje = datetime.now(timezone.utc)
    data_inicio = (hoje - timedelta(days=days_back)).strftime("%Y-%m-%d")
    data_fim = (hoje - timedelta(days=1)).strftime("%Y-%m-%d")

    url = f"{API_BASE}/matches/"
    params = {"status": "FINISHED", "dateFrom": data_inicio, "dateTo": data_fim}

    print(f"📅 Buscando jogos finalizados de {data_inicio} a {data_fim}...")
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        print(f"❌ Erro ao buscar jogos: {exc}")
        return []

    todos = resp.json().get("matches", [])
    filtrados = [m for m in todos if m.get("competition", {}).get("name", "") in COMPETICOES_PERMITIDAS]
    print(f"✅ {len(filtrados)} jogo(s) finalizados encontrados.\n")
    return filtrados


class _Bucket:
    """Agrupa predições por faixa de probabilidade e mede acurácia real."""

    def __init__(self, n: int = 10):
        self.n = n
        self.probs: List[List[float]] = [[] for _ in range(n)]
        self.hits: List[List[bool]] = [[] for _ in range(n)]

    def add(self, prob: float, hit: bool) -> None:
        idx = min(int(prob * self.n), self.n - 1)
        self.probs[idx].append(prob)
        self.hits[idx].append(hit)

    def rows(self) -> List[Dict]:
        out = []
        for i in range(self.n):
            if not self.probs[i]:
                continue
            p_med = sum(self.probs[i]) / len(self.probs[i])
            acc = sum(self.hits[i]) / len(self.hits[i])
            out.append({
                "faixa": f"{i*10}–{(i+1)*10}%",
                "p_medio": p_med,
                "acuracia": acc,
                "n": len(self.probs[i]),
                "erro": acc - p_med,
            })
        return out


def _brier(prob: float, hit: bool) -> float:
    return (prob - (1.0 if hit else 0.0)) ** 2


def _winner_hit(opcao: str, hg: int, ag: int) -> bool:
    if opcao == "1":
        return hg > ag
    if opcao == "X":
        return hg == ag
    return hg < ag


def _ou_hit(opcao: str, hg: int, ag: int) -> bool:
    total = hg + ag
    return (opcao == "OVER" and total > 2.5) or (opcao == "UNDER" and total <= 2.5)


def _btts_hit(opcao: str, hg: int, ag: int) -> bool:
    ambos = hg > 0 and ag > 0
    return (opcao == "YES" and ambos) or (opcao == "NO" and not ambos)


def backtest(days_back: int = 14) -> None:
    jogos = buscar_jogos_finalizados(days_back)
    if not jogos:
        print("Nenhum jogo para backtest.")
        return

    mercados_alvo = ("WINNER", "OVER_UNDER", "BTTS")
    stats: Dict[str, Dict] = {
        m: {
            "acertos": 0,
            "total": 0,
            "brier_sum": 0.0,
            "tier": defaultdict(lambda: {"acertos": 0, "total": 0}),
            "bucket": _Bucket(),
        }
        for m in mercados_alvo
    }

    print(f"⏳ Processando {len(jogos)} jogo(s) (~12 s por jogo)...\n")
    for i, match in enumerate(jogos, 1):
        score = match.get("score", {}).get("fullTime", {})
        hg: Optional[int] = score.get("home")
        ag: Optional[int] = score.get("away")
        if hg is None or ag is None:
            continue

        home = match.get("homeTeam", {}).get("shortName") or match.get("homeTeam", {}).get("name", "?")
        away = match.get("awayTeam", {}).get("shortName") or match.get("awayTeam", {}).get("name", "?")
        print(f"  [{i:>3}/{len(jogos)}] {home} vs {away}  →  {hg}-{ag}")

        try:
            pred = prever_jogo(match)
        except Exception as exc:
            print(f"    ⚠️  Erro ao prever: {exc}")
            time.sleep(12)
            continue

        for p in gerar_palpites(pred):
            if p.tipo not in stats:
                continue

            if p.tipo == "WINNER":
                hit = _winner_hit(p.opcao, hg, ag)
            elif p.tipo == "OVER_UNDER":
                hit = _ou_hit(p.opcao, hg, ag)
            elif p.tipo == "BTTS":
                hit = _btts_hit(p.opcao, hg, ag)
            else:
                continue

            s = stats[p.tipo]
            s["total"] += 1
            s["acertos"] += int(hit)
            s["brier_sum"] += _brier(p.probabilidade, hit)
            s["tier"][p.confianca]["total"] += 1
            s["tier"][p.confianca]["acertos"] += int(hit)
            s["bucket"].add(p.probabilidade, hit)

        time.sleep(12)

    # ── Relatório ────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  RELATÓRIO DE CALIBRAÇÃO")
    print(f"  Período: últimos {days_back} dias  |  Jogos processados: {len(jogos)}")
    print("=" * 72)

    for mercado in mercados_alvo:
        s = stats[mercado]
        if s["total"] == 0:
            print(f"\n{mercado}: sem dados suficientes.")
            continue

        acc = s["acertos"] / s["total"]
        brier = s["brier_sum"] / s["total"]
        thr = _THRESHOLDS[mercado]

        print(f"\n📊  {mercado}")
        print(f"    Acurácia global : {acc*100:.1f}%  ({s['acertos']}/{s['total']})")
        print(f"    Brier médio     : {brier:.4f}  (0=perfeito, 0.25=aleatório)")
        print(f"    Thresholds atuais: HIGH>{thr['HIGH']*100:.0f}pp  MEDIUM>{thr['MEDIUM']*100:.0f}pp")

        print("    Por confiança:")
        for tier in ("HIGH", "MEDIUM", "LOW"):
            t = s["tier"].get(tier)
            if not t or t["total"] == 0:
                continue
            t_acc = t["acertos"] / t["total"]
            flag = ""
            if tier == "HIGH" and t_acc < acc - 0.05:
                flag = "  ← threshold de HIGH pode estar baixo"
            elif tier == "LOW" and t_acc > acc + 0.05:
                flag = "  ← threshold de LOW pode estar alto"
            print(f"      {tier:6}: {t_acc*100:.1f}%  ({t['acertos']}/{t['total']}){flag}")

        print("    Calibração por faixa:")
        for row in s["bucket"].rows():
            sinal = "↑ superestimado" if row["erro"] < -0.04 else ("↓ subestimado" if row["erro"] > 0.04 else "≈ ok")
            print(
                f"      {row['faixa']:10}  previsto {row['p_medio']*100:4.0f}%  "
                f"real {row['acuracia']*100:4.0f}%  {sinal}  (n={row['n']})"
            )

    print("\n" + "=" * 72)
    print("  NOTA: look-ahead bias leve — dados históricos usados incluem")
    print("  as próprias partidas testadas. Use como estimativa grosseira.")
    print("  Para backtesting rigoroso, snapshots de dados seriam necessários.")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest do modelo Predictor_bet")
    parser.add_argument("--days", type=int, default=14, help="Dias para buscar (padrão: 14)")
    args = parser.parse_args()
    backtest(args.days)
