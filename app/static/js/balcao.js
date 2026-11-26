/* Balcão: pesa, fotografa, reconhece e registra o prato num clique. */
(function () {
  "use strict";
  const PC = window.PC;
  const { api, blobUrl, el, clear, fmt, reasonText, STATUS, showMessage, startPage } = PC;
  const $ = (id) => document.getElementById(id);
  const msg = $("page-msg");
  const PRICE_STORE = "pratocusto.balcao.preco";
  const num1 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  let timer = null;
  let scale = null;
  let busy = false;

  function local() { try { return window.localStorage; } catch (e) { return null; } }

  /* Chave de idempotência por clique: reenvios do mesmo registro não duplicam a transação. */
  function newKey() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  function setImage(img, url) {
    if (img.dataset.blob) URL.revokeObjectURL(img.dataset.blob);
    img.src = url;
    img.dataset.blob = url;
  }

  /* ----------------------------------------------------------- câmera */
  async function previewTick() {
    try {
      setImage($("preview"), await blobUrl("/camera/preview"));
    } catch (e) {
      stopPreview();
      $("device-info").textContent = "Pré-visualização indisponível: " + e.message;
      return;
    }
    if (timer !== null) timer = setTimeout(previewTick, 300);
  }
  function startPreview() {
    if (timer === null) timer = setTimeout(previewTick, 0);
    $("toggle-preview").textContent = "Pausar câmera";
  }
  function stopPreview() {
    if (timer !== null) { clearTimeout(timer); timer = null; }
    $("toggle-preview").textContent = "Ligar câmera";
  }

  /* ----------------------------------------------------------- balança */
  function showReading(r) {
    $("weight").textContent = r.net_weight_g === null ? "—" : num1.format(r.net_weight_g);
    $("weight-status").textContent = !r.valid_for_transaction ? "leitura inválida" : r.stable ? "estável" : "instável";
  }

  function readingBody() {
    const body = {};
    const sim = parseFloat($("sim-weight").value);
    if (scale && scale.configured_mode === "mock" && sim > 0) body.simulated_weight_g = sim;
    return body;
  }

  async function readScale() {
    $("weight-status").textContent = "lendo…";
    try {
      const r = await api("/scale/readings", { method: "POST", body: readingBody() });
      showReading(r);
      if (!r.valid_for_transaction) showMessage(msg, (r.issues || []).join(" ") || r.error || "Leitura inválida.", "error");
      else showMessage(msg, "", "info");
    } catch (e) {
      $("weight-status").textContent = "";
      showMessage(msg, e.message, "error");
    }
  }

  async function loadStatus() {
    const parts = [];
    try {
      scale = await api("/scale/status");
      parts.push("Balança: " + scale.configured_mode + " · tara " + fmt.grams(scale.tare_g) + " · mínimo " + fmt.grams(scale.min_weight_g));
      $("sim-box").hidden = scale.configured_mode !== "mock";
      $("sim-weight").placeholder = num1.format(scale.mock_weight_g);
    } catch (e) {
      parts.push("Balança: status indisponível (" + e.message + ")");
    }
    try {
      const cam = await api("/camera/status");
      parts.push("Câmera: " + cam.mode + (cam.enabled ? "" : " (desativada)"));
    } catch (e) {
      parts.push("Câmera: status indisponível");
    }
    try {
      const rec = await api("/recognition/status");
      $("rec-badge").textContent = rec.is_simulated ? "Reconhecimento simulado" : "Reconhecimento: " + (rec.model_name || rec.mode);
      $("rec-badge").className = "badge" + (rec.is_simulated ? " sim" : "");
      $("rec-badge").hidden = false;
    } catch (e) { /* o selo é só informativo */ }
    $("device-info").textContent = parts.join(" · ");
  }

  /* ----------------------------------------------------------- registro */
  function step(name, state, text) {
    const li = document.querySelector('#steps [data-step="' + name + '"]');
    li.className = state;
    if (text) li.textContent = text;
  }
  function resetSteps() {
    step("scale", "", "Ler a balança (peso estável)");
    step("photo", "", "Fotografar o prato");
    step("recognition", "", "Reconhecer os alimentos");
    step("transaction", "", "Calcular e registrar a transação");
  }

  function metric(label, value, hint) {
    return el("div", { class: "metric" }, [
      el("span", { class: "metric-label", text: label }),
      el("strong", { class: "metric-value", text: value }),
      hint ? el("span", { class: "metric-hint", text: hint }) : null,
    ]);
  }

  function renderResult(tx, rec, capture) {
    $("r-code").textContent = tx.code;
    clear($("r-status")).appendChild(el("span", { class: "badge " + tx.status, text: STATUS[tx.status] || tx.status }));
    $("r-charged").textContent = fmt.money(tx.charged_amount);
    $("r-sub").textContent = fmt.grams(tx.net_weight_g) + " líquido × " + fmt.money(tx.price_per_kg) + "/kg";
    const metrics = clear($("r-metrics"));
    metrics.appendChild(metric("Custo alimentar estimado", fmt.money(tx.food_cost), tx.food_cost === null ? "há alimento sem ficha técnica" : null));
    metrics.appendChild(metric("Margem bruta alimentar est.", fmt.money(tx.gross_margin), tx.gross_margin_pct === null ? null : fmt.pct(tx.gross_margin_pct) + " do valor"));
    const body = clear($("r-items"));
    tx.items.forEach((i) => body.appendChild(el("tr", {}, [
      el("td", { text: i.food_name }), el("td", { text: fmt.grams(i.weight_g) }), el("td", { text: fmt.ratioPct(i.proportion) }),
      el("td", { text: fmt.money(i.cost) }), el("td", { text: i.confidence === null ? "—" : fmt.ratioPct(i.confidence) }),
    ])));
    const reasons = clear($("r-reasons"));
    if (tx.review_reasons.length) reasons.appendChild(el("li", { class: "warn", text: "Foi para a fila de revisão: " + tx.review_reasons.map(reasonText).join("; ") + "." }));
    $("r-notice").textContent = rec.notice || "";
    $("r-notice").hidden = !rec.notice;
    const link = $("r-review");
    link.hidden = tx.status !== "pending_review";
    link.href = PC.pageUrl("review", { id: tx.id });
    const photo = $("r-photo");
    photo.removeAttribute("src");
    blobUrl("/camera/captures/" + encodeURIComponent(capture.id) + "/image").then((url) => setImage(photo, url)).catch(() => {});
    $("result-card").hidden = false;
  }

  async function register() {
    if (busy) return;
    busy = true;
    $("register").disabled = true;
    $("result-card").hidden = true;
    resetSteps();
    showMessage(msg, "", "info");
    const price = $("price").value.trim();
    const store = local();
    if (store) { try { if (price) store.setItem(PRICE_STORE, price); else store.removeItem(PRICE_STORE); } catch (e) { /* opcional */ } }
    let current = "scale";
    try {
      step("scale", "run", "Lendo a balança…");
      const reading = await api("/scale/readings", { method: "POST", body: readingBody() });
      showReading(reading);
      if (!reading.valid_for_transaction) {
        throw new Error("Leitura inválida: " + ((reading.issues || []).join(" ") || reading.error || "verifique a balança."));
      }
      step("scale", "done", "Balança: " + fmt.grams(reading.net_weight_g) + " líquido (tara " + fmt.grams(reading.tare_g) + ")");

      current = "photo";
      step("photo", "run", "Fotografando…");
      const capture = await api("/camera/captures", { method: "POST" });
      const warn = capture.warnings.length ? " · " + capture.warnings.length + " aviso(s) de qualidade" : "";
      step("photo", "done", "Foto: " + (capture.label || "capturada") + warn);

      current = "recognition";
      step("recognition", "run", "Reconhecendo os alimentos…");
      const rec = await api("/recognition/analyze", {
        method: "POST", body: { image_capture_id: capture.id, scale_reading_id: reading.id },
      });
      if (rec.error) throw new Error(rec.error);
      step("recognition", "done", "Reconhecimento" + (rec.is_simulated ? " simulado" : "") + ": " + rec.detections.length + " alimento(s)");

      current = "transaction";
      step("transaction", "run", "Calculando e registrando…");
      const body = { recognition_result_id: rec.id, scale_reading_id: reading.id };
      if (price) body.price_per_kg = parseFloat(price);
      const tx = await api("/transactions/from-recognition", { method: "POST", body, headers: { "Idempotency-Key": newKey() } });
      step("transaction", "done", "Transação " + tx.code + " · " + (STATUS[tx.status] || tx.status));
      renderResult(tx, rec, capture);
    } catch (e) {
      step(current, "fail", e.message);
      showMessage(msg, e.message, "error");
    } finally {
      busy = false;
      $("register").disabled = false;
    }
  }

  function init() {
    const store = local();
    try { const saved = store && store.getItem(PRICE_STORE); if (saved) $("price").value = saved; } catch (e) { /* opcional */ }
    $("register").addEventListener("click", register);
    $("read-scale").addEventListener("click", readScale);
    $("toggle-preview").addEventListener("click", () => (timer === null ? startPreview() : stopPreview()));
    $("r-new").addEventListener("click", () => { $("result-card").hidden = true; resetSteps(); window.scrollTo({ top: 0, behavior: "smooth" }); });
    loadStatus();
    startPreview();
  }

  startPage("operator", init, { keyOptional: true });
})();
