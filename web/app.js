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
  // ---------------------------------------------------------------------------
  // Catálogos Padrão Imediatos (Garantem exibição instantânea sem falhas de rede)
  // ---------------------------------------------------------------------------
  const DEFAULT_INTENCOES = [
    {
      nome: "ADICIONAR_ITEM",
      descricao: "O cliente deseja pedir, incluir ou adicionar itens ao carrinho.",
      exemplos: [
        "Quero dois x-saladas",
        "Me vê uma coca-cola por favor",
        "Vou pedir uma batata frita e um suco de laranja",
        "Adiciona mais um milkshake"
      ]
    },
    {
      nome: "REMOVER_ITEM",
      descricao: "O cliente deseja retirar, subtrair ou cancelar um item do pedido.",
      exemplos: [
        "Tira o x-salada",
        "Não quero mais a coca-cola",
        "Remove a batata frita do meu pedido"
      ]
    },
    {
      nome: "CONFIRMAR_PEDIDO",
      descricao: "O cliente está satisfeito com os itens e deseja fechar, confirmar ou finalizar o pedido.",
      exemplos: [
        "Pode fechar o pedido",
        "Está certo, confirmo",
        "É só isso mesmo, pode mandar",
        "Confirmar pedido"
      ]
    },
    {
      nome: "CANCELAR_PEDIDO",
      descricao: "O cliente deseja desistir de toda a compra e limpar a comanda.",
      exemplos: [
        "Cancela tudo",
        "Quero cancelar o pedido inteiro",
        "Desisti, pode zerar a comanda"
      ]
    },
    {
      nome: "CONSULTAR_CARDAPIO",
      descricao: "O cliente está com dúvida sobre opções, preços ou disponibilidade de produtos.",
      exemplos: [
        "Quanto custa a batata frita?",
        "Vocês têm opção vegetariana?",
        "Quais sabores de milkshake tem?"
      ]
    },
    {
      nome: "CHAMAR_ATENDIMENTO",
      descricao: "O cliente solicita ajuda de um atendente ou garçom humano.",
      exemplos: [
        "Chama o garçom por favor",
        "Preciso de ajuda de um atendente",
        "Pode chamar alguém aqui?"
      ]
    },
    {
      nome: "PEDIR_CONTA",
      descricao: "O cliente pede o fechamento da conta ou forma de pagamento no balcão/mesa.",
      exemplos: [
        "Pode trazer a conta",
        "Quero pagar",
        "Fecha a comanda pra mim"
      ]
    }
  ];

  const DEFAULT_PRODUTOS = [
    { id: 1, nome: "X-Salada", preco: 22.9, variacoes: ["sem cebola", "molho especial", "queijo extra", "pão integral"], disponibilidade: true },
    { id: 2, nome: "X-Bacon", preco: 26.5, variacoes: ["bacon extra", "sem maionese", "pão brioche"], disponibilidade: true },
    { id: 3, nome: "X-Tudo", preco: 32.0, variacoes: ["sem milho", "sem ervilha", "ovo extra"], disponibilidade: true },
    { id: 4, nome: "Hamburguer Artesanal Smash", preco: 19.9, variacoes: ["duplo smash", "queijo cheddar", "queijo prato"], disponibilidade: true },
    { id: 5, nome: "Vegetariano Futuro", preco: 25.0, variacoes: ["queijo vegano", "sem maionese"], disponibilidade: false },
    { id: 6, nome: "Coca-Cola Lata 350ml", preco: 6.5, variacoes: ["Original", "Zero Açúcar"], disponibilidade: true },
    { id: 7, nome: "Coca-Cola Garrafa 600ml", preco: 9.5, variacoes: ["Original", "Zero Açúcar"], disponibilidade: true },
    { id: 8, nome: "Guaraná Antarctica 350ml", preco: 6.0, variacoes: ["Original", "Zero"], disponibilidade: true },
    { id: 9, nome: "Suco Natural de Laranja 500ml", preco: 8.0, variacoes: ["com açúcar", "sem açúcar", "com gelo"], disponibilidade: true },
    { id: 10, nome: "Água Mineral 500ml", preco: 4.0, variacoes: ["sem gás", "com gás", "com limão"], disponibilidade: true },
    { id: 11, nome: "Batata Frita Padrão", preco: 14.0, variacoes: ["com cheddar e bacon", "sem sal"], disponibilidade: true },
    { id: 12, nome: "Batata Frita Grande", preco: 22.0, variacoes: ["com cheddar e bacon", "porção dupla de bacon"], disponibilidade: true },
    { id: 13, nome: "Onion Rings", preco: 18.0, variacoes: ["molho ranch", "molho picante"], disponibilidade: false },
    { id: 14, nome: "Nuggets de Frango 8 unidades", preco: 16.0, variacoes: ["molho mostarda e mel", "molho barbecue"], disponibilidade: true },
    { id: 15, nome: "Milkshake de Chocolate 400ml", preco: 15.0, variacoes: ["com chantilly", "calda extra"], disponibilidade: true },
    { id: 16, nome: "Milkshake de Morango 400ml", preco: 15.0, variacoes: ["com chantilly"], disponibilidade: true },
    { id: 17, nome: "Pudim de Leite Condensado", preco: 9.0, variacoes: ["fatia individual"], disponibilidade: true },
    { id: 18, nome: "Brownie com Sorvete", preco: 17.5, variacoes: ["sorvete de creme", "calda quente"], disponibilidade: true }
  ];

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
    currentScreen: "welcome",
    previousScreen: "welcome",
    chatHistory: [],
    isThinking: false,
    thinkingTimer: null,
    intencoes: DEFAULT_INTENCOES,
    produtosCardapio: DEFAULT_PRODUTOS,
    menuFilter: "all",
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
      help: document.getElementById("view-help"),
    },

    // Central de Ajuda & Cardápio
    btnToggleHelp: document.getElementById("btn-toggle-help"),
    btnCloseHelp: document.getElementById("btn-close-help"),
    tabBtnIntents: document.getElementById("tab-btn-intents"),
    tabBtnMenu: document.getElementById("tab-btn-menu"),
    paneIntents: document.getElementById("pane-intents"),
    paneMenu: document.getElementById("pane-menu"),
    intentsGridContainer: document.getElementById("intents-grid-container"),
    menuGridContainer: document.getElementById("menu-grid-container"),
    menuFilterChips: document.getElementById("menu-filter-chips"),

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
    if (state.currentScreen !== "help" && screenKey !== "help") {
      state.previousScreen = state.currentScreen;
    }
    state.currentScreen = screenKey;

    Object.entries(dom.views).forEach(([key, el]) => {
      if (!el) return;
      if (key === screenKey) {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    });

    if (dom.btnToggleHelp) {
      const btnText = dom.btnToggleHelp.querySelector(".help-btn-text");
      if (screenKey === "help") {
        dom.btnToggleHelp.classList.add("active");
        if (btnText) btnText.textContent = "Fechar Ajuda";
      } else {
        dom.btnToggleHelp.classList.remove("active");
        if (btnText) btnText.textContent = "Ajuda & Cardápio";
      }
    }
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

  function appendChatMessage(sender, text, isPending = false) {
    if (!text || !String(text).trim()) return;
    const cleanText = String(text).trim();
    const last = state.chatHistory[state.chatHistory.length - 1];
    if (last && last.sender === sender && last.text === cleanText) return;

    state.chatHistory.push({ sender, text: cleanText, isPending });
    if (state.chatHistory.length > 30) state.chatHistory.shift();
    renderChatBoxes();
  }

  // Venetian Blinds Loader SVG (Animação de Ouvindo)
  function createVenetianBlindsSvg(boxId = "global") {
    const discId = `ven-disc-${boxId}`;
    const faceId = `ven-face-${boxId}`;
    return `
      <svg xmlns="http://www.w3.org/2000/svg" class="ven-icon" viewBox="0 0 64 64" fill="none" role="img" aria-label="Ouvindo">
        <defs>
          <clipPath id="${discId}"><circle cx="32" cy="32" r="32"/></clipPath>
          <linearGradient id="${faceId}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.85"/>
            <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.18"/>
          </linearGradient>
        </defs>
        <g clip-path="url(#${discId})">
          <rect class="ven-slat" fill="url(#${faceId})" x="-2" y="0.00" width="68" height="7.11" style="--i:0;--rest:0.0"/>
          <rect class="ven-slat" fill="url(#${faceId})" x="-2" y="7.11" width="68" height="7.11" style="--i:1;--rest:40.0"/>
          <rect class="ven-slat" fill="url(#${faceId})" x="-2" y="14.22" width="68" height="7.11" style="--i:2;--rest:80.0"/>
          <rect class="ven-slat" fill="url(#${faceId})" x="-2" y="21.33" width="68" height="7.11" style="--i:3;--rest:120.0"/>
          <rect class="ven-slat" fill="url(#${faceId})" x="-2" y="28.44" width="68" height="7.11" style="--i:4;--rest:160.0"/>
          <rect class="ven-slat" fill="url(#${faceId})" x="-2" y="35.56" width="68" height="7.11" style="--i:5;--rest:200.0"/>
          <rect class="ven-slat" fill="url(#${faceId})" x="-2" y="42.67" width="68" height="7.11" style="--i:6;--rest:240.0"/>
          <rect class="ven-slat" fill="url(#${faceId})" x="-2" y="49.78" width="68" height="7.11" style="--i:7;--rest:280.0"/>
          <rect class="ven-slat" fill="url(#${faceId})" x="-2" y="56.89" width="68" height="7.11" style="--i:8;--rest:320.0"/>
        </g>
      </svg>
    `;
  }

  // Constellation Loader SVG (Animação de Pensando com nós e conexões)
  const constellationSvgHtml = `
    <svg xmlns="http://www.w3.org/2000/svg" class="con-icon" viewBox="0 0 64 64" fill="none" role="img" aria-label="Processando">
      <circle class="con-bound" cx="32" cy="32" r="30"/>
      <line class="con-link" x1="31.26" y1="56.57" x2="37.31" y2="44.56" style="--h:2"/>
      <line class="con-link" x1="31.26" y1="56.57" x2="17.60" y2="47.27" style="--h:2"/>
      <line class="con-link" x1="31.26" y1="56.57" x2="25.09" y2="38.70" style="--h:2"/>
      <line class="con-link" x1="41.24" y1="28.64" x2="53.04" y2="19.01" style="--h:2"/>
      <line class="con-link" x1="41.24" y1="28.64" x2="37.31" y2="44.56" style="--h:2"/>
      <line class="con-link" x1="41.24" y1="28.64" x2="32.00" y2="22.43" style="--h:1"/>
      <line class="con-link" x1="41.24" y1="28.64" x2="44.02" y2="12.95" style="--h:1"/>
      <line class="con-link" x1="41.24" y1="28.64" x2="25.09" y2="38.70" style="--h:1"/>
      <line class="con-link" x1="53.04" y1="19.01" x2="44.02" y2="12.95" style="--h:2"/>
      <line class="con-link" x1="12.10" y1="38.52" x2="19.90" y2="22.96" style="--h:2"/>
      <line class="con-link" x1="12.10" y1="38.52" x2="17.60" y2="47.27" style="--h:2"/>
      <line class="con-link" x1="12.10" y1="38.52" x2="25.09" y2="38.70" style="--h:2"/>
      <line class="con-link" x1="37.31" y1="44.56" x2="17.60" y2="47.27" style="--h:2"/>
      <line class="con-link" x1="37.31" y1="44.56" x2="53.05" y2="46.45" style="--h:3"/>
      <line class="con-link" x1="37.31" y1="44.56" x2="25.09" y2="38.70" style="--h:2"/>
      <line class="con-link" x1="19.90" y1="22.96" x2="32.00" y2="22.43" style="--h:1"/>
      <line class="con-link" x1="19.90" y1="22.96" x2="25.09" y2="38.70" style="--h:1"/>
      <line class="con-link" x1="17.60" y1="47.27" x2="25.09" y2="38.70" style="--h:2"/>
      <line class="con-link" x1="32.00" y1="22.43" x2="44.02" y2="12.95" style="--h:1"/>
      <line class="con-link" x1="32.00" y1="22.43" x2="25.09" y2="38.70" style="--h:1"/>
      <circle class="con-node" cx="31.26" cy="56.57" r="1.7" style="--h:2"/>
      <circle class="con-node" cx="41.24" cy="28.64" r="1.7" style="--h:1"/>
      <circle class="con-node" cx="53.04" cy="19.01" r="1.7" style="--h:2"/>
      <circle class="con-node" cx="44.02" cy="12.95" r="1.7" style="--h:2"/>
      <circle class="con-node" cx="19.90" cy="22.96" r="1.7" style="--h:2"/>
      <circle class="con-node" cx="12.10" cy="38.52" r="1.7" style="--h:2"/>
      <circle class="con-node" cx="17.60" cy="47.27" r="1.7" style="--h:2"/>
      <circle class="con-node" cx="53.05" cy="46.45" r="1.7" style="--h:3"/>
      <circle class="con-node" cx="37.31" cy="44.56" r="1.7" style="--h:2"/>
      <circle class="con-node con-seed" cx="32.00" cy="22.43" r="2.3" style="--h:0"/>
      <circle class="con-node" cx="25.09" cy="38.70" r="1.7" style="--h:1"/>
    </svg>
  `;

  function setThinkingState(thinking, durationMs = 2400) {
    if (state.thinkingTimer) {
      clearTimeout(state.thinkingTimer);
      state.thinkingTimer = null;
    }
    state.isThinking = thinking;
    renderChatBoxes();

    if (thinking && durationMs > 0) {
      state.thinkingTimer = setTimeout(() => {
        state.isThinking = false;
        renderChatBoxes();
        setVoiceVisualState(
          state.currentSessionState === "PENDING" ? "pending" : "listening",
          state.currentSessionState === "PENDING" ? "Atenção: Dúvida Explícita" : "Estou ouvindo você",
          state.currentSessionState === "PENDING" ? "Por favor, repita ou escolha outro produto por voz" : "Pode falar naturalmente"
        );
      }, durationMs);
    }
  }

  function renderChatBoxes() {
    const boxes = [
      { el: document.getElementById("order-dialogue-box"), id: "order" },
      { el: document.getElementById("listening-dialogue-box"), id: "listening" },
    ];

    const chatItemsHtml =
      state.chatHistory.length === 0
        ? `<div class="chat-empty-hint">Diga seu pedido ou faça uma pergunta por voz...</div>`
        : state.chatHistory
            .map((msg) => {
              const s = (msg.sender || "").toLowerCase();
              const isUser = s === "você" || s === "voce" || s === "user" || s === "cliente";
              const senderClass = isUser ? "user" : "lexie";
              const senderLabel = isUser ? "Você" : "Lexie";
              const pendingClass = msg.isPending ? "pending" : "";

              return `
                <div class="chat-bubble-row ${senderClass} ${pendingClass}">
                  <div class="chat-sender-header ${senderClass}">
                    <span class="dialogue-dot ${isUser ? "dot-user" : "dot-lexie"}"></span>
                    <span>${senderLabel}</span>
                  </div>
                  <div class="chat-bubble">
                    ${msg.text}
                  </div>
                </div>
              `;
            })
            .join("");

    boxes.forEach(({ el, id }) => {
      if (!el) return;

      const listeningSvg = createVenetianBlindsSvg(id);

      const bottomStatusHtml = state.isThinking
        ? `
          <div class="chat-bottom-status-row">
            <div class="chat-bottom-status thinking">
              ${constellationSvgHtml}
              <span>Pensando...</span>
            </div>
          </div>
        `
        : `
          <div class="chat-bottom-status-row">
            <div class="chat-bottom-status listening">
              ${listeningSvg}
              <span>Ouvindo</span>
            </div>
          </div>
        `;

      el.innerHTML = chatItemsHtml + bottomStatusHtml;
      el.scrollTop = el.scrollHeight;
    });
  }

  function setDialogueBox(row1Speaker, row1Text, row2Speaker, row2Text, isPending = false) {
    if (row1Text) appendChatMessage(row1Speaker, row1Text, false);
    if (row2Text) appendChatMessage(row2Speaker, row2Text, isPending);
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
  // Controle de Estado Visual do Circle Loader (Idle, Listening, Processing, Pending)
  // ---------------------------------------------------------------------------
  function setVoiceVisualState(mode, headline, subheadline) {
    const wrappers = document.querySelectorAll(".orb-wrapper");
    wrappers.forEach((w) => {
      w.classList.remove("mode-idle", "mode-listening", "mode-processing", "mode-pending", "orb-pending");
      w.classList.add(`mode-${mode}`);
      if (mode === "pending") w.classList.add("orb-pending");
    });

    if (headline) {
      if (dom.orderVoiceHeadline) dom.orderVoiceHeadline.textContent = headline;
      const lHeadline = document.getElementById("listening-headline");
      if (lHeadline) lHeadline.textContent = headline;
    }
    if (subheadline) {
      if (dom.orderVoiceSubheadline) dom.orderVoiceSubheadline.textContent = subheadline;
      const lSubheadline = document.getElementById("listening-subheadline");
      if (lSubheadline) lSubheadline.textContent = subheadline;
    }
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

    // Se a mensagem veio com transcrição do usuário e não estava pensando, ativa pensando temporário
    if (payload.texto_usuario && !state.isThinking) {
      setThinkingState(true, 2000);
    }

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
    dom.comandaOpenCard.classList.toggle("card-pending", isPending);

    if (isPending) {
      const motivo =
        payload.pending_reason ||
        payload.mensagem ||
        "Confiança baixa na transcrição do I5 ou produto indisponível no catálogo.";
      dom.pendingAlertReason.textContent = motivo;
      dom.pendingAlertBanner.classList.remove("hidden");
      setVoiceVisualState("pending", "Atenção: Dúvida Explícita", "Por favor, repita ou escolha outro produto por voz");
    } else {
      dom.pendingAlertBanner.classList.add("hidden");
      setVoiceVisualState("listening", "Estou ouvindo você", "Pode falar naturalmente");
    }

    const textoUsuario = payload.texto_usuario || "Comando de voz recebido";
    const respostaLexie = buildFriendlyLexieReply(payload, cart);
    const intencaoRecebida = payload.intencao || (payload.resultado_nlu && payload.resultado_nlu.intencao);

    // Comando de voz para voltar da tela de ajuda
    if (/voltar|fechar( ajuda| card[aá]pio)?|sair do card[aá]pio/i.test(textoUsuario)) {
      if (state.currentScreen === "help") {
        switchScreen(state.previousScreen || (hasItems ? "orderOpen" : "listening"));
        return;
      }
    }

    // Comando de voz explícito para abrir "O que a Lexie Entende" ou "Cardápio"
    const isAskingIntents = /o que (a lexie|voc[eê]) (entende|sabe|faz)|o que entende|quais (as )?a[cç][oõ]es|quais (os )?comandos|a[cç][oõ]es da lexie/i.test(textoUsuario);
    const isAskingMenu = /card[aá]pio|menu|mostrar (o )?card[aá]pio|ver (o )?card[aá]pio|abrir card[aá]pio/i.test(textoUsuario);
    const isAskingHelp = /^(ajuda|help)$/i.test(textoUsuario.trim()) || /abrir ajuda|central de ajuda/i.test(textoUsuario);

    if (isAskingIntents || isAskingMenu || isAskingHelp) {
      if (hasItems) {
        renderComandaItems(dom.comandaOpenItems, dom.comandaOpenTotal, cart);
      }
      switchScreen("help");
      if (isAskingMenu && !isAskingIntents) {
        if (dom.tabBtnMenu) dom.tabBtnMenu.click();
      } else {
        if (dom.tabBtnIntents) dom.tabBtnIntents.click();
      }
      return;
    }

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
      setDialogueBox("Você", textoUsuario, "Lexie", respostaLexie, false);
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
        payload.dialogo_custom.t2,
        isPending
      );
    } else {
      setDialogueBox("Você", textoUsuario, "Lexie", respostaLexie, isPending);
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

    // Feedback imediato na interface: Lexie entra em modo pensando com Constellation SVG
    setThinkingState(true, 2400);
    setVoiceVisualState("processing", "Processando pedido...", "Interpretando comando de voz...");

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
        state.chatHistory = [];
        renderChatBoxes();
        setBadgeStyle(dom.globalStateBadge, "IDLE", "AGUARDANDO VOZ");
        dom.bgGlow.classList.remove("glow-pending");
        setVoiceVisualState("idle");
        switchScreen("welcome");
        break;

      case "2":
        // Tela Início-1.png: Você: "Fazer pedido" -> Lexie: "Pedido aberto para mesa 05"
        await callRestAction("/reset", "POST");
        state.lastKnownCart = { itens: [], total: 0.0 };
        state.chatHistory = [];
        await sendVoiceEvent("Fazer pedido", 0.98, origem);
        break;

      case "3":
        // Pedido aberto.png: "Gostaria de dois X-Bacon e um suco de laranja." -> 2x X-Bacon + 1x Suco
        await callRestAction("/reset", "POST");
        state.lastKnownCart = { itens: [], total: 0.0 };
        state.chatHistory = [];
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
            <strong>${arq.nome}</strong> (conf: ${Number(arq.confianca_geral).toFixed(2)})<br/>
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
  // Central de Ajuda: Intenções Reconhecidas e Cardápio Completo
  // ---------------------------------------------------------------------------
  const INTENT_META = {
    ADICIONAR_ITEM: {
      titulo: "Adicionar Itens ao Pedido",
      tag: "ADICIONAR",
    },
    REMOVER_ITEM: {
      titulo: "Remover Item do Pedido",
      tag: "REMOVER",
    },
    CONFIRMAR_PEDIDO: {
      titulo: "Confirmar Pedido / Enviar à Cozinha",
      tag: "CONFIRMAR",
    },
    CANCELAR_PEDIDO: {
      titulo: "Cancelar Pedido Inteiro",
      tag: "CANCELAR",
    },
    CONSULTAR_CARDAPIO: {
      titulo: "Consultar Cardápio e Dúvidas",
      tag: "CARDÁPIO",
    },
    CHAMAR_ATENDIMENTO: {
      titulo: "Chamar Atendente Humano",
      tag: "ATENDIMENTO",
    },
    PEDIR_CONTA: {
      titulo: "Pedir a Conta e Pagamento",
      tag: "CONTA",
    },
  };

  async function loadHelpData() {
    try {
      const [resIntencoes, resCardapio] = await Promise.all([
        fetch("/api/intencoes").catch(() => null),
        fetch("/api/cardapio").catch(() => null),
      ]);

      if (resIntencoes && resIntencoes.ok) {
        const data = await resIntencoes.json();
        if (data.intencoes && data.intencoes.length) {
          state.intencoes = data.intencoes;
          renderIntentsGrid();
        }
      }

      if (resCardapio && resCardapio.ok) {
        const data = await resCardapio.json();
        if (data.produtos && data.produtos.length) {
          state.produtosCardapio = data.produtos;
          renderMenuGrid();
        }
      }
    } catch (e) {
      console.warn("Aviso ao carregar dados de ajuda/cardápio:", e);
    }
  }

  function renderIntentsGrid() {
    if (!dom.intentsGridContainer) return;
    const list = (state.intencoes && state.intencoes.length > 0) ? state.intencoes : DEFAULT_INTENCOES;

    dom.intentsGridContainer.innerHTML = list
      .map((it) => {
        const meta = INTENT_META[it.nome] || {
          titulo: it.nome,
          tag: it.nome,
        };
        const exemplosHtml = (it.exemplos || [])
          .slice(0, 4)
          .map((ex) => `<div class="intent-example-item">${ex}</div>`)
          .join("");

        return `
          <div class="intent-card" data-intent="${it.nome}">
            <div class="intent-card-header">
              <h3 class="intent-title">${meta.titulo}</h3>
              <span class="intent-raw-tag">${meta.tag}</span>
            </div>
            <p class="intent-description">${it.descricao}</p>
            <div class="intent-examples-box">
              <span class="intent-examples-title">Exemplos do que falar:</span>
              ${exemplosHtml}
            </div>
          </div>
        `;
      })
      .join("");
  }

  function getProductCategory(produto) {
    const nome = (produto.nome || "").toLowerCase();
    if (
      nome.includes("coca") ||
      nome.includes("guaraná") ||
      nome.includes("suco") ||
      nome.includes("água") ||
      nome.includes("lata") ||
      nome.includes("garrafa")
    ) {
      return "bebidas";
    }
    if (nome.includes("batata") || nome.includes("nuggets") || nome.includes("onion")) {
      return "porcoes";
    }
    if (
      nome.includes("milkshake") ||
      nome.includes("pudim") ||
      nome.includes("brownie") ||
      nome.includes("sorvete")
    ) {
      return "sobremesas";
    }
    return "sanduiches";
  }

  function renderMenuGrid() {
    if (!dom.menuGridContainer) return;
    const list = (state.produtosCardapio && state.produtosCardapio.length > 0) ? state.produtosCardapio : DEFAULT_PRODUTOS;

    const filtered = list.filter((prod) => {
      if (state.menuFilter === "all") return true;
      return getProductCategory(prod) === state.menuFilter;
    });

    dom.menuGridContainer.innerHTML = filtered
      .map((prod) => {
        const isAvail = prod.disponibilidade !== false;
        const precoFmt = `R$ ${Number(prod.preco || 0).toFixed(2).replace(".", ",")}`;
        const variacoesHtml = (prod.variacoes || [])
          .map((v) => `<span class="menu-variation-chip">${v}</span>`)
          .join("");

        return `
          <div class="menu-item-card ${isAvail ? "" : "is-unavailable"}">
            <div class="menu-item-top">
              <h3 class="menu-item-name">${prod.nome}</h3>
              <span class="menu-item-price">${precoFmt}</span>
            </div>
            <div class="menu-item-status-row">
              <span class="menu-avail-badge ${isAvail ? "available" : "unavailable"}">
                ${isAvail ? "Disponível" : "Indisponível"}
              </span>
            </div>
            ${
              variacoesHtml
                ? `<div class="menu-variations-container">${variacoesHtml}</div>`
                : ""
            }
            <div class="menu-voice-trigger">
              <span>Diga: “Quero ${prod.nome}”</span>
            </div>
          </div>
        `;
      })
      .join("");
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

    // Botões de teste direto dos estados do Circle Loader (Corona Swell)
    const btnIdle = document.getElementById("btn-state-idle");
    const btnListening = document.getElementById("btn-state-listening");
    const btnProcessing = document.getElementById("btn-state-processing");
    const btnPending = document.getElementById("btn-state-pending");

    if (btnIdle) btnIdle.addEventListener("click", () => setVoiceVisualState("idle", "Em descanso", "Aguardando novo cliente..."));
    if (btnListening) btnListening.addEventListener("click", () => setVoiceVisualState("listening", "Estou ouvindo você", "Pode falar naturalmente"));
    if (btnProcessing) btnProcessing.addEventListener("click", () => setVoiceVisualState("processing", "Processando pedido...", "Consultando cardápio local..."));
    if (btnPending) btnPending.addEventListener("click", () => setVoiceVisualState("pending", "Atenção: Dúvida Explícita", "Por favor, confirme ou repita seu pedido"));

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

    // Botão de alternar Central de Ajuda & Cardápio no topo
    if (dom.btnToggleHelp) {
      dom.btnToggleHelp.addEventListener("click", () => {
        if (state.currentScreen === "help") {
          switchScreen(state.previousScreen || "welcome");
        } else {
          switchScreen("help");
        }
      });
    }

    // Botão de fechar Ajuda (Voltar ao Atendimento)
    if (dom.btnCloseHelp) {
      dom.btnCloseHelp.addEventListener("click", () => {
        switchScreen(state.previousScreen || "welcome");
      });
    }

    // Abas da Central de Ajuda
    if (dom.tabBtnIntents && dom.tabBtnMenu) {
      dom.tabBtnIntents.addEventListener("click", () => {
        dom.tabBtnIntents.classList.add("active");
        dom.tabBtnIntents.setAttribute("aria-selected", "true");
        dom.tabBtnMenu.classList.remove("active");
        dom.tabBtnMenu.setAttribute("aria-selected", "false");
        if (dom.paneIntents) dom.paneIntents.classList.add("active");
        if (dom.paneMenu) dom.paneMenu.classList.remove("active");
        renderIntentsGrid();
      });

      dom.tabBtnMenu.addEventListener("click", () => {
        dom.tabBtnMenu.classList.add("active");
        dom.tabBtnMenu.setAttribute("aria-selected", "true");
        dom.tabBtnIntents.classList.remove("active");
        dom.tabBtnIntents.setAttribute("aria-selected", "false");
        if (dom.paneMenu) dom.paneMenu.classList.add("active");
        if (dom.paneIntents) dom.paneIntents.classList.remove("active");
        renderMenuGrid();
      });
    }

    // Filtros de Categoria do Cardápio
    if (dom.menuFilterChips) {
      dom.menuFilterChips.addEventListener("click", (e) => {
        const btn = e.target.closest(".menu-filter-btn");
        if (!btn) return;
        dom.menuFilterChips
          .querySelectorAll(".menu-filter-btn")
          .forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.menuFilter = btn.dataset.category || "all";
        renderMenuGrid();
      });
    }

    // Clique interativo nos exemplos para simular/testar comando de voz
    if (dom.paneIntents) {
      dom.paneIntents.addEventListener("click", (e) => {
        const item = e.target.closest(".intent-example-item");
        if (item && dom.devVoiceText && dom.devSendVoiceBtn) {
          const text = item.textContent.replace(/^[“”"•' ]+|[“”"•' ]+$/g, "").trim();
          dom.devVoiceText.value = text;
          dom.devSendVoiceBtn.click();
        }
      });
    }

    if (dom.paneMenu) {
      dom.paneMenu.addEventListener("click", (e) => {
        const trigger = e.target.closest(".menu-voice-trigger");
        if (trigger && dom.devVoiceText && dom.devSendVoiceBtn) {
          const card = trigger.closest(".menu-item-card");
          const nameEl = card && card.querySelector(".menu-item-name");
          if (nameEl) {
            dom.devVoiceText.value = `Quero um ${nameEl.textContent.trim()}`;
            dom.devSendVoiceBtn.click();
          }
        }
      });
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

    // Pré-renderiza imediatamente as intenções e cardápio com dados padrão
    renderIntentsGrid();
    renderMenuGrid();

    setupEventListeners();
    connectWebSocket();
    loadHelpData();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

