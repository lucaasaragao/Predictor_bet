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

const THEME_STORAGE_KEY = "radar-theme";

function pct(value) {
  return `${(value * 100).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

function getCurrentTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function getThemeIconSvg(isLight) {
  return isLight
    ? '<svg viewBox="0 0 20 20" focusable="false" aria-hidden="true"><circle cx="10" cy="10" r="6" fill="currentColor" opacity="0.16"></circle><path d="M10 4a6 6 0 1 0 0 12a6 6 0 0 1 0-12Z" fill="currentColor"></path></svg>'
    : '<svg viewBox="0 0 20 20" focusable="false" aria-hidden="true"><circle cx="10" cy="10" r="6" fill="currentColor" opacity="0.16"></circle><path d="M10 4a6 6 0 0 1 0 12Z" fill="currentColor"></path></svg>';
}

function applyTheme(theme) {
  const nextTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = nextTheme;

  const themeToggle = document.getElementById("themeToggle");
  if (!themeToggle) return;

  const themeLabel = themeToggle.querySelector(".theme-toggle__label");
  const themeIcon = themeToggle.querySelector(".theme-toggle__icon");
  const isLight = nextTheme === "light";

  themeToggle.setAttribute("aria-pressed", String(isLight));
  themeToggle.setAttribute("aria-label", isLight ? "Ativar tema escuro" : "Ativar tema claro");

  if (themeLabel) {
    themeLabel.textContent = isLight ? "Modo escuro" : "Modo claro";
  }

  if (themeIcon) {
    themeIcon.innerHTML = getThemeIconSvg(isLight);
  }
}

function setupThemeToggle() {
  const themeToggle = document.getElementById("themeToggle");
  if (!themeToggle) return;

  applyTheme(getCurrentTheme());

  themeToggle.addEventListener("click", () => {
    const nextTheme = getCurrentTheme() === "dark" ? "light" : "dark";
    applyTheme(nextTheme);

    try {
      localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    } catch (error) {
    }
  });
}

function confidenceClass(conf) {
  return (conf || "LOW").toLowerCase();
}

function confidenceLabel(conf) {
  const labels = { LOW: "Baixa", MEDIUM: "Média", HIGH: "Alta" };
  return labels[(conf || "LOW").toUpperCase()] || conf;
}

function parseGeneratedAt(value) {
  if (!value) return null;

  const normalized = String(value).trim().replace(" ", "T");
  const parsedDate = new Date(normalized);
  if (Number.isNaN(parsedDate.getTime())) {
    return null;
  }

  return parsedDate;
}

function formatGeneratedAt(value, compact = false) {
  const parsedDate = parseGeneratedAt(value);
  if (!parsedDate) {
    return value || "--";
  }

  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    ...(compact ? {} : { year: "numeric" }),
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsedDate);
}

function syncHeaderMeta() {
  const generatedAtEl = document.getElementById("generatedAt");
  if (!generatedAtEl) return;

  const rawGeneratedAt = state.raw?.generated_at || "--";
  const isMobile = window.matchMedia("(max-width: 768px)").matches;

  generatedAtEl.textContent = formatGeneratedAt(rawGeneratedAt, isMobile);
  generatedAtEl.title = rawGeneratedAt;
  generatedAtEl.setAttribute("aria-label", `Atualizado em ${formatGeneratedAt(rawGeneratedAt, false)}`);
}

function setupMobileTopbar() {
  const topbar = document.querySelector(".topbar");
  if (!topbar) return;

  const mobileQuery = window.matchMedia("(max-width: 768px)");

  const syncTopbarState = () => {
    const isMobile = mobileQuery.matches;
    topbar.classList.toggle("is-scrolled", isMobile && window.scrollY > 16);
  };

  syncTopbarState();
  window.addEventListener("scroll", syncTopbarState, { passive: true });
  mobileQuery.addEventListener("change", syncTopbarState);
  window.addEventListener("resize", syncTopbarState);
}

function historyBadgeClass(result) {
  if (result === "V") return "v";
  if (result === "E") return "e";
  return "d";
}

function translateTipType(type) {
  const labels = {
    WINNER: "Resultado",
    OVER_UNDER: "Quantidade de gols",
    BTTS: "Ambos marcam",
    EMPATE: "Empate",
  };
  return labels[type] || type;
}

function translateTipOption(type, option, match) {
  const upperOption = String(option || "").toUpperCase();
  if (type === "WINNER") {
    return resolveWinnerLabel(option, match);
  }
  if (type === "BTTS") {
    if (upperOption === "YES") return "Sim, os dois marcam";
    if (upperOption === "NO") return "Não, um fica sem gol";
  }
  if (type === "OVER_UNDER") {
    if (upperOption === "OVER") return "3 gols ou mais";
    if (upperOption === "UNDER") return "Menos de 3 gols";
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

function buildTipJustificationHuman(tip, match) {
  const casa = match?.times?.casa || "Casa";
  const visitante = match?.times?.visitante || "Visitante";
  const prob = Math.round((tip.probabilidade || 0) * 100);
  const xgCasa = Number(match?.gols_esperados?.casa || 0).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const xgVisit = Number(match?.gols_esperados?.visitante || 0).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  if (tip.tipo === "WINNER") {
    const vencedor = resolveWinnerLabel(tip.opcao, match);
    if (String(tip.opcao).toUpperCase() === "X") {
      return `${prob}% de chance de os dois times terminarem empatados.`;
    }
    return `O modelo dá ${prob}% de chance de vitória para o ${vencedor} neste jogo.`;
  }

  if (tip.tipo === "OVER_UNDER") {
    if (String(tip.opcao).toUpperCase() === "UNDER") {
      return `A linha de 2,5 gols aponta para um jogo mais fechado. Em ${prob}% dos cenários simulados, a partida termina com até 2 gols.`;
    } else {
      return `A linha de 2,5 gols aponta para um jogo mais aberto. Em ${prob}% dos cenários simulados, a partida termina com 3 gols ou mais.`;
    }
  }

  if (tip.tipo === "BTTS") {
    if (String(tip.opcao).toUpperCase() === "YES") {
      return `${casa} deve marcar cerca de ${xgCasa} gol(s) e ${visitante} cerca de ${xgVisit}. Há ${prob}% de chance de os dois times balançarem a rede.`;
    } else {
      return `${casa} tem expectativa de ${xgCasa} gol(s) e ${visitante} de ${xgVisit}. Em ${prob}% das simulações, um dos times termina sem marcar.`;
    }
  }

  return translateTipJustification(tip.justificativa);
}

function translateQuickRead(text) {
  return String(text || "")
    .replaceAll("UNDER 2.5", "Menos de 2,5 gols")
    .replaceAll("OVER 2.5", "Mais de 2,5 gols")
    .replaceAll("em alta", "\u2197 em alta")
    .replaceAll("em baixa", "\u2198 em baixa")
    .replace(/xG total\s*[\u2248~]?\s*\d+(?:[\.,]\d+)?/gi, "linha de 2,5 gols")
    .replace(/\s*—\s*/g, ". ");
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
  document.getElementById("totalJogos").textContent = String(data.total_jogos ?? data.jogos?.length ?? 0);
  syncHeaderMeta();

  const ah = data.acertos_hoje;
  if (ah && ah.total > 0 && ah.taxa != null) {
    const badge = document.getElementById("acertosHoje");
    const val = document.getElementById("acertosHojeVal");
    if (badge && val) {
      val.textContent = `${ah.acertos}/${ah.total} (${pct(ah.taxa)})`;
      badge.hidden = false;
    }
  }
}

async function loadHistory() {
  const resp = await fetch(`history.json?v=${Date.now()}`, { cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function renderAdminPanel(data) {
  const content = document.getElementById("adminContent");
  if (!content) return;

  const dias = data?.dias || [];
  if (!dias.length) {
    content.innerHTML = '<p class="admin-empty">Nenhum histórico disponível ainda.</p>';
    return;
  }

  content.innerHTML = dias.map((dia) => {
    const dataFmt = new Date(dia.data + "T12:00:00").toLocaleDateString("pt-BR", {
      weekday: "short", day: "2-digit", month: "2-digit",
    });
    const taxa = dia.taxa_geral ?? 0;
    const taxaClass = taxa >= 0.6 ? "good" : taxa >= 0.4 ? "mid" : "bad";
    const taxaLabel = dia.total_palpites
      ? `${dia.total_acertos}/${dia.total_palpites} acertos · ${pct(taxa)}`
      : "Sem resultados ainda";

    const mercadosHtml = Object.entries(dia.mercados || {})
      .map(([tipo, m]) => `
        <div class="admin-mercado">
          <span class="admin-mercado__nome">${tipo}</span>
          <span class="admin-mercado__stats">${m.acertos}/${m.total} · ${pct(m.taxa)}</span>
        </div>`)
      .join("");

    const jogosHtml = (dia.jogos || []).map((j) => {
      const tips = j.palpites
        .map((p) => {
          const ok = p.resultado === "ACERTO";
          return `<span class="admin-tip admin-tip--${ok ? "ok" : "err"}">${p.tipo} ${p.opcao} <em>${p.confianca}</em></span>`;
        })
        .join("");
      return `
        <div class="admin-jogo">
          <div class="admin-jogo__match">${j.casa} <span class="admin-placar">${j.placar}</span> ${j.visitante}</div>
          <div class="admin-jogo__tips">${tips}</div>
        </div>`;
    }).join("");

    return `
      <div class="admin-dia">
        <div class="admin-dia__header">
          <strong>${dataFmt}</strong>
          <span class="admin-dia__taxa admin-dia__taxa--${taxaClass}">${taxaLabel}</span>
        </div>
        ${mercadosHtml ? `<div class="admin-dia__mercados">${mercadosHtml}</div>` : ""}
        ${jogosHtml ? `<div class="admin-dia__jogos">${jogosHtml}</div>` : ""}
      </div>`;
  }).join("");
}

async function openAdminPanel() {
  const panel = document.getElementById("adminPanel");
  if (!panel || !panel.hidden) return;

  panel.hidden = false;
  document.body.style.overflow = "hidden";

  const content = document.getElementById("adminContent");
  if (content) content.innerHTML = '<p class="admin-loading">Carregando...</p>';

  try {
    const data = await loadHistory();
    renderAdminPanel(data);
  } catch (err) {
    if (content) content.innerHTML = `<p class="admin-empty">Erro ao carregar histórico: ${err.message}</p>`;
  }
}

function closeAdminPanel() {
  const panel = document.getElementById("adminPanel");
  if (!panel) return;
  panel.hidden = true;
  document.body.style.overflow = "";
  history.replaceState(null, "", window.location.pathname);
}

function initAdminPanel() {
  const panel = document.getElementById("adminPanel");
  if (!panel) return;

  document.getElementById("adminClose")?.addEventListener("click", closeAdminPanel);

  panel.addEventListener("click", (e) => {
    if (e.target === panel) closeAdminPanel();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden) closeAdminPanel();
  });

  // Gatilho 1: URL hash #admin (na carga da página)
  if (window.location.hash === "#admin") openAdminPanel();

  // Gatilho 2: hashchange (usuário adiciona #admin na URL enquanto na página)
  window.addEventListener("hashchange", () => {
    if (window.location.hash === "#admin") openAdminPanel();
  });

  // Gatilho 3: triple-click no copyright do footer
  let clickCount = 0;
  let clickTimer = null;
  document.getElementById("footerCopyright")?.addEventListener("click", () => {
    clickCount++;
    clearTimeout(clickTimer);
    clickTimer = setTimeout(() => { clickCount = 0; }, 600);
    if (clickCount >= 3) {
      clickCount = 0;
      openAdminPanel();
    }
  });
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

  Object.values(chips).forEach((chip) => {
    if (!chip) return;
    chip.classList.remove("is-active");
    chip.setAttribute("aria-pressed", "false");
  });

  if (chips[selected]) {
    chips[selected].classList.add("is-active");
    chips[selected].setAttribute("aria-pressed", "true");
  }
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

function getPrimaryTip(match) {
  const tips = match?.palpites || [];
  return tips.find((tip) => tip.valor_esperado_positivo === true) || tips[0] || null;
}

function buildGoalsProbabilityLabel(match) {
  const under = Number(match?.mercados?.under_25);
  const over = Number(match?.mercados?.over_25);

  if (!Number.isFinite(under) && !Number.isFinite(over)) {
    return "Dados indisponíveis";
  }

  if (!Number.isFinite(over) || (Number.isFinite(under) && under >= over)) {
    return `Menos de 2,5 (${pct(under)})`;
  }

  return `Mais de 2,5 (${pct(over)})`;
}

function buildCardSnapshot(match) {
  const primaryTip = getPrimaryTip(match);
  const probability = Math.round((match?.favorito?.prob || 0) * 100);
  const bestBet = primaryTip
    ? translateTipOption(primaryTip.tipo, primaryTip.opcao, match)
    : "Sem sugestão disponível";
  const confidence = primaryTip ? confidenceLabel(primaryTip.confianca) : "Baixa";
  const confidenceTone = primaryTip ? confidenceClass(primaryTip.confianca) : "low";
  const goalsProbability = buildGoalsProbabilityLabel(match);

  return `
    <div class="card-snapshot-grid">
      <div class="snapshot-item">
        <span class="snapshot-label">Probabilidade</span>
        <strong class="highlight">${probability}%</strong>
      </div>
      <div class="snapshot-item snapshot-item--wide">
        <span class="snapshot-label">Melhor aposta</span>
        <strong class="highlight highlight--secondary">${bestBet}</strong>
      </div>
      <div class="snapshot-item">
        <span class="snapshot-label">Confiança</span>
        <span class="conf ${confidenceTone}">${confidence}</span>
      </div>
      <div class="snapshot-item">
        <span class="snapshot-label">Probabilidade de gols</span>
        <strong class="highlight highlight--secondary">${goalsProbability}</strong>
      </div>
    </div>
  `;
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

function buildSummaryNarrative(match) {
  const casa = match?.times?.casa || "Casa";
  const visitante = match?.times?.visitante || "Visitante";
  const favNome = match?.favorito?.nome || casa;
  const favProb = Math.round((match?.favorito?.prob || 0) * 100);
  const underProb = Math.round((match?.mercados?.under_25 || 0) * 100);
  const bttsNoProb = Math.round((match?.mercados?.btts_no || 0) * 100);

  let parts = [];

  if (favProb >= 60) {
    parts.push(`O ${favNome} entra como grande favorito, com ${favProb}% de chance de vencer.`);
  } else if (favProb >= 50) {
    parts.push(`O ${favNome} tem leve vantagem: ${favProb}% de chance de vitória, mas o jogo pode surpreender.`);
  } else {
    parts.push(`Jogo equilibrado, com o ${favNome} à frente em ${favProb}% de probabilidade de vitória. Ainda assim, qualquer resultado é possível.`);
  }

  if (underProb >= 60) {
    parts.push(`A tendência principal do mercado é menos de 2,5 gols.`);
  } else if (underProb >= 50) {
    parts.push(`A linha de 2,5 gols está equilibrada, com leve inclinação para menos de 2,5.`);
  } else {
    parts.push(`A tendência principal do mercado é mais de 2,5 gols.`);
  }

  if (bttsNoProb >= 60) {
    parts.push(`Um dos times deve terminar sem marcar.`);
  } else if (bttsNoProb >= 50) {
    parts.push(`Há mais chance de um dos times não marcar do que de os dois balançarem a rede.`);
  } else {
    parts.push(`Os dois times têm boas chances de marcar.`);
  }

  return parts.join(" ");
}

function renderTips(container, tips, match) {
  container.innerHTML = "";

  if (state.raw?.odds_debug_visual && match?.odds_debug) {
    const debug = match.odds_debug;
    const debugBox = document.createElement("details");
    debugBox.className = "odds-debug";
    const evFilter = debug?.ev_filter === "pass" ? "aprovado" : debug?.ev_filter === "fail" ? "reprovado" : "--";
    const sportKey = debug?.sport_key || "--";
    debugBox.innerHTML = `
      <summary>Debug Odds: ${debug?.status || "--"}</summary>
      <div class="odds-debug-body">
        <div><strong>Competição:</strong> ${debug?.competition || "--"}</div>
        <div><strong>Sport key:</strong> ${sportKey}</div>
        <div><strong>Motivo:</strong> ${debug?.reason || "--"}</div>
        <div><strong>Filtro EV:</strong> ${evFilter}</div>
        <div><strong>Detalhe EV:</strong> ${debug?.ev_reason || "--"}</div>
        <div><strong>Match ID Odds:</strong> ${debug?.odds_match_id || "--"}</div>
      </div>
    `;
    container.appendChild(debugBox);
  }

  // Alertas contextuais (ex: fadiga por back-to-back)
  (match?.alertas || []).forEach(alerta => {
    const alertEl = document.createElement("div");
    alertEl.className = "tip-alerta";
    alertEl.textContent = "⚠️ " + alerta;
    container.appendChild(alertEl);
  });

  const summaryBox = document.createElement("div");
  summaryBox.className = "tip-summary";
  summaryBox.textContent = buildSummaryNarrative(match);
  container.appendChild(summaryBox);

  const baseTips = tips || [];
  const valueTips = baseTips.filter((tip) => tip.valor_esperado_positivo === true);
  const tipsToRender = valueTips.length ? valueTips : baseTips;

  tipsToRender.forEach(tip => {
    const tipEl = document.createElement("div");
    tipEl.className = "tip";
    
    let resultMark = "";
    if (tip.resultado_verificador === "ACERTO") {
      resultMark = '<span class="tip-mark tip-mark--acerto">✅ Acerto</span>';
    } else if (tip.resultado_verificador === "ERRO") {
      resultMark = '<span class="tip-mark tip-mark--erro">❌ Erro</span>';
    }

    let valueBadge = "";
    if (Number.isFinite(tip.odd_decimal) && Number.isFinite(tip.ev)) {
      const evPct = pct(tip.ev || 0);
      valueBadge = ` <span class="tip-value ${tip.valor_esperado_positivo ? "is-positive" : ""}">odd ${Number(tip.odd_decimal).toFixed(2)} | EV ${evPct}</span>`;
    }

    tipEl.innerHTML = `
      <div class="tag">${translateTipType(tip.tipo)}</div>
      <div class="conf ${confidenceClass(tip.confianca)}">${confidenceLabel(tip.confianca)}</div>
      <div class="tip-desc">
        <strong>${translateTipOption(tip.tipo, tip.opcao, match)}</strong>. <span class="tip-just">${buildTipJustificationHuman(tip, match)}</span>
        ${valueBadge}
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

  const filtered = (state.raw?.jogos || [])
    .filter(passesFilters)
    .sort((a, b) => new Date(a.data) - new Date(b.data));
  updateConfidenceHelp(filtered.length);

  if (!filtered.length) {
    container.innerHTML = '<div class="empty">Nenhum jogo atende aos filtros atuais.</div>';
    return;
  }

  filtered.forEach((match) => {
    const node = template.content.cloneNode(true);
    const cardEl = node.querySelector(".card");
    const cardBadgesEl = node.querySelector(".card-badges");

    let matchDateLabel = "";
    if (match.data) {
        const dateObj = new Date(match.data);
        const day = dateObj.getDate().toString().padStart(2, '0');
        const month = (dateObj.getMonth() + 1).toString().padStart(2, '0');
        const hours = dateObj.getHours().toString().padStart(2, '0');
        const minutes = dateObj.getMinutes().toString().padStart(2, '0');
        matchDateLabel = `${day}/${month} às ${hours}:${minutes}`;
    }
    node.querySelector(".competition").textContent = match.competicao;
    const matchDateEl = node.querySelector(".match-date");
    if (matchDateLabel) {
      matchDateEl.textContent = matchDateLabel;
      matchDateEl.hidden = false;
    }
    
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
      cardBadgesEl.appendChild(badge);
    } else if (match.status === "IN_PLAY" || match.status === "PAUSED") {
      const badge = document.createElement("span");
      badge.className = "card-status-badge card-status-badge--live";
      badge.textContent = "Ao Vivo";
      cardBadgesEl.appendChild(badge);
    }

    if (match.odds_valor_alto) {
      const valueBadge = document.createElement("span");
      valueBadge.className = "card-status-badge card-status-badge--value";
      valueBadge.textContent = "Possibilidade alta";
      cardBadgesEl.appendChild(valueBadge);
    } else if (match.odds_integradas) {
      const oddsBadge = document.createElement("span");
      oddsBadge.className = "card-status-badge card-status-badge--odds";
      oddsBadge.textContent = "Odds integradas";
      cardBadgesEl.appendChild(oddsBadge);
    }

    const miniOdds = document.createElement("div");
    miniOdds.className = "card-snapshot";
    miniOdds.innerHTML = buildCardSnapshot(match);
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

  document.querySelectorAll(".filter-chip[data-confidence]").forEach((chip) => {
    chip.addEventListener("click", () => {
      state.minConfidence = chip.dataset.confidence || "LOW";
      renderCards();
    });
  });

  document.getElementById("clearFilters")?.addEventListener("click", () => {
    state.competition = "";
    state.minConfidence = "LOW";

    const competitionFilter = document.getElementById("competitionFilter");
    if (competitionFilter) {
      competitionFilter.value = "";
    }

    renderCards();
  });
}

(async function init() {
  setupThemeToggle();
  setupMobileTopbar();
  initAdminPanel();

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

window.addEventListener("resize", syncHeaderMeta);
