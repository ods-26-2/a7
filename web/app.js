/**
 * Lexie — Cliente Reativo WebSocket & Controlador de Interface por Voz (UI/UX B6 - ODS A7)
 *
 * - Escuta passivamente o WebSocket `/ws/sessao` para refletir instantaneamente
 *   as transcrições vindas do componente I5 e a máquina de estados da jornada (A7).
 * - Interface principal 100% orientada a voz e resposta em texto (sem botões na tela).
 * - Painel oculto de simulação/avaliação acessível via tecla 'D' ou 'F2' (e atalhos 1 a 9).
 */

(() => {
  "use strict";

  // ---------------------------------------------------------------------------
  // Extrai a origem da URL (?origem=mesa_01 ou ?mesa=01)
  // ---------------------------------------------------------------------------
  const urlParams = new URLSearchParams(window.location.search);
  const origemInicial = urlParams.get("origem") || urlParams.get("mesa") || "mesa_05";

  // ---------------------------------------------------------------------------
  // Estado Local da Aplicação
  // ---------------------------------------------------------------------------
  const state = {
    ws: null,
    wsConnected: false,
    origemAtiva: origemInicial,
    lastSendTimestamp: 0,
    lastKnownCart: { itens: [], total: 0.0 },
    currentSessionState: "IDLE", // IDLE | ACTIVE | PENDING | CONFIRMADO | COMPLETED
  };

  // ---------------------------------------------------------------------------
  // Referências DOM
  // ---------------------------------------------------------------------------
  const dom = {
    bgGlow: document.getElementById("bg-glow"),
    wsDot: document.getElementById("ws-dot"),
    wsLabel: document.getElementById("ws-label"),
    globalStateBadge: document.getElementById("global-state-badge"),

    views: {
      welcome: document.getElementById("view-welcome"),
      listening: document.getElementById("view-listening"),
      orderOpen: document.getElementById("view-order-open"),
      orderClosed: document.getElementById("view-order-closed"),
    },

    // Tela 2: Ouvindo
    listeningUserMsg: document.getElementById("listening-user-msg"),
    listeningLexieMsg: document.getElementById("listening-lexie-msg"),

    // Tela 3: Pedido Aberto
    orbOrder: document.getElementById("orb-order"),
    orderVoiceHeadline: document.getElementById("order-voice-headline"),
    orderVoiceSubheadline: document.getElementById("order-voice-subheadline"),
    pendingAlertBanner: document.getElementById("pending-alert-banner"),
    pendingAlertReason: document.getElementById("pending-alert-reason"),

    orderDot1: document.getElementById("order-dot-1"),
    orderSpeaker1: document.getElementById("order-speaker-1"),
    orderMsg1: document.getElementById("order-msg-1"),
    orderDot2: document.getElementById("order-dot-2"),
    orderSpeaker2: document.getElementById("order-speaker-2"),
    orderMsg2: document.getElementById("order-msg-2"),

    comandaOpenLabel: document.getElementById("comanda-open-label"),
    comandaOpenBadge: document.getElementById("comanda-open-badge"),
    comandaOpenCard: document.getElementById("comanda-open-card"),
    comandaOpenItems: document.getElementById("comanda-open-items"),
    comandaOpenTotal: document.getElementById("comanda-open-total"),

    // Tela 4: Pedido Finalizado
    comandaClosedLabel: document.getElementById("comanda-closed-label"),
    comandaClosedBadge: document.getElementById("comanda-closed-badge"),
    comandaClosedItems: document.getElementById("comanda-closed-items"),
    comandaClosedTotal: document.getElementById("comanda-closed-total"),

    // Drawer Oculto (Modo Avaliação)
    devDrawer: document.getElementById("dev-drawer"),
    devCloseBtn: document.getElementById("dev-close-btn"),
    devOrigemInput: document.getElementById("dev-origem-input"),
    devLatencyTag: document.getElementById("dev-latency-tag"),
    devI5Files: document.getElementById("dev-i5-files"),
    devVoiceText: document.getElementById("dev-voice-text"),
    devVoiceConf: document.getElementById("dev-voice-conf"),
    devSendVoiceBtn: document.getElementById("dev-send-voice-btn"),

    restBtnConfirmar: document.getElementById("rest-btn-confirmar"),
    restBtnCancelar: document.getElementById("rest-btn-cancelar"),
    restBtnEditar: document.getElementById("rest-btn-editar"),
    restBtnResetar: document.getElementById("rest-btn-resetar"),
  };

  // ---------------------------------------------------------------------------
  // Utilitários de Formatação
  // ---------------------------------------------------------------------------
  function formatCurrency(val) {
    const num = Number(val || 0);
    return "R$" + num.toFixed(2).replace(".", ",");
  }

  function formatOrigemDisplay(origem) {
    if (!origem) return "MESA 05";
    const clean = String(origem)
      .replace(/^mic_/i, "")
      .replace(/_/g, " ")
      .trim()
      .toUpperCase();
    if (clean === "DEFAULT") return "MESA 05";
    if (/^MESA\s+\d$/i.test(clean)) {
      const parts = clean.split(/\s+/);
      return `MESA 0${parts[1]}`;
    }
    return clean;
  }

  function switchScreen(screenKey) {
    Object.entries(dom.views).forEach(([key, el]) => {
      if (!el) return;
      if (key === screenKey) {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    });
  }

  function setBadgeStyle(badgeEl, estado, labelOverride) {
    if (!badgeEl) return;
    badgeEl.classList.remove("badge-idle", "badge-active", "badge-pending", "badge-confirmed");
    if (estado === "PENDING") {
      badgeEl.classList.add("badge-pending");
      badgeEl.textContent = labelOverride || "PENDING • ALERTA";
    } else if (estado === "CONFIRMADO" || estado === "CONFIRMED" || estado === "COMPLETED") {
      badgeEl.classList.add("badge-confirmed");
      badgeEl.textContent = labelOverride || estado;
    } else if (estado === "ACTIVE") {
      badgeEl.classList.add("badge-active");
      badgeEl.textContent = labelOverride || "ACTIVE";
    } else {
      badgeEl.classList.add("badge-idle");
      badgeEl.textContent = labelOverride || "AGUARDANDO VOZ";
    }
  }

  function setDialogueBox(row1Speaker, row1Text, row2Speaker, row2Text) {
    const isRow1Lexie = row1Speaker === "Lexie";
    dom.orderDot1.className = `dialogue-dot ${isRow1Lexie ? "dot-lexie" : "dot-user"}`;
    dom.orderSpeaker1.className = isRow1Lexie ? "speaker-lexie" : "speaker-user";
    dom.orderSpeaker1.textContent = `${row1Speaker}:`;
    dom.orderMsg1.textContent = row1Text;

    const isRow2Lexie = row2Speaker === "Lexie";
    dom.orderDot2.className = `dialogue-dot ${isRow2Lexie ? "dot-lexie" : "dot-user"}`;
    dom.orderSpeaker2.className = isRow2Lexie ? "speaker-lexie" : "speaker-user";
    dom.orderSpeaker2.textContent = `${row2Speaker}:`;
    dom.orderMsg2.textContent = row2Text;
  }

  function renderComandaItems(containerEl, totalEl, cart) {
    if (!containerEl || !totalEl) return;
    const itens = (cart && Array.isArray(cart.itens)) ? cart.itens : [];
    const total = (cart && typeof cart.total === "number") ? cart.total : 0.0;

    totalEl.textContent = formatCurrency(total);

    if (itens.length === 0) {
      containerEl.innerHTML = `<div class="comanda-empty-msg">Nenhum item adicionado até o momento.</div>`;
      return;
    }

    containerEl.innerHTML = itens
      .map((item) => {
        const qtd = item.quantidade || 1;
        const nome = item.nome || `Produto #${item.produto_id}`;
        const subtotal = typeof item.subtotal === "number" ? item.subtotal : qtd * (item.preco_unitario || 0);
        const variacoes = Array.isArray(item.variacoes) ? item.variacoes : [];

        const variacoesHtml =
          variacoes.length > 0
            ? `<div class="comanda-item-variations">
                ${variacoes.map((v) => `<span class="variation-chip">${v}</span>`).join("")}
               </div>`
            : "";

        return `
          <div class="comanda-item-row" data-produto-id="${item.produto_id || ""}">
            <div class="comanda-item-main">
              <div class="comanda-item-left">
                <span class="comanda-item-qty">${qtd}x</span>
                <span class="comanda-item-name">${nome}</span>
              </div>
              <span class="comanda-item-price">${formatCurrency(subtotal)}</span>
            </div>
            ${variacoesHtml}
          </div>
        `;
      })
      .join("");
  }

  function buildFriendlyLexieReply(payload, cart) {
    const estado = payload.estado || "ACTIVE";
    const intencao = payload.intencao || "";
    const msgBackend = payload.mensagem || "";
    const origemFmt = formatOrigemDisplay(payload.origem || state.origemAtiva).toLowerCase();

    if (estado === "PENDING") {
      return payload.pending_reason || msgBackend || "Não consegui compreender com segurança. Pode repetir seu pedido?";
    }
    if (intencao === "INICIAR_PEDIDO") {
      return `Pedido aberto para ${origemFmt}`;
    }
    if (intencao === "ADICIONAR_ITEM") {
      if (msgBackend && msgBackend.startsWith("Item")) {
        return `Ok! ${msgBackend}`;
      }
      return "Ok!";
    }
    if (intencao === "CONFIRMAR_PEDIDO" || intencao === "PEDIR_CONTA" || estado === "CONFIRMADO") {
      return msgBackend || `Pedido confirmado! Total: ${formatCurrency(cart.total)}.`;
    }
    return msgBackend || "Ok! Estou ouvindo você.";
  }

  // ---------------------------------------------------------------------------
  // Atualização Reativa do DOM ao Receber Eventos do WebSocket
  // ---------------------------------------------------------------------------
  function handleSessionUpdate(payload) {
    if (!payload || payload.tipo === "conectado") return;

    if (state.lastSendTimestamp > 0) {
      const elapsed = Math.round(performance.now() - state.lastSendTimestamp);
      if (dom.devLatencyTag) {
        dom.devLatencyTag.textContent = `Latência WS: ${elapsed} ms`;
      }
      state.lastSendTimestamp = 0;
    }

    // Atualiza apenas se o evento for destinado a esta origem ou se não houver filtro restrito
    if (payload.origem && payload.origem !== state.origemAtiva) {
      console.log(`[WS] Ignorando evento da origem '${payload.origem}' pois esta aba monitora '${state.origemAtiva}'`);
      return;
    }

    if (payload.origem) {
      state.origemAtiva = payload.origem;
      if (dom.devOrigemInput && document.activeElement !== dom.devOrigemInput) {
        dom.devOrigemInput.value = payload.origem;
      }
    }

    const estado = payload.estado || "ACTIVE";
    state.currentSessionState = estado;

    // Preserva o último carrinho conhecido caso o evento PENDING retorne carrinho: null
    if (payload.carrinho && Array.isArray(payload.carrinho.itens)) {
      state.lastKnownCart = payload.carrinho;
    }
    const cart = state.lastKnownCart || { itens: [], total: 0.0 };
    const hasItems = cart.itens && cart.itens.length > 0;
    const origemLabel = formatOrigemDisplay(state.origemAtiva);

    // Atualiza badge global no topo
    setBadgeStyle(dom.globalStateBadge, estado);

    // Destaque visual de estado PENDING (RF07: dúvida explícita do I5 ou item indisponível)
    const isPending = estado === "PENDING";
    dom.bgGlow.classList.toggle("glow-pending", isPending);
    dom.orbOrder.classList.toggle("orb-pending", isPending);
    dom.comandaOpenCard.classList.toggle("card-pending", isPending);

    if (isPending) {
      const motivo =
        payload.pending_reason ||
        payload.mensagem ||
        "Confiança baixa na transcrição do I5 ou produto indisponível no catálogo.";
      dom.pendingAlertReason.textContent = motivo;
      dom.pendingAlertBanner.classList.remove("hidden");
      dom.orderVoiceHeadline.textContent = "Atenção: Dúvida Explícita";
      dom.orderVoiceSubheadline.textContent = "Por favor, repita ou escolha outro produto por voz";
    } else {
      dom.pendingAlertBanner.classList.add("hidden");
      dom.orderVoiceHeadline.textContent = "Estou ouvindo você";
      dom.orderVoiceSubheadline.textContent = "Pode falar naturalmente";
    }

    const textoUsuario = payload.texto_usuario || "Comando de voz recebido";
    const respostaLexie = buildFriendlyLexieReply(payload, cart);

    // 1. Sessão finalizada / confirmada -> Tela 4 (Pedido Finalizado!)
    if (estado === "CONFIRMADO" || estado === "CONFIRMED" || estado === "COMPLETED") {
      dom.comandaClosedLabel.textContent = `${origemLabel} - COMANDA FECHADA`;
      setBadgeStyle(dom.comandaClosedBadge, estado, "CONFIRMADO");
      renderComandaItems(dom.comandaClosedItems, dom.comandaClosedTotal, cart);
      switchScreen("orderClosed");
      return;
    }

    // 2. Sessão recém-aberta sem itens e sem alerta PENDING -> Tela 2 (Estou ouvindo você)
    if (!hasItems && !isPending) {
      dom.listeningUserMsg.textContent = textoUsuario;
      dom.listeningLexieMsg.textContent = respostaLexie;
      switchScreen("listening");
      return;
    }

    // 3. Pedido aberto com itens ou em alerta PENDING -> Tela 3 (Split View: Orbe + Comanda)
    dom.comandaOpenLabel.textContent = `${origemLabel} - COMANDA ABERTA`;
    setBadgeStyle(dom.comandaOpenBadge, estado, estado);
    renderComandaItems(dom.comandaOpenItems, dom.comandaOpenTotal, cart);

    if (payload.dialogo_custom) {
      setDialogueBox(
        payload.dialogo_custom.s1,
        payload.dialogo_custom.t1,
        payload.dialogo_custom.s2,
        payload.dialogo_custom.t2
      );
    } else {
      setDialogueBox("Você", textoUsuario, "Lexie", respostaLexie);
    }

    switchScreen("orderOpen");
  }

  // ---------------------------------------------------------------------------
  // Conexão WebSocket (/ws/sessao)
  // ---------------------------------------------------------------------------
  function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/sessao?origem=${encodeURIComponent(state.origemAtiva)}`;

    try {
      const ws = new WebSocket(wsUrl);
      state.ws = ws;

      ws.onopen = () => {
        state.wsConnected = true;
        dom.wsDot.classList.add("connected");
        dom.wsLabel.textContent = `WS ATIVO (${state.origemAtiva})`;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleSessionUpdate(data);
        } catch (err) {
          console.error("Erro ao processar payload WS:", err);
        }
      };

      ws.onclose = () => {
        state.wsConnected = false;
        dom.wsDot.classList.remove("connected");
        dom.wsLabel.textContent = "WS RECONECTANDO...";
        setTimeout(connectWebSocket, 1500);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch (err) {
      console.error("Falha ao abrir WebSocket:", err);
      setTimeout(connectWebSocket, 2000);
    }
  }

  // ---------------------------------------------------------------------------
  // Envio de Eventos de Voz (I5) e Chamadas REST Mapeadas
  // ---------------------------------------------------------------------------
  async function sendVoiceEvent(textoTranscrito, confiancaGeral = 0.95, origemOverride = null) {
    const origem = origemOverride || (dom.devOrigemInput && dom.devOrigemInput.value.trim()) || state.origemAtiva;
    state.origemAtiva = origem;
    state.lastSendTimestamp = performance.now();

    const envelopeI5 = {
      message_type: "event",
      schema: "ods.varejo.transcricao",
      schema_version: "1.0",
      producer: "I5",
      published_at: new Date().toISOString(),
      payload: {
        origem,
        texto_transcrito: textoTranscrito,
        confianca_geral: Number(confiancaGeral),
        duvida_explicita: Number(confiancaGeral) < 0.5,
      },
    };

    if (state.ws && state.wsConnected && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(envelopeI5));
      return;
    }

    await fetch("/eventos/voz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(envelopeI5),
    });
  }

  async function callRestAction(endpointSuffix, method = "POST", bodyObj = null) {
    const origem = (dom.devOrigemInput && dom.devOrigemInput.value.trim()) || state.origemAtiva;
    state.lastSendTimestamp = performance.now();
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (bodyObj) {
      opts.body = JSON.stringify(bodyObj);
    }
    const resp = await fetch(`/sessoes/${encodeURIComponent(origem)}${endpointSuffix}`, opts);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      console.warn("Aviso REST:", err.detail || resp.statusText);
    }
  }

  // ---------------------------------------------------------------------------
  // Cenas de Demonstração (Telas 1 a 6 das imagens de inspiração + Casos B6)
  // ---------------------------------------------------------------------------
  async function triggerScene(sceneNum) {
    const origem = (dom.devOrigemInput && dom.devOrigemInput.value.trim()) || "mesa_05";
    state.origemAtiva = origem;

    switch (String(sceneNum)) {
      case "1":
        // Tela Início (Bem vindo(a)!)
        await callRestAction("/reset", "POST");
        state.lastKnownCart = { itens: [], total: 0.0 };
        setBadgeStyle(dom.globalStateBadge, "IDLE", "AGUARDANDO VOZ");
        dom.bgGlow.classList.remove("glow-pending");
        switchScreen("welcome");
        break;

      case "2":
        // Tela Início-1.png: Você: "Fazer pedido" -> Lexie: "Pedido aberto para mesa 05"
        await callRestAction("/reset", "POST");
        state.lastKnownCart = { itens: [], total: 0.0 };
        await sendVoiceEvent("Fazer pedido", 0.98, origem);
        break;

      case "3":
        // Pedido aberto.png: "Gostaria de dois X-Bacon e um suco de laranja." -> 2x X-Bacon + 1x Suco
        await callRestAction("/reset", "POST");
        state.lastKnownCart = { itens: [], total: 0.0 };
        await sendVoiceEvent("Gostaria de dois X-Bacon e um suco de laranja.", 0.96, origem);
        setTimeout(() => {
          setDialogueBox(
            "Você",
            "Gostaria de dois X-Bacon e um suco de laranja.",
            "Lexie",
            "Ok!"
          );
        }, 80);
        break;

      case "4":
        // Pedido aberto-1.png: Lexie: "Posso enviar para a cozinha?" / Você: "Sim!"
        if (!state.lastKnownCart.itens || state.lastKnownCart.itens.length === 0) {
          await sendVoiceEvent("Gostaria de dois X-Bacon e um suco de laranja.", 0.96, origem);
        }
        setTimeout(() => {
          switchScreen("orderOpen");
          setDialogueBox("Lexie", "Posso enviar para a cozinha?", "Você", "Sim!");
        }, 90);
        break;

      case "5":
        // Pedido aberto-2.png: Lexie: "Posso fechar a conta?" / Você: "Sim!"
        if (!state.lastKnownCart.itens || state.lastKnownCart.itens.length === 0) {
          await sendVoiceEvent("Gostaria de dois X-Bacon e um suco de laranja.", 0.96, origem);
        }
        setTimeout(() => {
          switchScreen("orderOpen");
          setDialogueBox("Lexie", "Posso fechar a conta?", "Você", "Sim!");
        }, 90);
        break;

      case "6":
        // Pedido aberto-3.png: Comanda Fechada -> "Pedido Finalizado!"
        if (!state.lastKnownCart.itens || state.lastKnownCart.itens.length === 0) {
          await sendVoiceEvent("Gostaria de dois X-Bacon e um suco de laranja.", 0.96, origem);
        }
        setTimeout(() => {
          sendVoiceEvent("Confirmar pedido", 0.98, origem);
        }, 90);
        break;

      case "7":
        // Critério de Aceite: Estado PENDING por dúvida explícita do I5 (confiança < 0.5)
        await sendVoiceEvent("ruído incompreensível no balcão...", 0.32, origem);
        break;

      case "8":
        // Critério de Aceite: Estado PENDING por produto indisponível no catálogo
        await sendVoiceEvent("quero um vegetariano futuro", 0.94, origem);
        break;

      case "9":
        // Item com variação / modificador
        await sendVoiceEvent("quero um x-salada sem cebola", 0.96, origem);
        break;

      default:
        break;
    }
  }

  // ---------------------------------------------------------------------------
  // Carregamento dos Arquivos JSON Reais do Componente I5
  // ---------------------------------------------------------------------------
  async function loadI5Files() {
    if (!dom.devI5Files) return;
    try {
      const resp = await fetch("/api/i5/arquivos");
      const data = await resp.json();
      const arquivos = data.arquivos || [];
      if (arquivos.length === 0) {
        dom.devI5Files.innerHTML = `<span class="dev-muted">Nenhum JSON do I5 encontrado.</span>`;
        return;
      }

      dom.devI5Files.innerHTML = arquivos
        .map(
          (arq) => `
          <button type="button" class="dev-btn" data-i5-file="${arq.caminho}" title="${arq.texto_transcrito}">
            🎙️ <strong>${arq.nome}</strong> (conf: ${Number(arq.confianca_geral).toFixed(2)})<br/>
            <span class="dev-muted">"${arq.texto_transcrito.slice(0, 62)}..."</span>
          </button>
        `
        )
        .join("");

      dom.devI5Files.querySelectorAll("[data-i5-file]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const caminho = btn.getAttribute("data-i5-file");
          const origem = (dom.devOrigemInput && dom.devOrigemInput.value.trim()) || state.origemAtiva;
          state.lastSendTimestamp = performance.now();
          await fetch("/api/i5/reproduzir", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ arquivo: caminho, origem }),
          });
        });
      });
    } catch (err) {
      dom.devI5Files.innerHTML = `<span class="dev-muted">Erro ao listar arquivos I5.</span>`;
    }
  }

  // ---------------------------------------------------------------------------
  // Eventos de Teclado (Operação sem clique na tela) e Painel de Avaliação
  // ---------------------------------------------------------------------------
  function setupEventListeners() {
    window.addEventListener("keydown", (e) => {
      const tag = (e.target && e.target.tagName) || "";
      const isTyping = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

      if ((e.key === "d" || e.key === "D" || e.key === "F2") && !isTyping) {
        e.preventDefault();
        dom.devDrawer.classList.toggle("hidden");
        if (!dom.devDrawer.classList.contains("hidden")) {
          loadI5Files();
        }
        return;
      }

      if (!isTyping && /^[1-9]$/.test(e.key)) {
        e.preventDefault();
        triggerScene(e.key);
      }
    });

    if (dom.devCloseBtn) {
      dom.devCloseBtn.addEventListener("click", () => {
        dom.devDrawer.classList.add("hidden");
      });
    }

    document.querySelectorAll("[data-scene]").forEach((btn) => {
      btn.addEventListener("click", () => {
        triggerScene(btn.getAttribute("data-scene"));
      });
    });

    if (dom.devSendVoiceBtn) {
      dom.devSendVoiceBtn.addEventListener("click", () => {
        const txt = dom.devVoiceText.value.trim();
        const conf = parseFloat(dom.devVoiceConf.value || "0.95");
        if (txt) {
          sendVoiceEvent(txt, conf);
          dom.devVoiceText.value = "";
        }
      });
    }

    if (dom.devVoiceText) {
      dom.devVoiceText.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          dom.devSendVoiceBtn.click();
        }
      });
    }

    // Mapeamento dos endpoints REST do backend
    if (dom.restBtnConfirmar) {
      dom.restBtnConfirmar.addEventListener("click", () => callRestAction("/confirmar", "POST"));
    }
    if (dom.restBtnCancelar) {
      dom.restBtnCancelar.addEventListener("click", () => callRestAction("/cancelar", "POST"));
    }
    if (dom.restBtnResetar) {
      dom.restBtnResetar.addEventListener("click", () => callRestAction("/reset", "POST"));
    }
    if (dom.restBtnEditar) {
      dom.restBtnEditar.addEventListener("click", () =>
        callRestAction("/editar", "POST", {
          acao: "adicionar",
          produto_id: 1,
          quantidade: 1,
          variacoes: ["sem cebola", "queijo extra"],
        })
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Inicialização
  // ---------------------------------------------------------------------------
  function init() {
    // Atualiza imediatamente os labels visuais da comanda com a origem da aba
    const origemLabel = formatOrigemDisplay(state.origemAtiva);
    if (dom.comandaOpenLabel) dom.comandaOpenLabel.textContent = `${origemLabel} - COMANDA ABERTA`;
    if (dom.comandaClosedLabel) dom.comandaClosedLabel.textContent = `${origemLabel} - COMANDA FECHADA`;
    if (dom.devOrigemInput) dom.devOrigemInput.value = state.origemAtiva;

    setupEventListeners();
    connectWebSocket();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

