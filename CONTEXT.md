# Predictor Bet — Contexto Completo do Projeto

## Stack
- **Backend**: Python 3.12, `predictor.py` (futebol) e `predictor_nba.py` (NBA) — rodam via GitHub Actions a cada 3 min
- **Frontend**: HTML + Vanilla JS (`app.js`) + CSS (`styles.css`) — SPA estática, sem framework
- **Dados**: `predictions.json`, `history.json`, `predictions_nba.json`, `history_nba.json` — gerados pelo Python, lidos pelo JS
- **APIs**: football-data.org (futebol), BallDontLie API (NBA), the-odds-api.com (odds H2H, opcional)
- **CI/CD**: `.github/workflows/update-predictions.yml` — cron `*/3 * * * *`, faz `git pull --rebase` antes do push para evitar conflitos non-fast-forward

## Modelo de Predição
- **Dixon-Coles/Poisson**: calcula λ (gols esperados) por time com ataque × def_adversária × média_liga × HOME_ADVANTAGE × forma × fadiga
- Clamp: força 0.3–3.0, λ 0.3–5.0
- Mercados gerados: 1X2 (vitória/empate), Over/Under com **linha dinâmica** (2.5, 3.5 etc.), BTTS (ambos marcam)
- Score composto: Forma recente 35% + Ataque 25% + Defesa 20% + Mando 10% + H2H 10%
- Fadiga back-to-back: ≤2 dias → 0.86, ≤4 dias → 0.93

## Modelo NBA (`predictor_nba.py`)
- Fonte: BallDontLie API (temporada atual, playoffs incluídos)
- Mercados: WINNER (vitória), Over/Under de pontos, Spread esperado
- Forma recente por time (últimos N jogos), quarters, probabilidades por simulação
- Logos dos times via ESPN CDN: `https://a.espncdn.com/i/teamlogos/nba/500/{abrev}.png`

## Competições Permitidas
Premier League, La Liga (Primera Division), Serie A, Bundesliga, Ligue 1, Championship,
Primeira Liga, Eredivisie, Brasileirão Série A/B, UEFA Champions League, Copa Libertadores

## Estrutura do `predictions.json`
```json
{
  "generated_at": "YYYY-MM-DD HH:MM:SS",
  "total_jogos": 41,
  "daily_tips_ids": [{"casa": "...", "visitante": "...", "data": "ISO", "tipo": "OVER_UNDER", "opcao": "OVER_3.5"}],
  "daily_tips_date": "YYYY-MM-DD",
  "recovery_tip": {"ativo": false},
  "recovery_tip_date": "YYYY-MM-DD",
  "jogos": [{ "competicao", "data", "status", "times", "probabilidades",
              "favorito", "gols_esperados", "mercados", "palpites", ... }],
  "acertos_hoje": { "acertos", "total", "taxa" }
}
```

## Estrutura do `predictions_nba.json`
```json
{
  "generated_at": "ISO",
  "analysis_date": "YYYY-MM-DD",
  "total_jogos": 2,
  "daily_tips_ids": [{"casa": "...", "visitante": "...", "data": "ISO", "tipo": "WINNER", "opcao": "1"}],
  "jogos": [{ "game_id", "competicao", "data", "status", "times": {"casa", "visitante", "abrev_casa", "abrev_visit"},
              "probabilidades", "favorito", "mercados", "palpites", "spread_esperado", "pts_esperados", "forma", ... }]
}

## Funcionalidades Principais

### Dicas do Dia (congeladas)
- `daily_tips_ids` é calculado **apenas no primeiro run do dia** e preservado nas atualizações seguintes
- Cada entrada inclui `tipo` e `opcao` para identificar o palpite específico (ex: `OVER_3.5`)
- `predictor.py` lê o JSON existente; se `daily_tips_date == hoje`, mantém `daily_tips_ids`
- `app.js` → `renderTipsSection` / `renderTipsSectionNba` usa `daily_tips_ids` para buscar os jogos em `data.jogos`
- Exclui Brasileirão A/B das dicas de futebol; mostra 1–3 dicas conforme total de jogos (>10→3, >5→2, else 1)

### Dica de Recuperação
- Regra atual: ativa **somente** quando a dica #1 (maior prioridade do dia) falha (`resultado_verificador === "ERRO"`)
- No backend, a recuperação é persistida em `recovery_tip` no `predictions.json` para manter estabilidade no restante do dia
- Seleção da recuperação: maior `probabilidade` entre palpites elegíveis fora das dicas fixas do dia; em empate, usa confiança como desempate
- Renderizada como card âmbar (`tip-card--recovery`) com label "↩ Recuperação"
- **Bug corrigido**: a recovery card é suprimida no frontend se **todas** as dicas do dia terminarem com ACERTO, mesmo que `recovery_tip.ativo` ainda esteja `true` no JSON (valor congelado do Python)

### Verificação de Resultados
- Após jogos finalizados, `resultado_verificador` = "ACERTO" ou "ERRO" em cada palpite
- Tip cards das dicas do dia mostram badge ✅ Acerto / ❌ Errou conforme resultado
- `history.json` acumula os últimos 2 dias de resultados com merge por jogo (não sobrescreve o dia e não perde partidas já registradas)

## Fluxo Atual (Resumo)
1. Busca jogos do dia na API (futebol e NBA).
2. Filtra por competições permitidas e dia local da aplicação.
3. Analisa os jogos e gera probabilidades/mercados/palpites com linha Over/Under dinâmica.
4. Aplica baseline pré-jogo para evitar drift após início da partida.
5. Congela `daily_tips_ids` no primeiro run do dia (inclui tipo/opcao do palpite).
6. Ativa `recovery_tip` apenas se a dica #1 falhar.
7. Atualiza `history.json` e `history_nba.json` em modo acumulativo (merge), preservando jogos já registrados no dia.

## Formatação de Palpites OVER_UNDER no Frontend
- O Python gera `opcao` no formato `"OVER_3.5"`, `"UNDER_2.5"` etc.
- `parseOuOpcao(opcao)` extrai `{ side, linha }` com regex
- `translateTipOption` converte para ex: *"Mais de 3,5 gols"* / *"Menos de 2,5 gols"*
- `buildGoalsProbabilityLabel` usa o palpite OVER_UNDER real do modelo (linha dinâmica) para o snapshot do card; fallback para `over_25`/`under_25` quando não há palpite
- `buildTipJustificationHuman` usa a linha real para gerar texto coerente (ex: "A linha de 3,5 gols...")

## Escudos / Logos dos Times
- **Futebol**: `escudo_casa` / `escudo_visitante` vêm do JSON (football-data.org), acessados via `getTeamCrests(match)`
- **NBA**: logos buscados dinamicamente via ESPN CDN: `https://a.espncdn.com/i/teamlogos/nba/500/{abrev_lowercase}.png`
- Renderizados via `buildMatchTitleHtml(casa, visitante, vsLabel, logoCasa, logoVisit)` — usado em dicas do dia e cards de jogos
- `onerror="this.style.display='none'"` para falhas silenciosas

## Variáveis de Ambiente
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

## Filtros do Frontend
- Por competição (select)
- Por confiança mínima: LOW / MEDIUM / HIGH (chips)
- Cards expandem/colapsam ao clicar (is-collapsed)
- Abas de modalidade: Futebol / NBA

## Arquivos Chave
| Arquivo | Papel |
|---|---|
| `predictor.py` | Coleta dados futebol, calcula previsões, gera JSONs |
| `predictor_nba.py` | Coleta dados NBA via BallDontLie, gera JSONs |
| `app.js` | Renderiza UI, filtra, gerencia estado |
| `styles.css` | Dark/light theme, componentes |
| `index.html` | Shell HTML, templates |
| `predictions.json` | Saída futebol (gerado automaticamente) |
| `history.json` | Histórico futebol — últimos 2 dias (gerado automaticamente) |
| `predictions_nba.json` | Saída NBA (gerado automaticamente) |
| `history_nba.json` | Histórico NBA — últimos dias (gerado automaticamente) |
| `.github/workflows/update-predictions.yml` | Cron GitHub Actions (a cada 3 min) |
