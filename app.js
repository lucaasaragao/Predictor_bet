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
  return `${(value * 100).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
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
    WINNER: "Resultado final",
    OVER_UNDER: "Linha de gols 2,5",
    BTTS: "Ambas marcam",
    EMPATE: "Empate",
  };
  return labels[type] || type;
}

function translateTipOption(type, option) {
  const upperOption = String(option || "").toUpperCase();
  if (type === "BTTS") {
    if (upperOption === "YES") return "Sim";
    if (upperOption === "NO") return "Não";
  }
  if (type === "OVER_UNDER") {
    if (upperOption === "OVER") return "Mais de 2,5 gols";
    if (upperOption === "UNDER") return "Menos de 2,5 gols";
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
    .replaceAll("UNDER 2.5", "tendência de menos de 2,5 gols")
    .replaceAll("OVER 2.5", "tendência de mais de 2,5 gols")
    .replaceAll("BTTS YES", "tendência de ambas marcarem")
    .replaceAll("BTTS NO", "tendência de pelo menos um time não marcar");
}

function translateQuickRead(text) {
  return String(text || "")
    .replaceAll("UNDER 2.5", "Menos de 2,5 gols")
    .replaceAll("OVER 2.5", "Mais de 2,5 gols")
    .replaceAll("em alta", "\u2197 em alta")
    .replaceAll("em baixa", "\u2198 em baixa");
}

async function loadData() {
  try {
    const response = await fetch("predictions.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Não foi possível carregar predictions.json (HTTP ${response.status})`);
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

function updateConfidenceHelp(visibleCount) {
  const helpEl = document.getElementById("confidenceHelp");
  if (!helpEl) return;

  const chips = {
    LOW: document.getElementById("confChipLow"),
    MEDIUM: document.getElementById("confChipMedium"),
    HIGH: document.getElementById("confChipHigh"),
  };

  const total = (state.raw?.jogos || []).length;
  const shown = Number.isFinite(visibleCount)
    ? visibleCount
    : (state.raw?.jogos || []).filter(passesFilters).length;
  const selected = (state.minConfidence || "LOW").toUpperCase();

  Object.values(chips).forEach((chip) => chip?.classList.remove("is-active"));
  chips[selected]?.classList.add("is-active");

  helpEl.textContent = `Mostrando ${shown}/${total} jogos`;
}

function renderProbabilities(container, match) {
  const rows = [
    { name: match.times.casa, value: match.probabilidades.casa },
    { name: "Empate", value: match.probabilidades.empate },
    { name: match.times.visitante, value: match.probabilidades.visitante },
  ].sort((a, b) => b.value - a.value);

  const rankLevel = ["h", "m", "l"];

  rows.forEach((row, index) => {
    const level = rankLevel[index] || "l";
    const line = document.createElement("div");
    line.className = "prob-row";
    line.innerHTML = `
      <span class="prob-name">${row.name}</span>
      <strong class="prob-value">${pct(row.value)}</strong>
      <div class="prob-track"><div class="prob-fill ${level}" style="width:${Math.max(0, Math.min(100, row.value * 100))}%"></div></div>
    `;
    container.appendChild(line);
  });
}

function buildMiniOddsSummary(match) {
  const rows = [
    { name: match.times.casa, value: match.probabilidades.casa },
    { name: "Empate", value: match.probabilidades.empate },
    { name: match.times.visitante, value: match.probabilidades.visitante },
  ].sort((a, b) => b.value - a.value);

  return rows
    .map((row) => `<div class="mini-odd-row"><span class="mini-odd-name">${row.name}</span><strong class="mini-odd-value">${pct(row.value)}</strong></div>`)
    .join("");
}

function setCardExpanded(cardEl, expanded) {
  cardEl.classList.toggle("is-collapsed", !expanded);
  cardEl.setAttribute("aria-expanded", String(expanded));
}

function bindCardToggle(cardEl) {
  const toggleCard = () => {
    const shouldExpand = cardEl.classList.contains("is-collapsed");
    setCardExpanded(cardEl, shouldExpand);
  };

  cardEl.addEventListener("click", (event) => {
    if (event.currentTarget !== cardEl) return;
    toggleCard();
  });

  cardEl.addEventListener("keydown", (event) => {
    if (event.currentTarget !== cardEl) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    toggleCard();
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
    badge.textContent = String(row.resultado_label || row.resultado || "D").trim().charAt(0).toUpperCase();

    li.appendChild(info);
    li.appendChild(badge);
    listEl.appendChild(li);
  });

  if (!listEl.children.length) {
    const li = document.createElement("li");
    li.textContent = "Sem histórico recente.";
    listEl.appendChild(li);
  }
}

function renderTips(container, tips, match) {
  container.innerHTML = "";
  const casa = match?.times?.casa || "Time da casa";
  const visitante = match?.times?.visitante || "Visitante";
  const favorito = match?.favorito?.nome || casa;

  const pCasa = pct(match?.probabilidades?.casa || 0);
  const pEmpate = pct(match?.probabilidades?.empate || 0);
  const pVisitante = pct(match?.probabilidades?.visitante || 0);
  const pUnder25 = pct(match?.mercados?.under_25 || 0);
  const pOver25 = pct(match?.mercados?.over_25 || 0);
  const pBttsYes = pct(match?.mercados?.btts_yes || 0);
  const pBttsNo = pct(match?.mercados?.btts_no || 0);
  const xgTotal = Number(match?.gols_esperados?.total || 0).toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const summary = `${favorito} com maior probabilidade de vitória: ${pct(match?.favorito?.prob || 0)}. `
    + `Vitória do ${casa}: ${pCasa}, empate: ${pEmpate}, vitória do ${visitante}: ${pVisitante}. `
    + `Tendência de gols: mais de 2,5 gols em ${pOver25} e menos de 2,5 gols em ${pUnder25}. `
    + `Ambas marcam: sim em ${pBttsYes} e não em ${pBttsNo}. `
    + `Total de gols esperados (xG): ${xgTotal}.`;

  const summaryBox = document.createElement("div");
  summaryBox.className = "tip-summary";
  summaryBox.textContent = summary;
  container.appendChild(summaryBox);

  (tips || []).forEach(tip => {
    const tipEl = document.createElement("div");
    tipEl.className = "tip";
    
    let resultMark = "";
    if (tip.resultado_verificador === "ACERTO") {
      resultMark = '<span class="tip-mark tip-mark--acerto">✅ Acerto</span>';
    } else if (tip.resultado_verificador === "ERRO") {
      resultMark = '<span class="tip-mark tip-mark--erro">❌ Erro</span>';
    }

    tipEl.innerHTML = `
      <div class="tag">${translateTipType(tip.tipo)}</div>
      <div class="conf ${confidenceClass(tip.confianca)}">${confidenceLabel(tip.confianca)}</div>
      <div class="tip-desc">
        ${translateTipOption(tip.tipo, tip.opcao)} — <span class="tip-just">${translateTipJustification(tip.justificativa)}</span>
        ${resultMark}
      </div>
    `;
    container.appendChild(tipEl);
  });
}

function renderCards() {
  const container = document.getElementById("cardsContainer");
  const template = document.getElementById("matchCardTemplate");

  container.innerHTML = "";

  const filtered = (state.raw?.jogos || []).filter(passesFilters);
  updateConfidenceHelp(filtered.length);

  if (!filtered.length) {
    container.innerHTML = '<div class="empty">Nenhum jogo atende aos filtros atuais.</div>';
    return;
  }

  filtered.forEach((match) => {
    const node = template.content.cloneNode(true);
    const cardEl = node.querySelector(".card");

    let compStr = match.competicao;
    if (match.data) {
        const dateObj = new Date(match.data);
        const day = dateObj.getDate().toString().padStart(2, '0');
        const month = (dateObj.getMonth() + 1).toString().padStart(2, '0');
        const hours = dateObj.getHours().toString().padStart(2, '0');
        const minutes = dateObj.getMinutes().toString().padStart(2, '0');
        compStr += ` • ${day}/${month} às ${hours}:${minutes}`;
    }
    node.querySelector(".competition").textContent = compStr;
    
    let titleContent = `${match.times.casa} x ${match.times.visitante}`;
    if (match.status === "FINISHED" && match.placar_atual && match.placar_atual.casa !== null) {
      titleContent = `${match.times.casa} ${match.placar_atual.casa} x ${match.placar_atual.visitante} ${match.times.visitante}`;
    } else if (match.status === "IN_PLAY" || match.status === "PAUSED") {
      titleContent = `${match.times.casa} ${match.placar_atual?.casa ?? 0} x ${match.placar_atual?.visitante ?? 0} ${match.times.visitante}`;
    }
    node.querySelector(".match-title").textContent = titleContent;

    if (match.status === "FINISHED") {
      const badge = document.createElement("span");
      badge.className = "card-status-badge card-status-badge--finished";
      badge.textContent = "Finalizado";
      node.querySelector(".card-head").appendChild(badge);
    } else if (match.status === "IN_PLAY" || match.status === "PAUSED") {
      const badge = document.createElement("span");
      badge.className = "card-status-badge card-status-badge--live";
      badge.textContent = "Ao Vivo";
      node.querySelector(".card-head").appendChild(badge);
    }

    const miniOdds = document.createElement("div");
    miniOdds.className = "mini-odds";
    miniOdds.innerHTML = buildMiniOddsSummary(match);
    node.querySelector(".card-head").insertAdjacentElement("afterend", miniOdds);

    setCardExpanded(cardEl, false);
    cardEl.setAttribute("role", "button");
    cardEl.setAttribute("tabindex", "0");
    bindCardToggle(cardEl);

    node.querySelector(".favorite-line").textContent =
      `${match.favorito.nome} com maior probabilidade de vitória, com ${pct(match.favorito.prob)} de chance e margem estimada de ${pct(match.favorito.vantagem)}.`;
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

    const xgCasa = Number(match.gols_esperados.casa || 0).toLocaleString("pt-BR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    const xgFora = Number(match.gols_esperados.visitante || 0).toLocaleString("pt-BR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    const marketList = node.querySelector(".market-list");
    marketList.innerHTML = `
      <li class="market-xg"><span>Gols esperados (xG) por time</span><strong>${match.times.casa}: ${xgCasa} | ${match.times.visitante}: ${xgFora}</strong></li>
      <li><span>Menos de 2,5 gols</span><strong>${pct(match.mercados.under_25)}</strong></li>
      <li><span>Mais de 2,5 gols</span><strong>${pct(match.mercados.over_25)}</strong></li>
      <li><span>Ambas Marcam - Sim</span><strong>${pct(match.mercados.btts_yes)}</strong></li>
      <li><span>Ambas Marcam - Não</span><strong>${pct(match.mercados.btts_no)}</strong></li>
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
