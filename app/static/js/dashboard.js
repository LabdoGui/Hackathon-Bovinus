(function () {
  "use strict";
  const { api, el, clear, fmt, reasonText, STATUS, showMessage } = window.PC;
  const $ = (id) => document.getElementById(id);
  const msg = $("page-msg");

  function card(label, value, hint) {
    return el("div", { class: "metric" }, [
      el("span", { class: "metric-label", text: label }),
      el("strong", { class: "metric-value", text: value }),
      hint ? el("span", { class: "metric-hint", text: hint }) : null,
    ]);
  }

  function table(headers, rows, emptyText) {
    if (!rows.length) return el("p", { class: "muted", text: emptyText });
    return el("div", { class: "table-wrap" }, el("table", {}, [
      el("thead", {}, el("tr", {}, headers.map((h) => el("th", { text: h })))),
      el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => (c instanceof Node ? c : el("td", { text: String(c) })))))),
    ]));
  }
  const td = (text, cls) => el("td", { text: String(text), class: cls });

  function renderSummary(s) {
    const root = clear($("summary"));
    root.appendChild(card("Transações confirmadas", String(s.transactions_confirmed), s.transactions_cancelled + " cancelada(s)"));
    root.appendChild(card("Valor cobrado", fmt.money(s.total_charged_amount), "Ticket médio " + fmt.money(s.average_ticket)));
    root.appendChild(card("Peso líquido", fmt.grams(s.total_net_weight_g), "Média " + fmt.grams(s.average_net_weight_g)));
    root.appendChild(card("Custo alimentar estimado", fmt.money(s.total_food_cost), s.cost_complete_transactions + " transação(ões) com custo completo"));
    root.appendChild(card("Margem bruta alimentar estimada", fmt.money(s.total_gross_margin), fmt.pct(s.gross_margin_pct) + " sobre o valor com custo conhecido"));
    root.appendChild(card("Em revisão", String(s.transactions_pending_review), fmt.money(s.pending_review_charged_amount) + " fora dos totais"));
    const notes = clear($("summary-notes"));
    s.notes.forEach((n) => notes.appendChild(el("li", { text: n })));
    if (s.cost_incomplete_transactions) {
      notes.appendChild(el("li", { class: "warn", text: s.cost_incomplete_transactions + " transação(ões) confirmada(s) sem custo completo ficaram fora de custo e margem." }));
    }
    $("period-label").textContent = fmt.day(s.period.date_from) + " a " + fmt.day(s.period.date_to) + " (" + s.period.days + " dia(s), " + s.period.timezone + ")";
  }

  function renderDays(data) {
    const root = clear($("by-day"));
    if (!data) { root.appendChild(el("p", { class: "muted", text: "A série diária aceita até 92 dias. Reduza o período para vê-la." })); return; }
    const days = data.days;
    const max = Math.max(1, ...days.map((d) => d.charged_amount));
    const W = 720, H = 180, pad = 24, bw = Math.max(2, (W - pad * 2) / days.length - 2);
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("class", "chart");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Valor cobrado por dia");
    days.forEach((d, i) => {
      const h = Math.round(((H - pad * 2) * d.charged_amount) / max);
      const rect = document.createElementNS(svgNS, "rect");
      rect.setAttribute("class", "bar");
      rect.setAttribute("x", String(pad + i * ((W - pad * 2) / days.length)));
      rect.setAttribute("y", String(H - pad - h));
      rect.setAttribute("width", String(bw));
      rect.setAttribute("height", String(Math.max(h, d.charged_amount > 0 ? 1 : 0)));
      const title = document.createElementNS(svgNS, "title");
      title.textContent = fmt.day(d.date) + ": " + fmt.money(d.charged_amount) + " (" + d.transactions + " transações)";
      rect.appendChild(title);
      svg.appendChild(rect);
    });
    root.appendChild(svg);
    root.appendChild(el("p", { class: "muted", text: "Valor cobrado por dia (máximo " + fmt.money(max) + "). Passe o mouse sobre as barras." }));
    root.appendChild(el("details", {}, [
      el("summary", { text: "Ver tabela por dia" }),
      table(["Dia", "Transações", "Peso líquido", "Valor cobrado", "Custo estimado", "Margem bruta est."],
        days.map((d) => [fmt.day(d.date), d.transactions, fmt.grams(d.net_weight_g), fmt.money(d.charged_amount), fmt.money(d.food_cost), fmt.money(d.gross_margin)]), ""),
    ]));
  }

  function renderFoods(data) {
    const rows = data.foods.map((f) => [
      f.food_name, f.transactions, fmt.grams(f.weight_g), fmt.pct(f.weight_share_pct), fmt.money(f.known_cost),
      f.average_cost_per_kg === null ? "—" : fmt.money(f.average_cost_per_kg), f.items_without_cost ? f.items_without_cost + " sem custo" : "",
    ]);
    clear($("by-food")).appendChild(table(["Alimento", "Transações", "Peso", "% do peso", "Custo (conhecido)", "Custo médio/kg", "Obs."], rows, "Sem dados no período."));
  }

  function renderReview(r) {
    const root = clear($("review-stats"));
    root.appendChild(card("Transações no período", String(r.transactions), r.pending_review + " em revisão"));
    root.appendChild(card("Revisadas por operador", String(r.reviewed)));
    root.appendChild(card("Com correções", String(r.transactions_with_corrections)));
    root.appendChild(card("Itens do reconhecimento corrigidos", r.recognition_correction_rate_pct === null ? "—" : fmt.pct(r.recognition_correction_rate_pct), r.recognition_items_corrected + " de " + r.recognition_items));
    const reasons = clear($("review-reasons"));
    r.reasons.forEach((x) => reasons.appendChild(el("li", { text: reasonText(x.reason) + ": " + x.transactions })));
    clear($("review-notes")).appendChild(el("p", { class: "muted", text: r.notes.join(" ") }));
  }

  function renderQueue(page) {
    const rows = page.items.map((t) => [
      td(t.code), td(fmt.dateTime(t.created_at)), td(fmt.money(t.charged_amount)),
      el("td", {}, el("ul", { class: "reasons" }, t.review_reasons.map((r) => el("li", { text: reasonText(r) })))),
      el("td", {}, el("a", { class: "button", href: "/review?id=" + encodeURIComponent(t.id), text: "Revisar" })),
    ]);
    const root = clear($("queue"));
    root.appendChild(table(["Código", "Data", "Valor", "Motivos", ""], rows, "Nenhuma transação aguardando revisão."));
    if (page.total > page.items.length) root.appendChild(el("p", { class: "muted", text: "Mostrando " + page.items.length + " de " + page.total + "." }));
  }

  async function load() {
    showMessage(msg, "Carregando…", "info");
    const params = { date_from: $("date-from").value, date_to: $("date-to").value };
    try {
      const summary = await api("/reports/summary", { params });
      const days = summary.period.days <= 92 ? await api("/reports/by-day", { params }) : null;
      const [foods, review, queue] = await Promise.all([
        api("/reports/by-food", { params }), api("/reports/review", { params }),
        api("/transactions", { params: { status: "pending_review", requires_review: "true", limit: 50 } }),
      ]);
      renderSummary(summary); renderDays(days); renderFoods(foods); renderReview(review); renderQueue(queue);
      showMessage(msg, "", "info");
    } catch (error) {
      showMessage(msg, error.message, "error");
    }
  }

  async function exportCsv() {
    try {
      const params = { date_from: $("date-from").value, date_to: $("date-to").value, delimiter: ";" };
      const res = await api("/reports/transactions.csv", { params, raw: true });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = el("a", { href: url, download: "transacoes.csv" });
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      showMessage(msg, error.message, "error");
    }
  }

  window.PC.requireLogin("manager", () => {
    $("filters").addEventListener("submit", (e) => { e.preventDefault(); load(); });
    $("export-csv").addEventListener("click", exportCsv);
    load();
  });
})();
