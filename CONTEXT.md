# Predictor Bet — Contexto Completo do Projeto

## Stack
- **Backend**: Python 3.12, `predictor.py` — roda via GitHub Actions a cada 20 min
- **Frontend**: HTML + Vanilla JS (`app.js`) + CSS (`styles.css`) — SPA estática, sem framework
- **Dados**: `predictions.json` e `history.json` — gerados pelo Python, lidos pelo JS
- **APIs**: football-data.org (partidas/histórico), the-odds-api.com (odds H2H, opcional)
- **CI/CD**: `.github/workflows/update-predictions.yml` — cron `*/20 * * * *`, comita os JSONs

## Modelo de Predição
- **Dixon-Coles/Poisson**: calcula λ (gols esperados) por time com ataque × def_adversária × média_liga × HOME_ADVANTAGE × forma × fadiga
- Clamp: força 0.3–3.0, λ 0.3–5.0
- Mercados gerados: 1X2 (vitória/empate), Over/Under 2.5, BTTS (ambos marcam)
- Score composto: Forma recente 35% + Ataque 25% + Defesa 20% + Mando 10% + H2H 10%
- Fadiga back-to-back: ≤2 dias → 0.86, ≤4 dias → 0.93

## Competições Permitidas
Premier League, La Liga (Primera Division), Serie A, Bundesliga, Ligue 1, Championship,
Primeira Liga, Eredivisie, Brasileirão Série A/B, UEFA Champions League, Copa Libertadores

## Estrutura do `predictions.json`
```json
{
  "generated_at": "YYYY-MM-DD HH:MM:SS",
  "total_jogos": 41,
  "daily_tips_ids": [{"casa": "...", "visitante": "...", "data": "ISO"}],
  "daily_tips_date": "YYYY-MM-DD",
  "recovery_tip": {"ativo": false},
  "recovery_tip_date": "YYYY-MM-DD",
  "jogos": [{ "competicao", "data", "status", "times", "probabilidades",
              "favorito", "gols_esperados", "mercados", "palpites", ... }],
  "acertos_hoje": { "acertos", "total", "taxa" }
}
```

## Funcionalidades Principais

### Dicas do Dia (congeladas)
- `daily_tips_ids` é calculado **apenas no primeiro run do dia** e preservado nas atualizações seguintes
- `predictor.py` lê o JSON existente; se `daily_tips_date == hoje`, mantém `daily_tips_ids`
- `app.js` → `renderTipsSection` usa `daily_tips_ids` para buscar os jogos em `data.jogos`
- Exclui Brasileirão A/B das dicas; mostra 1–3 dicas conforme total de jogos (>10→3, >5→2, else 1)

### Dica de Recuperação
- Regra atual: ativa **somente** quando a dica #1 (maior prioridade do dia) falha (`resultado_verificador === "ERRO"`)
- No backend, a recuperação é persistida em `recovery_tip` no `predictions.json` para manter estabilidade no restante do dia
- Seleção da recuperação: maior `probabilidade` entre palpites elegíveis fora das dicas fixas do dia; em empate, usa confiança como desempate
- Renderizada como card âmbar (`tip-card--recovery`) com label "↩ Recuperação"

### Verificação de Resultados
- Após jogos finalizados, `resultado_verificador` = "ACERTO" ou "ERRO" em cada palpite
- Tip cards das dicas do dia mostram badge ✅ Acerto / ❌ Errou conforme resultado
- `history.json` acumula os últimos 2 dias de resultados com merge por jogo (não sobrescreve o dia e não perde partidas já registradas)

## Fluxo Atual (Resumo)
1. Busca jogos do dia na API.
2. Filtra por competições permitidas e dia local da aplicação.
3. Analisa os jogos e gera probabilidades/mercados/palpites.
4. Aplica baseline pré-jogo para evitar drift após início da partida.
5. Congela `daily_tips_ids` no primeiro run do dia.
6. Ativa `recovery_tip` apenas se a dica #1 falhar.
7. Atualiza `history.json` em modo acumulativo (merge), preservando jogos já registrados no dia.

## Filtros do Frontend
- Por competição (select)
- Por confiança mínima: LOW / MEDIUM / HIGH (chips)
- Cards expandem/colapsam ao clicar (is-collapsed)

## Variáveis de Ambiente
| Variável | Obrigatória | Descrição |
|---|---|---|
| `FOOTBALL_DATA_TOKEN` | Sim | Token football-data.org |
| `ODDS_API_KEY` | Não | Chave the-odds-api.com |
| `ODDS_REGIONS` | Não | Regiões odds (default: eu) |
| `ODDS_MIN_EV` | Não | EV mínimo para filtrar valor (default: 0.03) |
| `ODDS_MIN_EDGE_GATE` | Não | Edge mínimo para buscar odds (default: 0.10) |
| `ODDS_ONLY_VALUE_GAMES` | Não | Mostrar só jogos com EV+ (default: true) |

## Arquivos Chave
| Arquivo | Papel |
|---|---|
| `predictor.py` | Coleta dados, calcula previsões, gera JSONs |
| `app.js` | Renderiza UI, filtra, gerencia estado |
| `styles.css` | Dark/light theme, componentes |
| `index.html` | Shell HTML, templates |
| `predictions.json` | Saída principal (gerado automaticamente) |
| `history.json` | Histórico últimos 2 dias (gerado automaticamente) |
| `.github/workflows/update-predictions.yml` | Cron GitHub Actions |
