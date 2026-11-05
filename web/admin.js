(function () {
  "use strict";

  const qs = (selector) => document.querySelector(selector);

  function formatTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    return `${hours}h ${minutes % 60}min`;
  }

  function statusClass(status) {
    if (status === "PENDENTE") return "status-pending";
    if (status === "CONFIRMADO") return "status-confirmed";
    if (status === "ENTREGUE") return "status-delivered";
    return "status-production";
  }

  function renderTables(mesas) {
    const body = qs("#tables-body");
    const empty = qs("#tables-empty");
    body.innerHTML = "";

    qs("#tables-count").textContent = `${mesas.length} ${mesas.length === 1 ? "mesa" : "mesas"}`;
    empty.style.display = mesas.length ? "none" : "block";

    for (const mesa of mesas) {
      const row = document.createElement("tr");
      const itemCount = (mesa.itens || []).reduce((sum, item) => sum + Number(item.quantidade || 0), 0);
      row.innerHTML = `
        <td><strong>${escapeHtml(mesa.origem || "—")}</strong></td>
        <td><span class="status-tag ${statusClass(mesa.situacao.toUpperCase())}">${escapeHtml(mesa.situacao)}</span></td>
        <td>${itemCount} ${itemCount === 1 ? "item" : "itens"}</td>
        <td>R$ ${Number(mesa.total || 0).toFixed(2)}</td>
        <td>${formatTime(mesa.idade_segundos || 0)}</td>
      `;
      body.appendChild(row);
    }
  }

  function escapeHtml(value) {
    const span = document.createElement("span");
    span.textContent = String(value);
    return span.innerHTML;
  }

  function renderChart(hourly) {
    const chart = qs("#metrics-chart");
    chart.innerHTML = "";

    if (!hourly || hourly.length === 0) {
      chart.innerHTML = '<p class="empty-state" style="margin:auto">Sem séries temporais recebidas do S5.</p>';
      return;
    }

    const chartData = hourly.map((row) => ({
      hour: row.hour,
      confirmed: Number(row.count || 0),
    }));
    const max = Math.max(1, ...chartData.map((row) => row.confirmed));

    for (const row of chartData) {
      const group = document.createElement("div");
      group.className = "chart-bar-group";
      const height = Math.max(2, Math.round((row.confirmed / max) * 185));
      group.innerHTML = `
        <div class="bars">
          <div class="bar bar-confirmed" style="height:${height}px" title="${row.confirmed} eventos"></div>
        </div>
        <span class="chart-label">${escapeHtml(row.hour)}</span>
      `;
      chart.appendChild(group);
    }
  }

  function formatCurrency(value) {
    return Number(value || 0).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
    });
  }

  function formatDate(dateValue) {
    if (!dateValue) return "—";
    const date = new Date(`${dateValue}T12:00:00`);
    if (Number.isNaN(date.getTime())) return dateValue;
    return date.toLocaleDateString("pt-BR", {
      weekday: "short",
      day: "2-digit",
      month: "2-digit",
    });
  }

  function renderOperationalSummary(localSummary) {
    const list = qs("#event-list");
    list.innerHTML = "";
    const rows = [
      ["Valor atual nos carrinhos", `${localSummary.carrinhos_com_itens || 0} carrinhos com itens`, formatCurrency(localSummary.valor_carrinhos)],
      ["Ticket médio atual", "carrinhos com itens", formatCurrency(localSummary.ticket_medio_carrinhos)],
      ["Mesas em andamento", "sessões locais", String(localSummary.mesas_ativas || 0)],
      ["Confirmadas / entregues", "estado das sessões", `${localSummary.confirmados || 0} / ${localSummary.entregues || 0}`],
      ["Pendentes", "aguardam resolução", String(localSummary.pendentes || 0)],
    ];

    for (const [label, detail, value] of rows) {
      const row = document.createElement("div");
      row.className = "event-row";
      row.innerHTML = `
        <strong>${escapeHtml(label)}</strong>
        <span class="uncertain">${escapeHtml(detail)}</span>
        <span class="event-count">${escapeHtml(value)}</span>
      `;
      list.appendChild(row);
    }
  }

  async function loadDashboard() {
    try {
      const response = await fetch("/api/admin/dashboard", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const local = data.local || {};
      const localSummary = local.summary || {};
      const s5 = data.s5 || {};
      const s5Summary = s5.summary || {};
      const insights = s5.insights || {};
      const weekdays = s5.weekdays || [];

      const demoBanner = qs("#demo-banner");
      demoBanner.hidden = !s5.demonstration;

      qs("#metric-active").textContent = localSummary.mesas_ativas || 0;
      qs("#metric-active-detail").textContent = `${localSummary.pendentes || 0} pendentes · ${localSummary.entregues || 0} entregues`;
      qs("#metric-s5-total").textContent = s5Summary.total_count || 0;
      qs("#metric-production").textContent = localSummary.em_producao || 0;
      qs("#metric-time").textContent = s5Summary.duration_avg_minutes != null
        ? `${s5Summary.duration_avg_minutes} min`
        : "—";
      qs("#source-pill").textContent =
        s5.source === "s5-kafka"
          ? "S5 · KAFKA"
          : s5.source === "s5-aguardando"
            ? "Aguardando S5"
            : "S5 · KAFKA";
      qs("#updated-at").textContent = `Atualizado às ${new Date(data.generated_at).toLocaleTimeString("pt-BR")}`;

      renderTables(local.mesas || []);
      renderChart(s5.hourly || []);
      renderOperationalSummary(localSummary);

      if (insights.peak_hour) {
        qs("#metric-peak-hour").textContent = insights.peak_hour.hour;
        qs("#metric-peak-hour-detail").textContent =
          `${insights.peak_hour.count} eventos na série horária`;
      } else {
        qs("#metric-peak-hour").textContent = "—";
        qs("#metric-peak-hour-detail").textContent = "Sem dados históricos suficientes";
      }

      if (insights.peak_day) {
        qs("#metric-peak-day").textContent = formatDate(insights.peak_day.date);
        qs("#metric-peak-day-detail").textContent =
          `${insights.peak_day.count} eventos nesse dia`;
      } else {
        qs("#metric-peak-day").textContent = "—";
        qs("#metric-peak-day-detail").textContent = "Sem dados históricos suficientes";
      }

      qs("#metric-daily-average").textContent =
        insights.average_daily_count != null ? String(insights.average_daily_count) : "—";

      const total = Object.values(s5.by_event || {}).reduce(
        (sum, event) => sum + Number(event.count || 0),
        0,
      );
      const uncertain = s5Summary.uncertain_count || 0;
      const rate = total > 0 ? (uncertain / total) * 100 : 0;
      qs("#uncertainty-rate").textContent = `${rate.toFixed(1)}%`;
      qs("#uncertainty-detail").textContent = `${uncertain} de ${total} eventos incertos`;
    } catch (error) {
      qs("#source-pill").textContent = "API indisponível";
      qs("#updated-at").textContent = "Falha na atualização";
      console.error(error);
    }
  }

  loadDashboard();
  setInterval(loadDashboard, 5000);
})();
