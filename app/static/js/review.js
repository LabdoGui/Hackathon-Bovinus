(function () {
  "use strict";
  const { api, el, clear, fmt, reasonText, STATUS, ACTIONS, showMessage } = window.PC;
  const $ = (id) => document.getElementById(id);
  const msg = $("page-msg");
  const txId = new URLSearchParams(location.search).get("id");

  let tx = null;
  let foods = [];
  let rows = []; // estado editável: { itemId, foodId, value }
  let mode = "weight"; // "weight" (g) | "proportion" (%)
  let dirty = false;

  const foodName = (id) => (foods.find((f) => f.id === id) || {}).name || "—";

  function metaCard(label, value) {
    return el("div", { class: "metric" }, [el("span", { class: "metric-label", text: label }), el("strong", { class: "metric-value", text: value })]);
  }

  function renderHeader() {
    $("tx-title").textContent = tx.code;
    const badge = el("span", { class: "badge " + tx.status, text: STATUS[tx.status] || tx.status });
    clear($("tx-status")).appendChild(badge);
    const root = clear($("tx-meta"));
    root.appendChild(metaCard("Peso líquido", fmt.grams(tx.net_weight_g)));
    root.appendChild(metaCard("Valor cobrado", fmt.money(tx.charged_amount)));
    root.appendChild(metaCard("Custo alimentar estimado", fmt.money(tx.food_cost)));
    root.appendChild(metaCard("Margem bruta alimentar est.", tx.gross_margin === null ? "—" : fmt.money(tx.gross_margin) + " (" + fmt.pct(tx.gross_margin_pct) + ")"));
    const reasons = clear($("tx-reasons"));
    tx.review_reasons.forEach((r) => reasons.appendChild(el("li", { text: reasonText(r) })));
    $("tx-reasons-title").hidden = tx.review_reasons.length === 0;
    const photo = clear($("tx-photo"));
    if (tx.image_capture_id) {
      photo.appendChild(el("img", { class: "preview", alt: "Foto do prato", src: "/api/v1/camera/captures/" + encodeURIComponent(tx.image_capture_id) + "/image" }));
    } else {
      photo.appendChild(el("p", { class: "muted", text: "Sem foto (transação informada manualmente)." }));
    }
  }

  function initRows() {
    rows = tx.items.map((i) => ({ itemId: i.id, foodId: i.food_id || "", weight: i.weight_g, proportion: i.proportion * 100 }));
    dirty = false;
  }

  function foodSelect(row) {
    const select = el("select", { "aria-label": "Alimento" }, [
      el("option", { value: "", text: "— escolha o alimento —" }),
      ...foods.map((f) => el("option", { value: f.id, text: f.name + (f.recipe_id ? "" : " (sem ficha técnica)") })),
    ]);
    select.value = row.foodId;
    select.addEventListener("change", () => { row.foodId = select.value; dirty = true; refreshTotals(); });
    return select;
  }

  function originalText(item) {
    if (!item || !item.is_corrected) return item ? "—" : "novo";
    if (item.original_food_name === null && item.original_weight_g === null) return "acrescentado na revisão";
    return (item.original_food_name || "?") + ": " + fmt.grams(item.original_weight_g) + " (" + fmt.ratioPct(item.original_proportion) + ")";
  }

  function renderItems() {
    const editable = tx.status === "pending_review";
    const body = clear($("items-body"));
    rows.forEach((row, index) => {
      const item = tx.items.find((i) => i.id === row.itemId);
      const input = el("input", { type: "number", min: "0", step: mode === "weight" ? "0.1" : "0.1", "aria-label": "Quantidade", disabled: !editable });
      input.value = mode === "weight" ? row.weight : row.proportion;
      input.addEventListener("input", () => {
        const v = parseFloat(input.value);
        if (mode === "weight") row.weight = isNaN(v) ? 0 : v; else row.proportion = isNaN(v) ? 0 : v;
        dirty = true; refreshTotals();
      });
      const select = foodSelect(row);
      select.disabled = !editable;
      body.appendChild(el("tr", {}, [
        el("td", {}, select),
        el("td", {}, [input, " ", mode === "weight" ? "g" : "%"]),
        el("td", { text: item ? fmt.money(item.cost) : "—" }),
        el("td", { class: "muted", text: item ? (item.confidence !== null ? "conf. " + fmt.ratioPct(item.confidence) + " · " : "") + originalText(item) : "novo" }),
        el("td", {}, editable ? el("button", { type: "button", class: "secondary", text: "Remover", onclick: () => { rows.splice(index, 1); dirty = true; renderItems(); } }) : null),
      ]));
    });
    $("add-item").hidden = !editable;
    refreshTotals();
  }

  function refreshTotals() {
    const total = rows.reduce((acc, r) => acc + (mode === "weight" ? r.weight : r.proportion), 0);
    const target = mode === "weight" ? tx.net_weight_g : 100;
    const unit = mode === "weight" ? " g" : " %";
    const diff = Math.round((total - target) * 10) / 10;
    $("totals").textContent = "Soma: " + total.toFixed(1) + unit + " (esperado " + target.toFixed(1) + unit + (diff ? "; diferença " + diff.toFixed(1) + unit : "") + ")";
    $("totals").className = Math.abs(diff) > (mode === "weight" ? Math.max(5, tx.net_weight_g * 0.02) : 1) ? "msg error" : "msg info";
  }

  function switchMode(next) {
    if (next === mode) return;
    mode = next; renderItems();
  }

  function payloadItems() {
    return rows.map((r) => {
      const item = { food_id: r.foodId };
      if (r.itemId) item.item_id = r.itemId;
      if (mode === "weight") item.weight_g = r.weight; else item.proportion = r.proportion / 100;
      return item;
    });
  }

  async function submit(kind) {
    const reason = $("reason").value.trim();
    if (reason.length < 3) return showMessage(msg, "Informe o motivo da revisão (mínimo 3 caracteres).", "error");
    const body = { reason };
    if (kind !== "confirm-as-is") {
      if (rows.some((r) => !r.foodId)) return showMessage(msg, "Escolha o alimento de todos os itens.", "error");
      if (!rows.length) return showMessage(msg, "A transação precisa de pelo menos um alimento.", "error");
      body.items = payloadItems();
    }
    const notes = $("notes").value.trim();
    if (notes !== (tx.notes || "")) body.notes = notes;
    if (kind !== "save") body.confirm = true;
    showMessage(msg, "Salvando…", "info");
    try {
      tx = await api("/transactions/" + encodeURIComponent(txId) + "/review", { method: "POST", body });
      showMessage(msg, kind === "save" ? "Correções salvas." : "Transação confirmada.", "ok");
      await render();
    } catch (error) {
      showMessage(msg, error.message, "error");
    }
  }

  function renderHistory(entries) {
    const root = clear($("history"));
    const num1 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    if (entries === null) { root.appendChild(el("p", { class: "muted", text: "O histórico completo é visível para gerentes e administradores." })); return; }
    entries.forEach((entry) => {
      const lines = [];
      const num = (v) => num1.format(parseFloat(v));
      const FIELD = {
        food: (v) => "alimento " + v.from + " → " + v.to,
        proportion: (v) => "proporção " + num(v.from * 100) + " % → " + num(v.to * 100) + " %",
        weight_g: (v) => "peso " + num(v.from) + " g → " + num(v.to) + " g",
      };
      ((entry.after || {}).changes || []).forEach((c) => {
        if (c.type === "corrected") lines.push("Corrigido (" + c.food + "): " + Object.entries(c.fields).map(([k, v]) => (FIELD[k] ? FIELD[k](v) : k)).join("; "));
        else if (c.type === "added") lines.push("Acrescentado: " + c.food + " (" + num(c.weight_g) + " g)");
        else if (c.type === "removed") lines.push("Removido: " + c.food + " (" + num(c.weight_g) + " g)");
        else if (c.type === "notes") lines.push("Observação alterada");
      });
      root.appendChild(el("li", {}, [
        el("strong", { text: (ACTIONS[entry.action] || entry.action) + " · " }),
        fmt.dateTime(entry.created_at) + " · " + (entry.operator_username || "sistema"),
        entry.reason ? el("div", { class: "muted", text: "Motivo: " + entry.reason }) : null,
        ...lines.map((l) => el("div", { text: l })),
      ]));
    });
  }

  async function loadHistory() {
    try { renderHistory(await api("/transactions/" + encodeURIComponent(txId) + "/history")); }
    catch (error) { if (error.status === 403) renderHistory(null); else showMessage(msg, error.message, "error"); }
  }

  async function render() {
    renderHeader(); initRows(); renderItems();
    $("notes").value = tx.notes || "";
    const editable = tx.status === "pending_review";
    $("actions").hidden = !editable;
    $("reason-box").hidden = !editable;
    $("readonly-note").hidden = editable;
    if (!editable) {
      $("readonly-note").textContent = tx.status === "confirmed"
        ? "Transação confirmada" + (tx.reviewed_at ? " em " + fmt.dateTime(tx.reviewed_at) : "") + ". Não pode mais ser corrigida."
        : "Transação cancelada.";
    }
    await loadHistory();
  }

  window.PC.requireLogin("operator", async () => {
    if (!txId) return showMessage(msg, "Transação não informada. Abra a partir da fila de revisão no painel.", "error");
    try {
      const page = await api("/foods", { params: { active: "true", limit: 200 } });
      foods = page.items;
      tx = await api("/transactions/" + encodeURIComponent(txId));
      $("tx-section").hidden = false;
      $("mode-weight").addEventListener("change", () => switchMode("weight"));
      $("mode-proportion").addEventListener("change", () => switchMode("proportion"));
      $("add-item").addEventListener("click", () => { rows.push({ itemId: null, foodId: "", weight: 0, proportion: 0 }); dirty = true; renderItems(); });
      $("btn-save").addEventListener("click", () => submit("save"));
      $("btn-save-confirm").addEventListener("click", () => submit("save-confirm"));
      $("btn-confirm").addEventListener("click", () => submit("confirm-as-is"));
      window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
      await render();
    } catch (error) {
      showMessage(msg, error.status === 404 ? "Transação não encontrada." : error.message, "error");
    }
  });
})();
