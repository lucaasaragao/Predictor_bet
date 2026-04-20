# WebScrapping - Radar de Palpites de Futebol

## 1) Resumo do que estamos fazendo
Este projeto monta um mini pipeline de analise de jogos de futebol:

- consulta dados da API football-data.org
- calcula probabilidades e sugestoes de aposta com um modelo simples (score + Poisson)
- exporta um arquivo JSON para consumo no frontend
- renderiza uma pagina web com filtros, cards de jogo, historico e palpites

Na pratica, o script Python gera os dados e a pagina HTML/JS apresenta esses dados de forma visual.

## 2) Arquitetura (visao rapida)

- predictor.py
  - busca jogos de competicoes permitidas
  - monta score de cada time (forma, ataque, defesa, mando, h2h)
  - calcula mercados (1X2, over/under 2.5, BTTS) via Poisson
  - gera palpites com nivel de confianca
  - exporta predictions.json para o frontend

- predictions.json
  - arquivo de saida consumido pela interface
  - contem metadados e lista de jogos com probabilidades, historico e palpites

- index.html
  - estrutura da pagina (header, filtros, cards)

- app.js
  - carrega predictions.json
  - aplica filtros de competicao e confianca
  - monta os cards dinamicamente no DOM

- styles.css
  - estilo visual da pagina (layout responsivo, cores, tipografia e animacoes)

- football.py e uol.py
  - scripts auxiliares para consulta/listagem de partidas via API
  - nao sao obrigatorios para o fluxo da pagina Radar, mas ajudam em exploracao de dados

## 3) Fluxo de dados ponta a ponta

1. Executar predictor.py
2. O script consulta a API e processa os jogos
3. O script salva predictions.json na raiz do projeto
4. Abrir index.html em servidor local
5. app.js faz fetch de predictions.json
6. A pagina renderiza os cards com os dados calculados

## 4) Como executar (Windows / PowerShell)

Prerequisitos:
- Python instalado
- pacote requests instalado

Comandos:

c:/python314/python.exe -m pip install requests
c:/python314/python.exe predictor.py

Depois, abra a pagina com servidor local (exemplo: Live Server no VS Code).

Importante:
- Evite abrir o HTML direto por file://, pois o fetch do JSON pode falhar dependendo do navegador.

## 5) Estrutura do predictions.json (resumo)

Cada jogo exportado inclui:

- competicao
- times (casa, visitante)
- probabilidades (casa, empate, visitante)
- favorito (nome, probabilidade, vantagem)
- gols_esperados (casa, visitante, total)
- mercados (under/over 2.5, btts sim/nao)
- historico dos times (ultimos jogos normalizados)
- palpites (tipo, opcao, probabilidade, confianca, justificativa)

## 6) Erros comuns e como resolver

Erro: "Nao foi possivel carregar predictions.json"

Causas comuns:
- o arquivo predictions.json ainda nao foi gerado
- pagina aberta sem servidor local (file://)
- fetch bloqueado por politica do navegador

Solucao:
1. rodar predictor.py para gerar/atualizar predictions.json
2. abrir index.html via servidor local
3. recarregar a pagina

## 7) Estado atual do projeto

- fluxo script -> JSON -> pagina funcionando
- tratamento de erro no app.js melhorado para indicar falha de rede/HTTP
- arquivo predictions.json gerado na raiz

## 8) Proximos passos recomendados

- mover token da API para variavel de ambiente (seguranca)
- criar rotina de atualizacao automatica do JSON (ex.: tarefa agendada)
- adicionar testes para funcoes de probabilidade e normalizacao
- opcional: separar backend (API propria) do frontend para escalar melhor

## 9) Publicacao segura no GitHub

Antes de publicar, siga este checklist:

1. Nunca commitar token, senha ou chave de API no codigo.
2. Use sempre variavel de ambiente para credenciais:
   - PowerShell (sessao atual):
     - $env:FOOTBALL_DATA_TOKEN="seu_token"
3. Crie e use um arquivo .env apenas local (nao versionado).
4. Garanta que .env e .venv estejam no .gitignore.
5. Se um token ja apareceu em arquivo/commit, gere um novo token no provedor (rotacao).
6. Revogue o token antigo imediatamente.

Observacao:
- Neste projeto, predictor.py, football.py e uol.py usam FOOTBALL_DATA_TOKEN via variavel de ambiente.

## 10) Atualizacao automatica no GitHub Pages (GitHub Actions)

Para atualizar o predictions.json sem rodar localmente toda vez, o projeto inclui workflow:

- .github/workflows/update-predictions.yml

Esse workflow:

1. roda a cada 6 horas (UTC) e tambem manualmente
2. instala dependencias Python
3. executa predictor.py
4. commita e envia predictions.json quando houver alteracao

Como ativar no GitHub:

1. Suba o repositorio com esse workflow.
2. No GitHub, abra Settings > Secrets and variables > Actions.
3. Crie o secret FOOTBALL_DATA_TOKEN com seu token real.
4. Em Actions, execute manualmente o workflow "Update predictions.json" na primeira vez.
5. Confirme que o predictions.json foi atualizado no repositorio.
6. Se o commit automatico falhar, em Settings > Actions > General ajuste Workflow permissions para "Read and write permissions".

Importante:

- O cron usa horario UTC.
- O GitHub Pages continua estatico: ele apenas serve o predictions.json que ja esta no repositorio.
