const state = {
  raw: null,
  competition: "",
  minConfidence: "LOW",
};

const confidenceRank = {
  LOW: 1,
  MEDIUM: 2,
  HIGH: 3,
};

function pct(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function confidenceClass(conf) {
  return (conf || "LOW").toLowerCase();
}

function confidenceLabel(conf) {
  const labels = { LOW: "Baixa", MEDIUM: "Média", HIGH: "Alta" };
  return labels[(conf || "LOW").toUpperCase()] || conf;
}

function historyBadgeClass(result) {
  if (result === "V") return "v";
  if (result === "E") return "e";
  return "d";
}

function translateTipType(type) {
  const labels = {
    WINNER: "Vencedor",
    OVER_UNDER: "Gols 2.5",
    BTTS: "Ambas Marcam",
    EMPATE: "Empate",
  };
  return labels[type] || type;
}

function translateTipOption(type, option) {
  const upperOption = String(option || "").toUpperCase();
  if (type === "BTTS") {
    if (upperOption === "YES") return "Sim";
    if (upperOption === "NO") return "Nao";
  }
  if (type === "OVER_UNDER") {
    if (upperOption === "OVER") return "Mais de 2.5";
    if (upperOption === "UNDER") return "Menos de 2.5";
  }
  return option;
}

function resolveWinnerLabel(option, match) {
  const upperOption = String(option || "").toUpperCase();
  if (upperOption === "1") return match?.times?.casa || "Casa";
  if (upperOption === "2") return match?.times?.visitante || "Visitante";
  if (upperOption === "X") return "Empate";
  return option;
}

function translateTipJustification(text) {
  return String(text || "")
    .replaceAll("UNDER 2.5", "Menos de 2.5 gols")
    .replaceAll("OVER 2.5", "Mais de 2.5 gols")
    .replaceAll("BTTS YES", "Ambas marcam - Sim")
    .replaceAll("BTTS NO", "Ambas marcam - Nao");
}

function translateQuickRead(text) {
  return String(text || "")
    .replaceAll("UNDER 2.5", "Menos de 2.5 gols")
    .replaceAll("OVER 2.5", "Mais de 2.5 gols")
    .replaceAll("em alta", "\u2197 em alta")
    .replaceAll("em baixa", "\u2198 em baixa");
}

async function loadData() {
  try {
    const response = await fetch("predictions.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Nao foi possivel carregar predictions.json (HTTP ${response.status})`);
    }
    return response.json();
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error("Falha de rede ao carregar predictions.json. Abra o projeto em servidor local (ex.: Live Server) e gere o arquivo com predictor.py.");
    }
    throw error;
  }
}

function fillHeader(data) {
  document.getElementById("generatedAt").textContent = data.generated_at || "--";
  document.getElementById("totalJogos").textContent = String(data.total_jogos ?? data.jogos?.length ?? 0);
}

function fillCompetitionFilter(data) {
  const select = document.getElementById("competitionFilter");
  const competitions = [...new Set((data.jogos || []).map((item) => item.competicao))].sort();
  competitions.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });
}

function passesFilters(match) {
  if (state.competition && match.competicao !== state.competition) {
    return false;
  }

  const minRank = confidenceRank[state.minConfidence] || 1;
  const bestTipRank = Math.max(
    ...(match.palpites || []).map((tip) => confidenceRank[(tip.confianca || "LOW").toUpperCase()] || 1),
    1
  );

  return bestTipRank >= minRank;
}

function renderProbabilities(container, match) {
  const rows = [
    { name: match.times.casa, value: match.probabilidades.casa },
    { name: "Empate", value: match.probabilidades.empate },
    { name: match.times.visitante, value: match.probabilidades.visitante },
  ].sort((a, b) => b.value - a.value);

  rows.forEach((row) => {
    const line = document.createElement("div");
    line.className = "prob-row";
    line.innerHTML = `
      <span>${row.name}</span>
      <div class="prob-track"><div class="prob-fill" style="width:${Math.max(0, Math.min(100, row.value * 100))}%"></div></div>
      <strong>${pct(row.value)}</strong>
    `;
    container.appendChild(line);
  });
}

function renderHistory(listEl, items) {
  listEl.innerHTML = "";
  (items || []).slice(0, 5).forEach((row) => {
    const li = document.createElement("li");

    const info = document.createElement("span");
    info.textContent = `${row.data} - ${row.mandante} x ${row.visitante} (${row.placar})`;

    const badge = document.createElement("span");
    badge.className = `badge ${historyBadgeClass(row.resultado)}`;
    badge.textContent = row.resultado_label;

    li.appendChild(info);
    li.appendChild(badge);
    listEl.appendChild(li);
  });

  if (!listEl.children.length) {
    const li = document.createElement("li");
    li.textContent = "Sem historico recente";
    listEl.appendChild(li);
  }
}

function renderTips(container, tips, match) {
  container.innerHTML = "";
  (tips || []).forEach((tip) => {
    const row = document.createElement("div");
    const conf = (tip.confianca || "LOW").toUpperCase();
    const translatedType = translateTipType(tip.tipo);
    const translatedOption = tip.tipo === "WINNER"
      ? resolveWinnerLabel(tip.opcao, match)
      : translateTipOption(tip.tipo, tip.opcao);
    const translatedJustification = translateTipJustification(tip.justificativa);
    row.className = "tip";

    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = translatedType;

    const confEl = document.createElement("span");
    confEl.className = `conf ${confidenceClass(conf)}`;
    confEl.textContent = confidenceLabel(conf);

    const detail = document.createElement("span");
    const strong = document.createElement("strong");
    strong.textContent = translatedOption;
    detail.appendChild(strong);
    detail.appendChild(document.createTextNode(` - ${pct(tip.probabilidade)}. ${translatedJustification}`));

    row.appendChild(tag);
    row.appendChild(confEl);
    row.appendChild(detail);
    container.appendChild(row);
  });
}

function renderCards() {
  const container = document.getElementById("cardsContainer");
  const template = document.getElementById("matchCardTemplate");
  container.innerHTML = "";

  const filtered = (state.raw?.jogos || []).filter(passesFilters);

  if (!filtered.length) {
    container.innerHTML = '<div class="empty">Nenhum jogo atende aos filtros atuais.</div>';
    return;
  }

  filtered.forEach((match) => {
    const node = template.content.cloneNode(true);

    node.querySelector(".competition").textContent = match.competicao;
    node.querySelector(".match-title").textContent = `${match.times.casa} vs ${match.times.visitante}`;
    node.querySelector(".favorite-line").textContent =
      `${match.favorito.nome} — ${pct(match.favorito.prob)} de chance | margem ${pct(match.favorito.vantagem)}`;
    node.querySelector(".quick-read").textContent = translateQuickRead(match.leitura_rapida);

    // Tendência de forma
    const formaRow = node.querySelector(".forma-row");
    const tendencia = match.tendencia || {};
    const formaLabel = { "em alta": "↗ em alta", "em baixa": "↘ em baixa", "estavel": "→ estável", "indefinida": null };
    const formaClass = { "em alta": "forma--alta", "em baixa": "forma--baixa", "estavel": "forma--estavel" };
    [[match.times.casa, tendencia.casa], [match.times.visitante, tendencia.visitante]].forEach(([nome, tend]) => {
      const label = formaLabel[tend];
      if (!label) return;
      const pill = document.createElement("span");
      pill.className = `forma-pill ${formaClass[tend] || ""}`;
      pill.textContent = `${nome} ${label}`;
      formaRow.appendChild(pill);
    });

    renderProbabilities(node.querySelector(".prob-bars"), match);

    const xgCasa = (match.gols_esperados.casa || 0).toFixed(2);
    const xgFora = (match.gols_esperados.visitante || 0).toFixed(2);
    const marketList = node.querySelector(".market-list");
    marketList.innerHTML = `
      <li class="market-xg"><span>xG esperado</span><strong>${xgCasa} × ${xgFora}</strong></li>
      <li><span>Menos de 2.5 gols</span><strong>${pct(match.mercados.under_25)}</strong></li>
      <li><span>Mais de 2.5 gols</span><strong>${pct(match.mercados.over_25)}</strong></li>
      <li><span>Ambas Marcam - Sim</span><strong>${pct(match.mercados.btts_yes)}</strong></li>
      <li><span>Ambas Marcam - Nao</span><strong>${pct(match.mercados.btts_no)}</strong></li>
    `;

    renderHistory(node.querySelector(".home-history"), match.historico.casa);
    renderHistory(node.querySelector(".away-history"), match.historico.visitante);
    renderTips(node.querySelector(".tips"), match.palpites, match);

    container.appendChild(node);
  });
}

function setupFilters() {
  document.getElementById("competitionFilter").addEventListener("change", (event) => {
    state.competition = event.target.value;
    renderCards();
  });

  document.getElementById("confidenceFilter").addEventListener("change", (event) => {
    state.minConfidence = event.target.value;
    renderCards();
  });
}

(async function init() {
  try {
    const data = await loadData();
    state.raw = data;
    fillHeader(data);
    fillCompetitionFilter(data);
    setupFilters();
    renderCards();
  } catch (error) {
    const errContainer = document.getElementById("cardsContainer");
    const errDiv = document.createElement("div");
    errDiv.className = "empty";
    errDiv.textContent = `Erro ao carregar dados: ${error.message}`;
    errContainer.appendChild(errDiv);
  }
})();
