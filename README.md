# Predictor Bet - Radar de Palpites de Futebol e NBA

Projeto de previsao de partidas de futebol e NBA com pipeline completo:

1. coleta dados da football-data.org (futebol) e BallDontLie API (NBA)
2. calcula probabilidades e mercados com modelo Poisson/Dixon-Coles simplificado
3. integra odds da The Odds API para analise de valor esperado (EV)
4. exporta predictions.json, history.json, predictions_nba.json e history_nba.json
5. renderiza uma SPA estatica com filtros, cards, dicas do dia e painel historico para futebol e NBA

## Visao Geral

O backend em Python gera os arquivos JSON e o frontend em HTML/CSS/JS consome esses dados sem servidor de aplicacao.

Componentes principais:

1. predictor.py: motor de predicao de futebol, odds, exportacao e historico
2. predictor_nba.py: motor de predicao NBA via BallDontLie API
3. backtest.py: avaliacao offline com calibracao e acuracia
4. app.js: renderizacao dos cards, filtros e regras de UI
5. index.html e styles.css: estrutura visual da pagina
6. predictions.json / predictions_nba.json: snapshots de previsoes por modalidade
7. history.json / history_nba.json: historico de desempenho dos ultimos dias
8. .github/workflows/update-predictions.yml: automacao para atualizar JSONs no GitHub

## Funcionalidades Implementadas

1. Predicao por jogo (futebol):
- probabilidades 1X2 (casa, empate, visitante)
- gols esperados (xG simplificado)
- Over/Under com linha dinamica (2.5, 3.5 etc.)
- BTTS (ambos marcam)

2. Predicao por jogo (NBA):
- probabilidade de vitoria (WINNER)
- Over/Under de pontos
- Spread esperado
- Forma recente e probabilidades por time
- Logos dos times via ESPN CDN

3. Palpites por mercado (futebol):
- WINNER
- OVER_UNDER (linha dinamica)
- BTTS
- EMPATE (quando elegivel)

3. Integracao de odds:
- consulta principal via endpoint unico upcoming para economizar cota
- fallback por liga/sport_key quando necessario
- matching por normalizacao/alias de nomes de times

4. Analise de valor esperado (EV):
- EV bruto por odd
- EV justo com de-vig para mercado 1X2 (remove overround)
- destaque de valor esperado positivo

5. Historico e avaliacao:
- acerto/erro por palpite em jogos finalizados
- taxa de acerto geral e por mercado
- metricas probabilisticas: Brier e Log Loss (1X2, Over/Under, BTTS)

6. Protecao anti-vies de jogo em andamento:
- baseline pre-jogo congelado
- evita troca de favorito depois do inicio da partida
- jogos iniciados/finalizados sem snapshot pre-jogo sao ignorados na calibracao

7. Frontend:
- abas de modalidade: Futebol e NBA
- filtros por competicao e confianca minima
- cards colapsaveis com escudos/logos dos times
- tema claro/escuro
- dicas do dia congeladas com logos
- dica de recuperacao quando a dica #1 falha (suprimida automaticamente se o dia fechar com acerto)
- painel admin com historico (via #admin ou triple-click no rodape)

8. Historico acumulativo por dia:
- nao sobrescreve o dia inteiro a cada execucao
- faz merge por jogo finalizado e preserva partidas ja registradas (ex.: PSG/Bayer)

## Modelo de Predicao

Base do modelo:

1. estimativa de forca ofensiva/defensiva por time
2. normalizacao por media de gols da liga
3. ajuste por mando de campo
4. ajuste de forma recente
5. ajuste de fadiga (back-to-back)
6. clamp de forcas e lambdas para evitar extremos

Melhoria recente aplicada:

1. shrinkage estatistico para amostra curta
- combina media do time com media da liga quando ha poucos jogos
- reduz volatilidade e falsos sinais

## Estrutura dos Dados

### predictions.json

Campos principais:

1. generated_at
2. total_jogos
3. odds_debug_visual
4. odds_only_value_games
5. odds_min_ev
6. jogos[] com:
- competicao, data, status
- times (casa, visitante)
- probabilidades 1X2
- favorito
- gols_esperados
- mercados
- scores
- leitura_rapida
- tendencia
- alertas
- odds_debug
- odds_integradas
- odds_valor_alto
- historico (casa/visitante)
- palpites (incluindo EV, EV bruto, valor_esperado_positivo e resultado_verificador quando finalizado)

### history.json

Campos principais por dia:

1. data
2. ultima_atualizacao
3. finalizados
4. taxa_geral
5. total_acertos
6. total_palpites
7. mercados (acertos/total/taxa)
8. metricas_probabilisticas (Brier e Log Loss por mercado)
9. jogos

Observacao de comportamento:

1. o dia atual e atualizado de forma acumulativa (merge por jogo), evitando perda de jogos ja registrados em execucoes subsequentes

## Requisitos

1. Python 3.12+
2. requests
3. token da football-data.org

## Configuracao de Ambiente

Use .env.example como base para seu .env local.

Variaveis disponiveis:

1. FOOTBALL_DATA_TOKEN (obrigatoria)
2. ODDS_API_KEY (opcional)
3. ODDS_REGIONS (default: eu)
4. ODDS_BOOKMAKERS (opcional)
5. ODDS_MIN_EV (default: 0.03)
6. ODDS_MIN_EDGE_GATE (default: 0.10)
7. ODDS_ONLY_VALUE_GAMES (default: true)
8. ODDS_MAX_SPORT_CALLS (default: 3)
9. ODDS_USE_UPCOMING (default: true)
10. ODDS_DEBUG_VISUAL (default: false)
11. SHRINKAGE_K_JOGOS (default: 6)
12. SHRINKAGE_PESO_MIN (default: 0.20)

Exemplo PowerShell (sessao atual):

```powershell
$env:FOOTBALL_DATA_TOKEN="seu_token"
$env:ODDS_API_KEY="sua_chave_odds"
```

## Execucao Local

Instalacao:

```powershell
python -m pip install --upgrade pip
pip install requests
```

Gerar previsoes:

```powershell
python predictor.py
```

Isso atualiza:

1. predictions.json
2. history.json

Depois, abra o frontend com servidor local (exemplo: Live Server) e acesse index.html.

Importante:

1. nao abrir por file:// (fetch pode falhar)
2. o frontend depende de predictions.json e history.json na raiz

## Backtest

Script disponivel: backtest.py

Comandos:

```powershell
python backtest.py
python backtest.py --days 30
```

Saidas do backtest:

1. acuracia por mercado
2. Brier score
3. desempenho por tier de confianca
4. tabela de calibracao por faixa de probabilidade

Observacao:

1. o proprio script informa que ha look-ahead bias leve para jogos recentes

## GitHub Actions (Atualizacao automatica)

Workflow: .github/workflows/update-predictions.yml

Comportamento atual:

1. executa a cada 3 minutos (cron `*/3 * * * *`)
2. executa manualmente via workflow_dispatch
3. instala requests
4. roda predictor.py e predictor_nba.py
5. faz git pull --rebase antes de cada push para evitar conflitos non-fast-forward
6. commita predictions.json, history.json, predictions_nba.json e history_nba.json se houver mudanca

## Fluxo Atual (execucao)

1. busca jogos do dia na football-data.org (futebol) e BallDontLie (NBA)
2. filtra por competicoes permitidas e dia local da aplicacao
3. calcula probabilidades/mercados/palpites por jogo com linha Over/Under dinamica
4. aplica baseline pre-jogo para estabilizar partidas em andamento/finalizadas
5. congela dicas do dia no primeiro run do dia
6. ativa recovery_tip apenas se a dica #1 falhar; escolhe a maior probabilidade disponivel fora das dicas fixas
7. dica de recuperacao e suprimida no frontend se todas as dicas do dia terminarem com acerto
8. atualiza history.json e history_nba.json com merge acumulativo por jogo

Secrets recomendados no repositorio:

1. FOOTBALL_DATA_TOKEN
2. ODDS_API_KEY (se usar odds)
3. BALLDONTLIE_API_KEY (NBA)

## Troubleshooting

1. Erro ao carregar predictions.json no frontend:
- rode python predictor.py
- use servidor local
- confirme que predictions.json existe na raiz

2. Nenhum jogo com valor esperado:
- verifique ODDS_API_KEY
- reduza ODDS_MIN_EV temporariamente
- confira se as competicoes do dia estao na lista permitida

3. Odds API retornando Unknown sport:
- algumas competicoes podem nao existir com aquela sport_key
- sistema ja tenta fallback por liga e segue operando

4. Favorito mudando durante o jogo:
- comportamento corrigido com baseline pre-jogo congelado

## Avisos e Boas Praticas

1. nao commite tokens/chaves
2. mantenha .env fora do versionamento
3. trate o sistema como apoio a decisao, nao garantia de resultado
4. revise periodicamente Brier/Log Loss e taxa por mercado para calibrar thresholds

## Estrutura de Pastas (Resumo)

1. predictor.py
2. backtest.py
3. app.js
4. styles.css
5. index.html
6. predictions.json
7. history.json
8. .github/workflows/update-predictions.yml
9. .env.example
