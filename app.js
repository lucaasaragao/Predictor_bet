const state = {
  raw: null,
  rawNba: null,
  sport: "football",
  competition: "",
  minConfidence: "LOW",
};

const confidenceRank = {
  LOW: 1,
  MEDIUM: 2,
  HIGH: 3,
};

const THEME_STORAGE_KEY = "radar-theme";

// Limites de quantidade de jogos para definir o número de dicas exibidas
const LIMITE_JOGOS_TRES_DICAS = 10;
const LIMITE_JOGOS_DUAS_DICAS = 5;

// Competições excluídas da seção de dicas
const COMPETICOES_EXCLUIDAS_DICAS = new Set([
  "Campeonato Brasileiro Série A",
  "Campeonato Brasileiro Série B",
]);

// Thresholds de probabilidade para coloração das dicas
const PROB_VITORIA_ALTA = 0.70;
const PROB_VITORIA_MEDIA = 0.55;
const TIMEZONE_FORTALEZA = "America/Fortaleza";

function formatarPorcentagem(value) {
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
  const hasTimezone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(normalized);
  const isoValue = hasTimezone ? normalized : `${normalized}Z`;
  const parsedDate = new Date(isoValue);
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
    timeZone: TIMEZONE_FORTALEZA,
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
    SPREAD: "Vantagem de pontos",
  };
  return labels[type] || type;
}

function translateTipTypeNba(type) {
  const labels = {
    WINNER: "Vencedor",
    OVER_UNDER: "Total de pontos",
    SPREAD: "Vantagem de pontos",
  };
  return labels[type] || type;
}

function translateTipOptionNba(tipo, opcao, match) {
  const upper = String(opcao || "").toUpperCase();
  if (tipo === "WINNER") {
    if (upper === "CASA") return match?.times?.casa || "Casa";
    if (upper === "VISIT") return match?.times?.visitante || "Visitante";
  }
  if (tipo === "OVER_UNDER") {
    const linha = match?.mercados?.over_linha || "";
    const linhaStr = linha ? ` ${linha}` : "";
    if (upper === "OVER") return `Mais de${linhaStr} pts`;
    if (upper === "UNDER") return `Menos de${linhaStr} pts`;
  }
  return opcao;
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
    const ouMatch = upperOption.match(/^(OVER|UNDER)(?:_(\d+(?:\.\d+)?))?$/);
    if (ouMatch) {
      const side = ouMatch[1];
      const linha = ouMatch[2] ? Number(ouMatch[2]).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : "2,5";
      return side === "OVER" ? `Mais de ${linha} gols` : `Menos de ${linha} gols`;
    }
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
    const parsed = parseOuOpcao(tip.opcao);
    const linhaNum = parsed?.linha ?? 2.5;
    const linhaStr = linhaNum.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    const golsThreshold = Math.ceil(linhaNum);
    if (parsed?.side === "UNDER") {
      return `A linha de ${linhaStr} gols aponta para um jogo mais fechado. Em ${prob}% dos cenários simulados, a partida termina com até ${golsThreshold - 1} gols.`;
    } else {
      return `A linha de ${linhaStr} gols aponta para um jogo mais aberto. Em ${prob}% dos cenários simulados, a partida termina com ${golsThreshold} gols ou mais.`;
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

async function loadNbaData() {
  try {
    const response = await fetch("predictions_nba.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Não foi possível carregar predictions_nba.json (HTTP ${response.status})`);
    }
    return response.json();
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error("Falha de rede ao carregar predictions_nba.json.");
    }
    throw error;
  }
}

function normalizeFootballMatch(match) {
  const times = match?.times || {};
  const casa = times.casa ?? match?.casa ?? match?.mandante ?? match?.home_team ?? "Casa";
  const visitante = times.visitante ?? match?.visitante ?? match?.fora ?? match?.away_team ?? "Visitante";
  const escudoCasa = times.escudo_casa ?? match?.escudo_casa ?? match?.homeTeam?.crest ?? match?.home_team_crest ?? "";
  const escudoVisitante = times.escudo_visitante ?? match?.escudo_visitante ?? match?.awayTeam?.crest ?? match?.away_team_crest ?? "";

  return {
    ...match,
    times: {
      ...times,
      casa: String(casa),
      visitante: String(visitante),
      escudo_casa: escudoCasa || undefined,
      escudo_visitante: escudoVisitante || undefined,
    },
  };
}

function normalizeFootballData(data) {
  const jogos = Array.isArray(data?.jogos) ? data.jogos.map(normalizeFootballMatch) : [];
  const jogosByKey = new Map(
    jogos.map((jogo) => [`${jogo?.times?.casa || ""}|${jogo?.times?.visitante || ""}|${jogo?.data || ""}`, jogo])
  );

  const rawRecovery = data?.recovery_tip;
  let recoveryTip = { ativo: false };
  if (rawRecovery?.ativo) {
    const recoveryGame = normalizeFootballMatch(rawRecovery?.jogo || {});
    const recoveryKey = `${recoveryGame?.times?.casa || ""}|${recoveryGame?.times?.visitante || ""}|${recoveryGame?.data || ""}`;
    const matchedGame = jogosByKey.get(recoveryKey);
    const finalGame = matchedGame || recoveryGame;
    const finalTeams = getTeamNames(finalGame);

    if (finalTeams.casa !== "Casa" || finalTeams.visitante !== "Visitante") {
      recoveryTip = {
        ...rawRecovery,
        jogo: finalGame,
        palpite: rawRecovery?.palpite || {},
      };
    }
  }

  return {
    ...data,
    jogos,
    daily_tips_ids: Array.isArray(data?.daily_tips_ids) ? data.daily_tips_ids : [],
    recovery_tip: recoveryTip,
  };
}

function getTeamNames(match) {
  const times = match?.times || {};
  return {
    casa: times.casa || match?.casa || match?.mandante || "Casa",
    visitante: times.visitante || match?.visitante || match?.fora || "Visitante",
  };
}

function getTeamCrests(match) {
  const times = match?.times || {};
  return {
    casa: times.escudo_casa || match?.escudo_casa || match?.homeTeam?.crest || match?.home_team_crest || "",
    visitante: times.escudo_visitante || match?.escudo_visitante || match?.awayTeam?.crest || match?.away_team_crest || "",
  };
}

async function loadData() {
  try {
    const response = await fetch("predictions.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Não foi possível carregar predictions.json (HTTP ${response.status})`);
    }
    const rawData = await response.json();
    return normalizeFootballData(rawData);
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

  const acertosHoje = data.acertos_hoje;
  if (acertosHoje && acertosHoje.total > 0 && acertosHoje.taxa != null) {
    const elementoBadge = document.getElementById("acertosHoje");
    const elementoContador = document.getElementById("acertosHojeVal");
    if (elementoBadge && elementoContador) {
      elementoContador.textContent = `${acertosHoje.acertos}/${acertosHoje.total} (${formatarPorcentagem(acertosHoje.taxa)})`;
      elementoBadge.hidden = false;
    }
  }
}

async function fetchHistoryFile(path) {
  const resp = await fetch(`${path}?v=${Date.now()}`, { cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function mergeMercados(destino, origem) {
  const saida = { ...(destino || {}) };
  Object.entries(origem || {}).forEach(([tipo, estat]) => {
    const atual = saida[tipo] || { acertos: 0, total: 0 };
    const acertos = Number(atual.acertos || 0) + Number(estat?.acertos || 0);
    const total = Number(atual.total || 0) + Number(estat?.total || 0);
    saida[tipo] = {
      acertos,
      total,
      taxa: total > 0 ? acertos / total : 0,
    };
  });
  return saida;
}

function construirMercadosNba(jogos) {
  const mercados = {};
  (jogos || []).forEach((jogo) => {
    (jogo?.palpites || []).forEach((palpite) => {
      const resultado = palpite?.resultado;
      if (resultado !== "ACERTO" && resultado !== "ERRO") return;
      const tipo = palpite?.tipo || "OUTRO";
      const atual = mercados[tipo] || { acertos: 0, total: 0 };
      atual.total += 1;
      if (resultado === "ACERTO") atual.acertos += 1;
      mercados[tipo] = atual;
    });
  });

  Object.values(mercados).forEach((m) => {
    m.taxa = m.total > 0 ? m.acertos / m.total : 0;
  });

  return mercados;
}

function normalizarDiaNba(dia) {
  const jogos = (dia?.jogos || []).map((j) => ({
    ...j,
    competicao: "NBA",
    palpites: (j?.palpites || []).map((p) => ({
      tipo: p?.tipo,
      opcao: p?.opcao,
      confianca: p?.confianca,
      resultado: p?.resultado,
    })),
  }));

  const totalPalpites = Number(dia?.total_palpites || 0);
  const totalAcertos = Number(dia?.total_acertos || 0);

  return {
    data: dia?.data,
    ultima_atualizacao: dia?.ultima_atualizacao || null,
    finalizados: Number(dia?.finalizados ?? dia?.total_jogos ?? jogos.length),
    taxa_geral: totalPalpites > 0 ? totalAcertos / totalPalpites : 0,
    total_acertos: totalAcertos,
    total_palpites: totalPalpites,
    mercados: construirMercadosNba(jogos),
    metricas_probabilisticas: dia?.metricas_probabilisticas || {},
    jogos,
  };
}

function mergeHistoryDays(footballDays, nbaDays) {
  const porData = new Map();

  (footballDays || []).forEach((dia) => {
    if (!dia?.data) return;
    porData.set(dia.data, {
      ...dia,
      mercados: { ...(dia?.mercados || {}) },
      jogos: [...(dia?.jogos || [])],
    });
  });

  (nbaDays || []).forEach((diaNbaRaw) => {
    const diaNba = normalizarDiaNba(diaNbaRaw);
    if (!diaNba?.data) return;

    const atual = porData.get(diaNba.data);
    if (!atual) {
      porData.set(diaNba.data, diaNba);
      return;
    }

    const totalAcertos = Number(atual.total_acertos || 0) + Number(diaNba.total_acertos || 0);
    const totalPalpites = Number(atual.total_palpites || 0) + Number(diaNba.total_palpites || 0);

    porData.set(diaNba.data, {
      ...atual,
      finalizados: Number(atual.finalizados || 0) + Number(diaNba.finalizados || 0),
      total_acertos: totalAcertos,
      total_palpites: totalPalpites,
      taxa_geral: totalPalpites > 0 ? totalAcertos / totalPalpites : 0,
      mercados: mergeMercados(atual.mercados, diaNba.mercados),
      jogos: [...(atual.jogos || []), ...(diaNba.jogos || [])],
    });
  });

  return Array.from(porData.values())
    .sort((a, b) => String(b.data || "").localeCompare(String(a.data || "")))
    .slice(0, 5);
}

async function loadHistory() {
  const [footballResult, nbaResult] = await Promise.allSettled([
    fetchHistoryFile("history.json"),
    fetchHistoryFile("history_nba.json"),
  ]);

  if (footballResult.status !== "fulfilled" && nbaResult.status !== "fulfilled") {
    const footballErr = footballResult.status === "rejected" ? footballResult.reason?.message || "erro" : "ok";
    const nbaErr = nbaResult.status === "rejected" ? nbaResult.reason?.message || "erro" : "ok";
    throw new Error(`Não foi possível carregar histórico (futebol: ${footballErr}, NBA: ${nbaErr})`);
  }

  const footballDays = footballResult.status === "fulfilled" ? (footballResult.value?.dias || []) : [];
  const nbaDays = nbaResult.status === "fulfilled" ? (nbaResult.value?.dias || []) : [];

  return { dias: mergeHistoryDays(footballDays, nbaDays) };
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
      ? `${dia.total_acertos}/${dia.total_palpites} acertos · ${formatarPorcentagem(taxa)}`
      : "Sem resultados ainda";

    const mercadosHtml = Object.entries(dia.mercados || {})
      .map(([tipo, m]) => `
        <div class="admin-mercado">
          <span class="admin-mercado__nome">${tipo}</span>
          <span class="admin-mercado__stats">${m.acertos}/${m.total} · ${formatarPorcentagem(m.taxa)}</span>
        </div>`)
      .join("");

    const jogosHtml = (dia.jogos || []).map((j) => {
      const tips = j.palpites
        .map((p) => {
          const ok = p.resultado === "ACERTO";
          return `<span class="admin-tip admin-tip--${ok ? "ok" : "err"}">${p.tipo} ${p.opcao} <em>${p.confianca}</em></span>`;
        })
        .join("");
      const competicaoTag = j.competicao ? `<span class="admin-jogo__comp">${j.competicao}</span> ` : "";

      return `
        <div class="admin-jogo">
          <div class="admin-jogo__match">${competicaoTag}${j.casa} <span class="admin-placar">${j.placar}</span> ${j.visitante}</div>
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
  const list = document.getElementById("competitionSelectList");
  if (!list) return;
  const competitions = [...new Set((data.jogos || []).map((item) => item.competicao))].sort();
  competitions.forEach((name) => {
    const li = document.createElement("li");
    li.className = "custom-select__option";
    li.setAttribute("role", "option");
    li.setAttribute("data-value", name);
    li.setAttribute("tabindex", "-1");
    li.textContent = name;
    list.appendChild(li);
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
    { name: match?.times?.casa || "Casa", value: Number(match?.probabilidades?.casa) || 0 },
    { name: "Empate", value: Number(match?.probabilidades?.empate) || 0 },
    { name: match?.times?.visitante || "Visitante", value: Number(match?.probabilidades?.visitante) || 0 },
  ].sort((a, b) => b.value - a.value);

  const rankLevel = ["h", "m", "l"];

  rows.forEach((row, index) => {
    const level = rankLevel[index] || "l";
    const line = document.createElement("div");
    line.className = "prob-row";
    line.innerHTML = `
      <span class="prob-name">${row.name}</span>
      <strong class="prob-value">${formatarPorcentagem(row.value)}</strong>
      <div class="prob-track"><div class="prob-fill ${level}" style="width:${Math.max(0, Math.min(100, row.value * 100))}%"></div></div>
    `;
    container.appendChild(line);
  });
}

function getPrimaryTip(match) {
  const tips = match?.palpites || [];
  return tips.find((tip) => tip.valor_esperado_positivo === true) || tips[0] || null;
}

function parseOuOpcao(opcao) {
  const m = String(opcao || "").toUpperCase().match(/^(OVER|UNDER)(?:_(\d+(?:\.\d+)?))?$/);
  if (!m) return null;
  return { side: m[1], linha: m[2] ? Number(m[2]) : null };
}

function buildGoalsProbabilityLabel(match) {
  // Prefere usar o palpite OVER_UNDER real do modelo (ex: OVER_3.5)
  const ouTip = (match?.palpites || []).find((p) => p.tipo === "OVER_UNDER");
  if (ouTip) {
    const parsed = parseOuOpcao(ouTip.opcao);
    if (parsed) {
      const prob = Math.round((ouTip.probabilidade || 0) * 100);
      const linhaStr = parsed.linha !== null
        ? parsed.linha.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })
        : "2,5";
      const label = parsed.side === "OVER" ? `Mais de ${linhaStr}` : `Menos de ${linhaStr}`;
      return `${label} (${prob}%)`;
    }
  }

  // Fallback para over/under 2.5 do mercado
  const under = Number(match?.mercados?.under_25);
  const over = Number(match?.mercados?.over_25);

  if (!Number.isFinite(under) && !Number.isFinite(over)) {
    return "Dados indisponíveis";
  }

  if (!Number.isFinite(over) || (Number.isFinite(under) && under >= over)) {
    return `Menos de 2,5 (${formatarPorcentagem(under)})`;
  }

  return `Mais de 2,5 (${formatarPorcentagem(over)})`;
}

function buildCardSnapshot(match) {
  const primaryTip = getPrimaryTip(match);
  const probability = Math.round((primaryTip?.probabilidade || match?.favorito?.prob || 0) * 100);
  const bestBet = primaryTip
    ? translateTipOption(primaryTip.tipo, primaryTip.opcao, match)
    : "Sem sugestão disponível";
  const confidence = primaryTip ? confidenceLabel(primaryTip.confianca) : "Baixa";
  const confidenceTone = primaryTip ? confidenceClass(primaryTip.confianca) : "low";
  const goalsProbability = buildGoalsProbabilityLabel(match);

  return `
    <div class="card-snapshot-grid">
      <div class="snapshot-item">
        <span class="snapshot-label">Probabilidade da dica</span>
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

  // Análise Gemini IA
  const ia = match?.analise_ia;
  const primaryTip = getPrimaryTip(match);
  if (ia?.palpite_ia) {
    const iaEl = document.createElement("div");
    iaEl.className = "tip-analise-ia";
    const opcaoLabel = ia.palpite_ia === "1" ? "Casa" : ia.palpite_ia === "2" ? "Visitante" : "Empate";
    const confClass  = ia.confianca_ia === "alta" ? "ia-conf--alta" : ia.confianca_ia === "media" ? "ia-conf--media" : "ia-conf--baixa";
    iaEl.innerHTML = `
      <span class="ia-badge">✨ IA</span>
      <span class="ia-palpite">${opcaoLabel}</span>
      <span class="ia-conf ${confClass}">${ia.confianca_ia ?? ""}</span>
      ${ia.nota ? `<span class="ia-nota">${ia.nota}</span>` : ""}
    `;
    container.appendChild(iaEl);
  } else if (primaryTip) {
    const iaEl = document.createElement("div");
    iaEl.className = "tip-analise-ia tip-analise-ia--fallback";
    const opcaoLabel = translateTipOption(primaryTip.tipo, primaryTip.opcao, match);
    const confClass = primaryTip.confianca === "HIGH" ? "ia-conf--alta" : primaryTip.confianca === "MEDIUM" ? "ia-conf--media" : "ia-conf--baixa";
    const note = translateQuickRead(match?.leitura_rapida || buildSummaryNarrative(match));
    iaEl.innerHTML = `
      <span class="ia-badge">🤖 Modelo</span>
      <span class="ia-palpite">${opcaoLabel}</span>
      <span class="ia-conf ${confClass}">${confidenceLabel(primaryTip.confianca)}</span>
      ${note ? `<span class="ia-nota">${note}</span>` : ""}
    `;
    container.appendChild(iaEl);
  }

  const summaryBox = document.createElement("div");
  summaryBox.className = "tip-summary";
  summaryBox.textContent = buildSummaryNarrative(match);
  container.appendChild(summaryBox);

  const baseTips = tips || [];
  const coreMarketOrder = ["WINNER", "OVER_UNDER", "BTTS"];

  // Sempre exibir os 3 mercados principais (quando existirem),
  // mantendo ordem estável e sem ocultar mercados por filtro de EV.
  const coreTips = coreMarketOrder
    .map((marketType) => baseTips.find((tip) => tip.tipo === marketType))
    .filter(Boolean);

  const extraTips = baseTips.filter((tip) => !coreMarketOrder.includes(tip.tipo));
  const tipsToRender = [...coreTips, ...extraTips];

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
      const evPct = formatarPorcentagem(tip.ev || 0);
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

function getRecoveryTip(data, dailyGames) {
  const dailyKeys = new Set(dailyGames.map((g) => {
    const teams = getTeamNames(g);
    return `${teams.casa}|${teams.visitante}`;
  }));
  const confScore = { HIGH: 3, MEDIUM: 2, LOW: 1 };

  let best = null;
  let bestScore = -1;

  for (const game of data.jogos || []) {
    const teams = getTeamNames(game);
    if (game.status === "FINISHED") continue;
    if (dailyKeys.has(`${teams.casa}|${teams.visitante}`)) continue;
    if (COMPETICOES_EXCLUIDAS_DICAS.has(game.competicao)) continue;

    for (const tip of game.palpites || []) {
      const score = (confScore[tip.confianca] || 1) * 10 + (tip.probabilidade || 0);
      if (score > bestScore) {
        bestScore = score;
        best = { game, tip };
      }
    }
  }

  return best;
}

function renderRecoveryCard(container, recovery) {
  const game = recovery?.game || recovery?.jogo;
  const tip = recovery?.tip || recovery?.palpite;
  if (!game || !tip) return;
  const teams = getTeamNames(game);
  const escudos = getTeamCrests(game);
  const kickoffLabel = game?.data ? formatGeneratedAt(game.data, true) : "--";
  const triggerLabel = recovery?.disparado_em ? formatGeneratedAt(recovery.disparado_em, true) : "--";
  const prob = Math.round((tip.probabilidade || 0) * 100);
  const confidenceTone = confidenceClass(tip.confianca);
  const confidenceText = confidenceLabel(tip.confianca);
  const betLabel = translateTipOption(tip.tipo, tip.opcao, game);

  const resultadoRecovery = tip.resultado_verificador;
  let resultMarkRecovery = "";
  if (resultadoRecovery === "ACERTO") {
    resultMarkRecovery = '<span class="tip-card__result tip-card__result--acerto">✅ Acerto</span>';
  } else if (resultadoRecovery === "ERRO") {
    resultMarkRecovery = '<span class="tip-card__result tip-card__result--erro">❌ Errou</span>';
  }

  const card = document.createElement("article");
  card.className = "tip-card tip-card--recovery";
  card.innerHTML = `
    <div class="tip-card__top">
      <span class="tip-card__rank tip-card__rank--recovery">↩ Recuperação</span>
      <span class="tip-card__competition">${game.competicao}</span>
      <span class="conf ${confidenceTone} tip-card__conf">${confidenceText}</span>
    </div>
    <div class="tip-card__teams">${buildMatchTitleHtml(teams.casa, teams.visitante, "x", escudos.casa, escudos.visitante)}</div>
    <div class="tip-card__prob">
      <span class="tip-card__prob-value tip-card__prob-value--high">${prob}%</span>
      <span class="tip-card__prob-label">probabilidade</span>
    </div>
    <div class="tip-card__bet">
      <span class="tip-card__bet-label">Apostar em</span>
      <strong class="tip-card__bet-value">${betLabel}</strong>
    </div>
    <div class="tip-card__recovery-note">Sugestão mais conservadora para recuperar. Jogo: ${kickoffLabel} · Entrou: ${triggerLabel}</div>
    ${resultMarkRecovery}
  `;
  container.appendChild(card);
}

function renderTipsSection(data) {
  const container = document.getElementById("tipsCards");
  const badge = document.getElementById("tipsBadge");
  if (!container) return;

  // Usa dicas congeladas no início do dia, com fallback dinâmico
  let topDicas = [];
  if (data.daily_tips_ids && data.daily_tips_ids.length) {
    // New structure: daily_tips_ids contém tipo e opcao do palpite específico
    topDicas = data.daily_tips_ids
      .map((dica) => {
        const jogo = (data.jogos || []).find(
          (j) => j?.times?.casa === dica.casa && j?.times?.visitante === dica.visitante && j?.data === dica.data
        );
        if (!jogo) return null;
        
        // Se a dica tem tipo/opcao específicos, buscar esse palpite; senão pegar o principal
        let palpite = null;
        if (dica.tipo && dica.opcao) {
          palpite = (jogo.palpites || []).find((p) => p.tipo === dica.tipo && p.opcao === dica.opcao);
        }
        palpite = palpite || getPrimaryTip(jogo);
        
        return { jogo, palpite, dica };
      })
      .filter(Boolean);
  } else {
    const total = data.total_jogos ?? (data.jogos || []).length;
    const count = total >= LIMITE_JOGOS_TRES_DICAS ? 3 : total > LIMITE_JOGOS_DUAS_DICAS ? 2 : 1;
    topDicas = (data.jogos || [])
      .filter((j) => j.status !== "FINISHED" && !COMPETICOES_EXCLUIDAS_DICAS.has(j.competicao))
      .sort((a, b) => (b.favorito?.prob || 0) - (a.favorito?.prob || 0))
      .slice(0, count)
      .map((jogo) => ({ jogo, palpite: getPrimaryTip(jogo), dica: null }));
  }

  if (badge) {
    badge.textContent = `${topDicas.length} dica${topDicas.length !== 1 ? "s" : ""}`;
  }

  container.innerHTML = "";

  if (!topDicas.length) {
    container.innerHTML = '<p class="tips-section__empty">Sem jogos disponíveis para dicas no momento.</p>';
    return;
  }

  const hasError = topDicas[0]?.palpite?.resultado_verificador === "ERRO";

  topDicas.forEach(({ jogo, palpite }, index) => {
    const teams = getTeamNames(jogo);
    const crests = getTeamCrests(jogo);
    const prob = Math.round((palpite?.probabilidade || 0) * 100);
    const bestBet = palpite ? translateTipOption(palpite.tipo, palpite.opcao, jogo) : "—";
    const confidenceTone = palpite ? confidenceClass(palpite.confianca) : "low";
    const confidenceText = palpite ? confidenceLabel(palpite.confianca) : "Baixa";

    const probClass =
      prob >= PROB_VITORIA_ALTA * 100 ? "tip-card__prob-value--high"
      : prob >= PROB_VITORIA_MEDIA * 100 ? "tip-card__prob-value--mid"
      : "tip-card__prob-value--low";

    const resultado = palpite?.resultado_verificador;

    let resultMark = "";
    if (resultado === "ACERTO") {
      resultMark = '<span class="tip-card__result tip-card__result--acerto">✅ Acerto</span>';
    } else if (resultado === "ERRO") {
      resultMark = '<span class="tip-card__result tip-card__result--erro">❌ Errou</span>';
    }

    const card = document.createElement("article");
    card.className = "tip-card";
    card.innerHTML = `
      <div class="tip-card__top">
        <span class="tip-card__rank">#${index + 1}</span>
        <span class="tip-card__competition">${jogo.competicao}</span>
        <span class="conf ${confidenceTone} tip-card__conf">${confidenceText}</span>
      </div>
      <div class="tip-card__teams">${buildMatchTitleHtml(teams.casa, teams.visitante, "x", crests.casa, crests.visitante)}</div>
      <div class="tip-card__prob">
        <span class="tip-card__prob-value ${probClass}">${prob}%</span>
        <span class="tip-card__prob-label">${palpite?.tipo === "WINNER" ? "vitória" : translateTipType(palpite?.tipo || "")}: <strong>${palpite?.tipo === "WINNER" ? (jogo.favorito?.nome || "-") : translateTipOption(palpite?.tipo, palpite?.opcao, jogo)}</strong></span>
      </div>
      <div class="tip-card__bet">
        <span class="tip-card__bet-label">Apostar em</span>
        <strong class="tip-card__bet-value">${bestBet}</strong>
      </div>
      ${resultMark}
    `;
    container.appendChild(card);
  });

  const allCorrect = topDicas.length > 0 && topDicas.every(
    ({ palpite }) => palpite?.resultado_verificador === "ACERTO"
  );

  if (!allCorrect) {
    if (data?.recovery_tip?.ativo) {
      renderRecoveryCard(container, data.recovery_tip);
    } else if (hasError) {
      const recovery = getRecoveryTip(data, topDicas.map((d) => d.jogo));
      if (recovery) renderRecoveryCard(container, recovery);
    }
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function buildMatchTitleHtml(casa, visitante, vsLabel, escudoCasa, escudoVisitante) {
  const imgCasa = escudoCasa
    ? `<img class="team-crest" src="${escapeHtml(escudoCasa)}" alt="${escapeHtml(casa)}" onerror="this.style.display='none'">`
    : "";
  const imgVisitante = escudoVisitante
    ? `<img class="team-crest" src="${escapeHtml(escudoVisitante)}" alt="${escapeHtml(visitante)}" onerror="this.style.display='none'">`
    : "";
  return `<span class="match-teams"><span class="match-team match-team--home">${imgCasa}<span>${escapeHtml(casa)}</span></span><span class="match-vs">${escapeHtml(vsLabel)}</span><span class="match-team match-team--away"><span>${escapeHtml(visitante)}</span>${imgVisitante}</span></span>`;
}

function renderCards() {
  const container = document.getElementById("cardsContainer");
  const template = document.getElementById("matchCardTemplate");

  container.innerHTML = "";

  const filtered = (state.raw?.jogos || [])
    .filter(passesFilters)
    .map(normalizeFootballMatch)
    .sort((a, b) => new Date(a.data) - new Date(b.data));
  updateConfidenceHelp(filtered.length);

  if (!filtered.length) {
    container.innerHTML = '<div class="empty">Nenhum jogo atende aos filtros atuais.</div>';
    return;
  }

  filtered.forEach((match) => {
    const teams = getTeamNames(match);
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
    
    const escudos = getTeamCrests(match);
    let vsLabel = "x";
    if (match.status === "FINISHED" && match.placar_atual && match.placar_atual.casa !== null) {
      vsLabel = `${match.placar_atual.casa} x ${match.placar_atual.visitante}`;
    } else if (match.status === "IN_PLAY" || match.status === "PAUSED") {
      vsLabel = `${match.placar_atual?.casa ?? 0} x ${match.placar_atual?.visitante ?? 0}`;
    }
    node.querySelector(".match-title").innerHTML = buildMatchTitleHtml(teams.casa, teams.visitante, vsLabel, escudos.casa, escudos.visitante);

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
      `${match?.favorito?.nome || teams.casa} com maior probabilidade de vitória, com ${formatarPorcentagem(match?.favorito?.prob || 0)} de chance e margem estimada de ${formatarPorcentagem(match?.favorito?.vantagem || 0)}.`;
    node.querySelector(".quick-read").textContent = translateQuickRead(match.leitura_rapida);

    // Tendência de forma
    const formaRow = node.querySelector(".forma-row");
    const tendencia = match.tendencia || {};
    const formaLabel = { "em alta": "↗ em alta", "em baixa": "↘ em baixa", "estavel": "→ estável", "indefinida": null };
    const formaClass = { "em alta": "forma--alta", "em baixa": "forma--baixa", "estavel": "forma--estavel" };
    [[teams.casa, tendencia.casa], [teams.visitante, tendencia.visitante]].forEach(([nome, tend]) => {
      const label = formaLabel[tend];
      if (!label) return;
      const pill = document.createElement("span");
      pill.className = `forma-pill ${formaClass[tend] || ""}`;
      pill.textContent = `${nome} ${label}`;
      formaRow.appendChild(pill);
    });

    renderProbabilities(node.querySelector(".prob-bars"), match);

    const xgCasa = Number(match?.gols_esperados?.casa || 0).toLocaleString("pt-BR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    const xgFora = Number(match?.gols_esperados?.visitante || 0).toLocaleString("pt-BR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    const marketList = node.querySelector(".market-list");
    marketList.innerHTML = `
      <li class="market-xg"><span>Gols esperados (xG) por time</span><strong>${teams.casa}: ${xgCasa} | ${teams.visitante}: ${xgFora}</strong></li>
      <li><span>Menos de 2,5 gols</span><strong>${formatarPorcentagem(match?.mercados?.under_25 || 0)}</strong></li>
      <li><span>Mais de 2,5 gols</span><strong>${formatarPorcentagem(match?.mercados?.over_25 || 0)}</strong></li>
      <li><span>Ambas Marcam - Sim</span><strong>${formatarPorcentagem(match?.mercados?.btts_yes || 0)}</strong></li>
      <li><span>Ambas Marcam - Não</span><strong>${formatarPorcentagem(match?.mercados?.btts_no || 0)}</strong></li>
    `;

    renderHistory(node.querySelector(".home-history"), match?.historico?.casa || []);
    renderHistory(node.querySelector(".away-history"), match?.historico?.visitante || []);
    renderTips(node.querySelector(".tips"), match.palpites, match);

    container.appendChild(node);
  });
}

function setupFilters() {
  document.querySelectorAll(".filter-chip[data-confidence]").forEach((chip) => {
    chip.addEventListener("click", () => {
      state.minConfidence = chip.dataset.confidence || "LOW";
      renderCards();
    });
  });

  document.getElementById("clearFilters")?.addEventListener("click", () => {
    state.competition = "";
    state.minConfidence = "LOW";
    const wrapper = document.getElementById("competitionSelectWrapper");
    if (wrapper?._reset) wrapper._reset();
    renderCards();
  });
}

function setupCompetitionDropdown() {
  const wrapper = document.getElementById("competitionSelectWrapper");
  const btn     = document.getElementById("competitionSelectBtn");
  const list    = document.getElementById("competitionSelectList");
  const valueEl = document.getElementById("competitionSelectValue");
  if (!wrapper || !btn || !list || !valueEl) return;

  const openDropdown = () => {
    wrapper.classList.add("is-open");
    btn.setAttribute("aria-expanded", "true");
  };

  const closeDropdown = () => {
    wrapper.classList.remove("is-open");
    btn.setAttribute("aria-expanded", "false");
  };

  const selectOption = (value, label) => {
    state.competition = value;
    valueEl.textContent = label;
    list.querySelectorAll(".custom-select__option").forEach((opt) => {
      opt.classList.toggle("custom-select__option--active", opt.dataset.value === value);
    });
    closeDropdown();
    renderCards();
  };

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    wrapper.classList.contains("is-open") ? closeDropdown() : openDropdown();
  });

  list.addEventListener("click", (e) => {
    const opt = e.target.closest(".custom-select__option");
    if (!opt) return;
    selectOption(opt.dataset.value, opt.textContent.trim());
  });

  document.addEventListener("click", (e) => {
    if (!wrapper.contains(e.target)) closeDropdown();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && wrapper.classList.contains("is-open")) closeDropdown();
  });

  wrapper._reset = () => selectOption("", "Todas");
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;

  window.addEventListener("load", async () => {
    try {
      const registration = await navigator.serviceWorker.register("./service-worker.js?v=5");
      let isRefreshing = false;

      const requestSkipWaiting = () => {
        if (registration.waiting) {
          registration.waiting.postMessage({ type: "SKIP_WAITING" });
        }
      };

      navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (isRefreshing) return;
        isRefreshing = true;
        window.location.reload();
      });

      if (registration.waiting) {
        requestSkipWaiting();
      }

      registration.addEventListener("updatefound", () => {
        const newWorker = registration.installing;
        if (!newWorker) return;

        newWorker.addEventListener("statechange", () => {
          if (newWorker.state === "installed" && navigator.serviceWorker.controller) {
            requestSkipWaiting();
          }
        });
      });

      registration.update();

      // Revalida atualizações periodicamente para reduzir tempo de usuários em versão antiga.
      setInterval(() => {
        registration.update().catch(() => {});
      }, 30 * 60 * 1000);
    } catch (error) {
      console.warn("Falha ao registrar service worker:", error);
    }
  });
}

(async function init() {
  setupThemeToggle();
  setupMobileTopbar();
  initAdminPanel();
  registerServiceWorker();
  setupSportSelector();

  try {
    const data = await loadData();
    state.raw = data;
    fillHeader(data);
    fillCompetitionFilter(data);
    setupCompetitionDropdown();
    renderTipsSection(data);
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

function setupSportSelector() {
  const buttons = document.querySelectorAll(".sport-btn");
  if (!buttons.length) return;

  const footballSections = [
    document.getElementById("tipsSection"),
    document.querySelector("main"),
  ];
  const nbaSections = [
    document.getElementById("tipsSectionNba"),
    document.getElementById("nbaCardsContainer"),
  ];
  const comingSoon = document.getElementById("basketballComingSoon");

  const applySportView = (sport) => {
    state.sport = sport;
    const isFootball = sport === "football";

    footballSections.forEach((el) => { if (el) el.hidden = !isFootball; });
    nbaSections.forEach((el) => { if (el) el.hidden = isFootball; });
    if (comingSoon) comingSoon.hidden = true;

    buttons.forEach((b) => {
      const active = b.dataset.sport === sport;
      b.classList.toggle("sport-btn--active", active);
      b.setAttribute("aria-pressed", String(active));
    });

    if (!isFootball && state.rawNba === null) {
      const nbaContainer = document.getElementById("nbaCardsContainer");
      if (nbaContainer) nbaContainer.innerHTML = '<div class="empty">Carregando dados da NBA...</div>';

      loadNbaData()
        .then((data) => {
          state.rawNba = data;
          renderTipsSectionNba(data);
          renderCardsNba();
        })
        .catch((err) => {
          if (comingSoon) {
            comingSoon.hidden = false;
            nbaSections.forEach((el) => { if (el) el.hidden = true; });
          } else if (nbaContainer) {
            nbaContainer.innerHTML = `<div class="empty">Erro ao carregar NBA: ${err.message}</div>`;
          }
        });
    } else if (!isFootball && state.rawNba !== null) {
      renderCardsNba();
    }
  };

  const activeBtn = document.querySelector(".sport-btn.sport-btn--active") || buttons[0];
  applySportView(activeBtn?.dataset?.sport || "football");

  buttons.forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.classList.contains("sport-btn--active")));
    btn.addEventListener("click", () => applySportView(btn.dataset.sport || "football"));
  });
}

function statusDisplayNba(match) {
  const periodos = { 1: "1º Quarto", 2: "2º Quarto", 3: "3º Quarto", 4: "4º Quarto" };
  if (match.status === "IN_PLAY") {
    const p = periodos[match.periodo] || "Ao Vivo";
    const t = match.tempo ? ` — ${match.tempo}` : "";
    return `${p}${t}`;
  }
  if (match.status === "FINISHED") return "Final";
  return match.status_display || "Agendado";
}

function renderTipsSectionNba(data) {
  const container = document.getElementById("tipsCardsNba");
  const badge = document.getElementById("tipsBadgeNba");
  if (!container) return;

  let topDicas = [];
  if (data.daily_tips_ids && data.daily_tips_ids.length) {
    topDicas = data.daily_tips_ids
      .map((dica) => {
        const jogo = (data.jogos || []).find(
          (j) => j?.times?.casa === dica.casa && j?.times?.visitante === dica.visitante && j?.data === dica.data
        );
        if (!jogo) return null;
        
        let palpite = null;
        if (dica.tipo && dica.opcao) {
          palpite = (jogo.palpites || []).find((p) => p.tipo === dica.tipo && p.opcao === dica.opcao);
        }
        palpite = palpite || (jogo.palpites?.[0] || null);
        
        return { jogo, palpite };
      })
      .filter(Boolean);
  } else {
    topDicas = (data.jogos || [])
      .filter((j) => j.status !== "FINISHED")
      .sort((a, b) => (b.favorito?.prob || 0) - (a.favorito?.prob || 0))
      .slice(0, 3)
      .map((jogo) => ({ jogo, palpite: jogo.palpites?.[0] || null }));
  }

  if (badge) badge.textContent = `${topDicas.length} dica${topDicas.length !== 1 ? "s" : ""}`;

  container.innerHTML = "";
  if (!topDicas.length) {
    container.innerHTML = '<p class="tips-section__empty">Sem jogos NBA disponíveis para dicas.</p>';
    return;
  }

  topDicas.forEach(({ jogo, palpite }, index) => {
    const prob = Math.round((palpite?.probabilidade || jogo.favorito?.prob || 0) * 100);
    const bestBet = palpite ? translateTipOptionNba(palpite.tipo, palpite.opcao, jogo) : "—";
    const confidenceTone = palpite ? confidenceClass(palpite.confianca) : "low";
    const confidenceText = palpite ? confidenceLabel(palpite.confianca) : "Baixa";
    const probClass = prob >= 70 ? "tip-card__prob-value--high" : prob >= 55 ? "tip-card__prob-value--mid" : "tip-card__prob-value--low";
    const resultado = palpite?.resultado_verificador;

    const abrevCasa = jogo.times.abrev_casa || "";
    const abrevVisit = jogo.times.abrev_visit || "";
    const logoCasa = abrevCasa ? `https://a.espncdn.com/i/teamlogos/nba/500/${abrevCasa.toLowerCase()}.png` : "";
    const logoVisit = abrevVisit ? `https://a.espncdn.com/i/teamlogos/nba/500/${abrevVisit.toLowerCase()}.png` : "";
    const nomeCasa = jogo.times.casa || abrevCasa;
    const nomeVisit = jogo.times.visitante || abrevVisit;

    let resultMark = "";
    if (resultado === "ACERTO") {
      resultMark = '<span class="tip-card__result tip-card__result--acerto">✅ Acerto</span>';
    } else if (resultado === "ERRO") {
      resultMark = '<span class="tip-card__result tip-card__result--erro">❌ Errou</span>';
    }

    const card = document.createElement("article");
    card.className = "tip-card tip-card--nba";
    card.innerHTML = `
      <div class="tip-card__top">
        <span class="tip-card__rank">#${index + 1}</span>
        <span class="tip-card__competition">NBA</span>
        <span class="conf ${confidenceTone} tip-card__conf">${confidenceText}</span>
      </div>
      <div class="tip-card__teams">${buildMatchTitleHtml(nomeCasa, nomeVisit, "x", logoCasa, logoVisit)}</div>
      <div class="tip-card__prob">
        <span class="tip-card__prob-value ${probClass}">${prob}%</span>
        <span class="tip-card__prob-label">${palpite?.tipo === "WINNER" ? "vitória" : "probabilidade"} — <strong>${palpite?.tipo === "WINNER" ? (jogo.favorito?.nome || "—") : (palpite?.opcao || "—")}</strong></span>
      </div>
      <div class="tip-card__bet">
        <span class="tip-card__bet-label">Apostar em</span>
        <strong class="tip-card__bet-value">${bestBet}</strong>
      </div>
      ${resultMark}
    `;
    container.appendChild(card);
  });

  const hasErrorNba = topDicas[0]?.palpite?.resultado_verificador === "ERRO";
  const allCorrectNba = topDicas.length > 0 && topDicas.every(
    ({ palpite }) => palpite?.resultado_verificador === "ACERTO"
  );
  if (!allCorrectNba && data?.recovery_tip?.ativo) {
    renderRecoveryCardNba(container, data.recovery_tip);
  } else if (!allCorrectNba && hasErrorNba) {
    const ids = new Set(topDicas.map(({ jogo }) => `${jogo?.times?.casa}|${jogo?.times?.visitante}`));
    const fallback = (data.jogos || [])
      .filter((j) => j.status !== "FINISHED" && !ids.has(`${j?.times?.casa}|${j?.times?.visitante}`))
      .sort((a, b) => (b.favorito?.prob || 0) - (a.favorito?.prob || 0))[0];
    if (fallback) {
      const p = fallback.palpites?.[0];
      if (p) {
        const abrevC = fallback.times?.abrev_casa || "";
        const abrevV = fallback.times?.abrev_visit || "";
        const fakeRt = {
          ativo: true,
          disparado_em: null,
          jogo: {
            ...fallback,
            competicao: "NBA",
            times: {
              ...fallback.times,
              escudo_casa: abrevC ? `https://a.espncdn.com/i/teamlogos/nba/500/${abrevC.toLowerCase()}.png` : "",
              escudo_visitante: abrevV ? `https://a.espncdn.com/i/teamlogos/nba/500/${abrevV.toLowerCase()}.png` : "",
            },
          },
          palpite: p,
        };
        renderRecoveryCardNba(container, fakeRt);
      }
    }
  }
}

function renderRecoveryCardNba(container, recovery) {
  const game = recovery?.game || recovery?.jogo;
  const tip = recovery?.tip || recovery?.palpite;
  if (!game || !tip) return;
  const teams = getTeamNames(game);
  const escudos = getTeamCrests(game);
  const kickoffLabel = game?.data ? formatGeneratedAt(game.data, true) : "--";
  const triggerLabel = recovery?.disparado_em ? formatGeneratedAt(recovery.disparado_em, true) : "--";
  const prob = Math.round((tip.probabilidade || 0) * 100);
  const confidenceTone = confidenceClass(tip.confianca);
  const confidenceText = confidenceLabel(tip.confianca);
  const betLabel = translateTipOptionNba(tip.tipo, tip.opcao, game);

  const resultadoNba = tip.resultado_verificador;
  let resultMarkNba = "";
  if (resultadoNba === "ACERTO") {
    resultMarkNba = '<span class="tip-card__result tip-card__result--acerto">✅ Acerto</span>';
  } else if (resultadoNba === "ERRO") {
    resultMarkNba = '<span class="tip-card__result tip-card__result--erro">❌ Errou</span>';
  }

  const card = document.createElement("article");
  card.className = "tip-card tip-card--recovery tip-card--nba";
  card.innerHTML = `
    <div class="tip-card__top">
      <span class="tip-card__rank tip-card__rank--recovery">↩ Recuperação</span>
      <span class="tip-card__competition">NBA</span>
      <span class="conf ${confidenceTone} tip-card__conf">${confidenceText}</span>
    </div>
    <div class="tip-card__teams">${buildMatchTitleHtml(teams.casa, teams.visitante, "x", escudos.casa, escudos.visitante)}</div>
    <div class="tip-card__prob">
      <span class="tip-card__prob-value tip-card__prob-value--high">${prob}%</span>
      <span class="tip-card__prob-label">probabilidade</span>
    </div>
    <div class="tip-card__bet">
      <span class="tip-card__bet-label">Apostar em</span>
      <strong class="tip-card__bet-value">${betLabel}</strong>
    </div>
    <div class="tip-card__recovery-note">Sugestão de recuperação NBA. Jogo: ${kickoffLabel}${recovery?.disparado_em ? ` · Entrou: ${triggerLabel}` : ""}</div>
    ${resultMarkNba}
  `;
  container.appendChild(card);
}

function renderCardsNba() {
  const container = document.getElementById("nbaCardsContainer");
  if (!container) return;
  container.innerHTML = "";

  const jogos = (state.rawNba?.jogos || []);
  if (!jogos.length) {
    container.innerHTML = '<div class="empty">Nenhum jogo NBA hoje.</div>';
    return;
  }

  jogos.forEach((match) => {
    const card = document.createElement("article");
    card.className = "card card--nba is-collapsed";
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-expanded", "false");

    // Logos dos times via ESPN CDN
    const abrevCasa = match.times.abrev_casa || "";
    const abrevVisit = match.times.abrev_visit || "";
    const logoCasa = abrevCasa ? `https://a.espncdn.com/i/teamlogos/nba/500/${abrevCasa.toLowerCase()}.png` : "";
    const logoVisit = abrevVisit ? `https://a.espncdn.com/i/teamlogos/nba/500/${abrevVisit.toLowerCase()}.png` : "";

    // Título com placar se disponível
    let vsLabel = "x";
    let nomeCasa = match.times.casa || abrevCasa;
    let nomeVisit = match.times.visitante || abrevVisit;
    if (match.status === "FINISHED" && match.placar_casa !== null) {
      vsLabel = `${match.placar_casa} x ${match.placar_visitante}`;
    } else if (match.status === "IN_PLAY") {
      vsLabel = `${match.placar_casa ?? 0} x ${match.placar_visitante ?? 0}`;
    }
    const titulo = buildMatchTitleHtml(nomeCasa, nomeVisit, vsLabel, logoCasa, logoVisit);

    // Badge de status
    let badgeHtml = "";
    if (match.status === "FINISHED") {
      badgeHtml = '<span class="card-status-badge card-status-badge--finished">Final</span>';
    } else if (match.status === "IN_PLAY") {
      badgeHtml = `<span class="card-status-badge card-status-badge--live">${statusDisplayNba(match)}</span>`;
    }

    // Quarters
    let quartersHtml = "";
    const qc = match.quarters?.casa || [];
    const qv = match.quarters?.visitante || [];
    const temQuarters = qc.some((q) => q !== null && q !== undefined);
    if (temQuarters) {
      const qLabels = ["Q1", "Q2", "Q3", "Q4"];
      const qHeaders = qLabels.map((q) => `<th>${q}</th>`).join("");
      const qCasa = qLabels.map((_, i) => `<td>${qc[i] ?? "—"}</td>`).join("");
      const qVisit = qLabels.map((_, i) => `<td>${qv[i] ?? "—"}</td>`).join("");
      quartersHtml = `
        <div class="nba-quarters">
          <table class="quarters-table">
            <thead><tr><th>Time</th>${qHeaders}<th>Total</th></tr></thead>
            <tbody>
              <tr><td class="qt-team">${match.times.abrev_casa}</td>${qCasa}<td class="qt-total">${match.placar_casa ?? "—"}</td></tr>
              <tr><td class="qt-team">${match.times.abrev_visit}</td>${qVisit}<td class="qt-total">${match.placar_visitante ?? "—"}</td></tr>
            </tbody>
          </table>
        </div>`;
    }

    // Probabilidades
    const probCasaPct = Math.round((match.probabilidades?.casa || 0) * 100);
    const probVisitPct = Math.round((match.probabilidades?.visitante || 0) * 100);

    // Mercados
    const totalEsp = match.pts_esperados?.total || 0;
    const overLinha = match.mercados?.over_linha || "";
    const probOver = Math.round((match.mercados?.prob_over || 0) * 100);
    const probUnder = 100 - probOver;
    const spreadDisplay = match.spread_esperado >= 0
      ? `${match.times.abrev_casa} -${Math.abs(match.spread_esperado)}`
      : `${match.times.abrev_visit} -${Math.abs(match.spread_esperado)}`;

    // Forma
    const formaCasaPct = Math.round((match.forma?.casa || 0.5) * 100);
    const formaVisitPct = Math.round((match.forma?.visitante || 0.5) * 100);

    // Palpites
    let tipsHtml = "";
    (match.palpites || []).forEach((tip) => {
      let resultMark = "";
      if (tip.resultado_verificador === "ACERTO") resultMark = '<span class="tip-mark tip-mark--acerto">✅ Acerto</span>';
      if (tip.resultado_verificador === "ERRO") resultMark = '<span class="tip-mark tip-mark--erro">❌ Erro</span>';
      const opcaoLabel = translateTipOptionNba(tip.tipo, tip.opcao, match);
      tipsHtml += `
        <div class="tip">
          <div class="tag">${translateTipTypeNba(tip.tipo)}</div>
          <div class="conf ${confidenceClass(tip.confianca)}">${confidenceLabel(tip.confianca)}</div>
          <div class="tip-desc"><strong>${opcaoLabel}</strong>. <span class="tip-just">${tip.justificativa || ""}</span>${resultMark}</div>
        </div>`;
    });

    card.innerHTML = `
      <div class="card-head">
        <div class="card-head-top">
          <div class="card-meta"><p class="competition">NBA</p></div>
          <div class="card-badges">${badgeHtml}</div>
        </div>
        <h2 class="match-title">${titulo}</h2>
      </div>
      <div class="card-snapshot">
        <div class="card-snapshot-grid">
          <div class="snapshot-item">
            <span class="snapshot-label">Probabilidade</span>
            <strong class="highlight">${Math.round(match.favorito?.prob * 100 || 0)}%</strong>
          </div>
          <div class="snapshot-item snapshot-item--wide">
            <span class="snapshot-label">Favorito</span>
            <strong class="highlight highlight--secondary">${match.favorito?.nome || "—"}</strong>
          </div>
          <div class="snapshot-item">
            <span class="snapshot-label">Spread</span>
            <strong class="highlight highlight--secondary">${spreadDisplay}</strong>
          </div>
          <div class="snapshot-item">
            <span class="snapshot-label">Total esperado</span>
            <strong class="highlight highlight--secondary">${totalEsp} pts</strong>
          </div>
        </div>
      </div>
      <div class="card-body">
        <div class="card-body-inner">
          <div class="grid-2 grid-2--stacked">
            <section class="panel emphasis">
              <h3>Favorito</h3>
              <p class="favorite-line">${match.leitura_rapida || ""}</p>
              <div class="prob-bars">
                <div class="prob-row">
                  <span class="prob-name">${match.times.casa}</span>
                  <strong class="prob-value">${probCasaPct}%</strong>
                  <div class="prob-track"><div class="prob-fill h" style="width:${probCasaPct}%"></div></div>
                </div>
                <div class="prob-row">
                  <span class="prob-name">${match.times.visitante}</span>
                  <strong class="prob-value">${probVisitPct}%</strong>
                  <div class="prob-track"><div class="prob-fill l" style="width:${probVisitPct}%"></div></div>
                </div>
              </div>
            </section>
            <section class="panel">
              <h3>Mercados</h3>
              <ul class="market-list">
                <li class="market-xg"><span>Pontos esperados (casa)</span><strong>${match.pts_esperados?.casa || "—"}</strong></li>
                <li class="market-xg"><span>Pontos esperados (visit.)</span><strong>${match.pts_esperados?.visitante || "—"}</strong></li>
                <li><span>Over ${overLinha}</span><strong>${probOver}%</strong></li>
                <li><span>Under ${overLinha}</span><strong>${probUnder}%</strong></li>
                <li><span>Spread esperado</span><strong>${spreadDisplay}</strong></li>
              </ul>
            </section>
          </div>
          ${quartersHtml}
          <div class="grid-2">
            <section class="panel">
              <h3>Forma recente — Casa</h3>
              <p class="nba-forma">${match.times.casa}: <strong>${formaCasaPct}%</strong> de vitórias recentes</p>
            </section>
            <section class="panel">
              <h3>Forma recente — Visitante</h3>
              <p class="nba-forma">${match.times.visitante}: <strong>${formaVisitPct}%</strong> de vitórias recentes</p>
            </section>
          </div>
          <section class="panel">
            <h3>Sugestões do modelo</h3>
            <div class="tips">${tipsHtml}</div>
          </section>
        </div>
      </div>
    `;

    bindCardToggle(card);
    container.appendChild(card);
  });
}
