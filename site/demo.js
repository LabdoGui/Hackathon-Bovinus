/* PratoCusto AI — demonstração estática (GitHub Pages).

   Troca o transporte de PC.api por uma API simulada que roda inteira no navegador:
   balança e reconhecimento SIMULADOS, webcam do visitante (opcional, só com permissão)
   e dados fictícios guardados apenas no localStorage deste navegador. Nada é enviado
   para servidor algum. Os cálculos seguem as mesmas regras do motor em Python
   (app/services/calculations/engine.py): pesos em 0,1 g, proporções em 0,0001,
   dinheiro em centavos, arredondamento "meio para cima" e distribuição pelo maior resto. */
(function () {
  "use strict";
  const PC = window.PC;
  const DATA = window.PC_DEMO_DATA;
  if (!PC || !DATA) return;

  const API = document.body.dataset.api || "/api/v1";
  const STORE = "pratocusto.demo.v1";
  const CAM_PREF = "pratocusto.demo.webcam";
  const OFFSET_MS = DATA.utc_offset_minutes * 60000;
  const MIN_WEIGHT_G = 10;
  const MIN_CONFIDENCE = 0.7;
  const NOTICE = "Resultado SIMULADO (modo mock): não existe modelo treinado em uso e os alimentos reconhecidos NÃO " +
    "refletem a imagem. Use apenas para testes e demonstração.";
  const MARGIN_NOTE = "Margem bruta alimentar estimada = valor cobrado − custo alimentar estimado (fichas técnicas). Não é lucro líquido.";
  const COST_NOTE = "Custo e margem consideram apenas transações confirmadas com custo conhecido para todos os itens.";
  const USERS = {
    marina: { id: "8f0f8e5e-5a43-4c1e-9a55-1d1b6b0d0001", username: "marina", name: "Marina (demonstração)", role: "manager", active: true },
    joao: { id: "8f0f8e5e-5a43-4c1e-9a55-1d1b6b0d0002", username: "joao", name: "João (demonstração)", role: "operator", active: true },
  };
  const ME = USERS.marina;
  const FOODS = DATA.foods;
  const foodById = (id) => FOODS.find((f) => f.id === id) || null;

  /* ------------------------------------------------------------ utilidades */
  function local() { try { return window.localStorage; } catch (e) { return null; } }
  function session() { try { return window.sessionStorage; } catch (e) { return null; } }

  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const randInt = (r, a, b) => a + Math.floor(r() * (b - a + 1));
  const pick = (r, list) => list[Math.floor(r() * list.length)];
  const hex = (r, n) => Array.from({ length: n }, () => Math.floor(r() * 16).toString(16)).join("").toUpperCase();
  function uuid(r) {
    const h = Array.from({ length: 32 }, () => Math.floor((r ? r() : Math.random()) * 16).toString(16));
    h[12] = "4"; h[16] = "89ab"[parseInt(h[16], 16) & 3];
    const s = h.join("");
    return s.slice(0, 8) + "-" + s.slice(8, 12) + "-" + s.slice(12, 16) + "-" + s.slice(16, 20) + "-" + s.slice(20);
  }
  const iso = (ms) => new Date(ms).toISOString();
  const localDate = (ms) => new Date(ms + OFFSET_MS).toISOString().slice(0, 10);
  const addDays = (ymd, n) => new Date(Date.parse(ymd + "T00:00:00Z") + n * 86400000).toISOString().slice(0, 10);
  const daysBetween = (a, b) => Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 86400000);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /* ---------------------------------------------- aritmética do motor de cálculo */
  // Arredondamento "meio para cima" (ROUND_HALF_UP) de a / b em inteiros, b > 0.
  function rhu(a, b) {
    const sign = a < 0 ? -1 : 1;
    return sign * Math.floor((2 * Math.abs(a) + b) / (2 * b));
  }
  const toDg = (g) => Math.round(Number(g) * 10); // 0,1 g
  const toE4 = (v) => Math.round(Number(v) * 10000); // 0,0001
  const toCents = (v) => Math.round(Number(v) * 100);

  function apiError(status, code, message, details) {
    const e = new Error(message);
    e.http = { status, body: { error: { code, message, details: details || null } } };
    return e;
  }

  // Método do maior resto: a soma do resultado é exatamente "total" (empates pela ordem).
  function largestRemainder(total, weights) {
    const sum = weights.reduce((a, b) => a + b, 0);
    if (!weights.length) throw apiError(422, "calculation_error", "Informe ao menos um alimento.");
    if (weights.some((w) => w < 0)) throw apiError(422, "calculation_error", "Proporções não podem ser negativas.");
    if (!(sum > 0)) throw apiError(422, "calculation_error", "A soma das proporções deve ser maior que zero.");
    const floors = weights.map((w) => Math.floor((w * total) / sum));
    const rest = weights.map((w, i) => w * total - floors[i] * sum);
    const left = total - floors.reduce((a, b) => a + b, 0);
    const order = weights.map((_, i) => i).sort((i, j) => rest[j] - rest[i] || i - j);
    for (let k = 0; k < left; k++) floors[order[k]] += 1;
    return floors;
  }

  function assemble(tx, propUnits, weightsDg, costsE4) {
    const items = propUnits.map((p, i) => {
      const cost = costsE4[i] === null ? null : rhu(weightsDg[i] * costsE4[i], 1000000);
      return { proportion: p / 10000, weight_g: weightsDg[i] / 10, cost_per_kg: costsE4[i] === null ? null : costsE4[i] / 10000, costCents: cost };
    });
    const known = items.reduce((a, it) => a + (it.costCents || 0), 0);
    const complete = items.every((it) => it.costCents !== null);
    const charged = rhu(toDg(tx.net_weight_g) * toCents(tx.price_per_kg), 10000);
    const margin = complete ? charged - known : null;
    return {
      items: items.map((it) => ({ proportion: it.proportion, weight_g: it.weight_g, cost_per_kg: it.cost_per_kg, cost: it.costCents === null ? null : it.costCents / 100 })),
      charged_amount: charged / 100,
      food_cost: complete ? known / 100 : null,
      cost_complete: complete,
      gross_margin: margin === null ? null : margin / 100,
      gross_margin_pct: margin === null || charged <= 0 ? null : rhu(margin * 10000, charged) / 100,
    };
  }
  const costE4 = (food) => (food && food.cost_per_kg !== null && food.cost_per_kg !== undefined ? toE4(food.cost_per_kg) : null);
  function plateFromProportions(tx, proportions, foods) {
    const units = largestRemainder(10000, proportions.map(toE4));
    return assemble(tx, units, largestRemainder(toDg(tx.net_weight_g), units), foods.map(costE4));
  }
  function plateFromWeights(tx, weightsG, foods) {
    const dg = weightsG.map(toDg);
    return assemble(tx, largestRemainder(10000, dg), largestRemainder(toDg(tx.net_weight_g), dg), foods.map(costE4));
  }

  /* ------------------------------------------------------------------ estado */
  let state = null;

  function save() {
    const store = local();
    if (!store) return;
    for (let attempt = 0; attempt < 6; attempt++) {
      try { store.setItem(STORE, JSON.stringify(state)); return; } catch (e) {
        const ids = Object.keys(state.images);
        if (!ids.length) return;
        delete state.images[ids[0]]; // sem espaço: descarta a foto mais antiga
      }
    }
  }

  function load() {
    const store = local();
    try {
      const raw = store && store.getItem(STORE);
      const parsed = raw ? JSON.parse(raw) : null;
      if (parsed && parsed.version === DATA.data_version && parsed.base_day === localDate(Date.now())) { state = parsed; return; }
    } catch (e) { /* estado corrompido: recomeça */ }
    state = seed();
    save();
  }

  /* ----------------------------------------------------------- cenas simuladas */
  // "Cena" = o prato que a câmera simulada mostra: alimentos e áreas aproximadas.
  function newScene(r) {
    const withCost = FOODS.filter((f) => f.cost_per_kg !== null && f.active);
    const pool = withCost.slice();
    const count = randInt(r, 2, 4);
    const chosen = [];
    while (chosen.length < count && pool.length) chosen.push(pool.splice(Math.floor(r() * pool.length), 1)[0]);
    const noCost = FOODS.filter((f) => f.cost_per_kg === null && f.active);
    if (noCost.length && r() < 0.12) chosen[chosen.length - 1] = pick(r, noCost);
    return {
      seed: Math.floor(r() * 2 ** 31),
      weight_g: Math.round((300 + r() * 420) * 10) / 10,
      foods: chosen.map((f) => ({ food_id: f.id, w: randInt(r, 15, 60) })),
    };
  }

  /* ----------------------------------------------------------- transações */
  function interpret(scene, netG, r) {
    const foods = scene.foods.map((s) => foodById(s.food_id));
    const props = largestRemainder(10000, scene.foods.map((s) => s.w)).map((u) => u / 10000);
    const est = largestRemainder(toDg(netG), props.map(toE4)).map((d) => d / 10);
    const detections = foods.map((f, i) => {
      const confidence = Math.round((0.62 + r() * 0.37) * 10000) / 10000;
      const reasons = confidence < MIN_CONFIDENCE ? ["confianca_baixa"] : [];
      const ratio = Math.round(props[i] * 0.55 * 10000) / 10000;
      return {
        name: f.name, recognition_class: f.recognition_class, confidence, segmented_area_px: Math.round(ratio * 640 * 480),
        segmented_area_ratio: ratio, proportion: props[i], estimated_weight_g: est[i], source: "mock",
        food_id: f.id, matched: true, review_reasons: reasons,
      };
    });
    const reasons = [];
    detections.forEach((d) => d.review_reasons.forEach((x) => { if (!reasons.includes(x)) reasons.push(x); }));
    return { detections, reasons, overall: Math.min(...detections.map((d) => d.confidence)) };
  }

  function createReading(grossG, now, r) {
    r = r || Math.random;
    const gross = Math.round(grossG * 10) / 10;
    const valid = gross >= MIN_WEIGHT_G;
    const reading = {
      id: uuid(r), mode: "mock", gross_weight_g: gross, tare_g: 0, net_weight_g: gross, stable: true,
      device: "simulador no navegador", error: null, created_at: iso(now), min_weight_g: MIN_WEIGHT_G,
      valid_for_transaction: valid, issues: valid ? [] : ["Peso líquido abaixo do mínimo (" + MIN_WEIGHT_G + " g)."],
    };
    state.readings[reading.id] = reading;
    return reading;
  }

  function createRecognition(capture, reading, now, r) {
    r = r || Math.random;
    const scene = capture.scene || newScene(r); // foto real (webcam/upload): alimentos sorteados, como no modo mock
    const net = reading ? reading.net_weight_g : null;
    const it = interpret(scene, net || 0, r);
    if (!net) it.detections.forEach((d) => { d.estimated_weight_g = null; });
    const rec = {
      id: uuid(r), image_capture_id: capture.id, provider: "mock", model_name: "mock-simulador", model_version: null,
      is_simulated: true, status: it.reasons.length ? "uncertain" : "success", overall_confidence: it.overall,
      requires_review: true, review_reasons: it.reasons, net_weight_g: net, detections: it.detections, error: null,
      processing_ms: randInt(r, 180, 420), created_at: iso(now), notice: NOTICE,
    };
    state.recognitions[rec.id] = rec;
    return rec;
  }

  function txCode(now, r) { return "PC-" + localDate(now).replace(/-/g, "") + "-" + hex(r, 6); }

  function createTransaction(rec, reading, priceG, now, r, username) {
    r = r || Math.random;
    const foods = rec.detections.map((d) => foodById(d.food_id));
    const tx = {
      id: uuid(r), code: txCode(now, r), status: "pending_review", operator_id: USERS[username].id,
      scale_reading_id: reading.id, image_capture_id: rec.image_capture_id, recognition_result_id: rec.id,
      gross_weight_g: reading.gross_weight_g, tare_g: reading.tare_g, net_weight_g: reading.net_weight_g,
      price_per_kg: priceG, notes: null, created_at: iso(now), updated_at: iso(now),
      confirmed_at: null, cancelled_at: null, reviewed_at: null, reviewed_by_id: null,
    };
    const calc = plateFromProportions(tx, rec.detections.map((d) => d.proportion), foods);
    tx.items = calc.items.map((c, i) => ({
      id: uuid(r), position: i + 1, food_id: foods[i].id, food_name: foods[i].name, recognition_class: foods[i].recognition_class,
      source: "recognition", confidence: rec.detections[i].confidence, proportion: c.proportion, weight_g: c.weight_g,
      cost_per_kg: c.cost_per_kg, cost: c.cost, is_corrected: false, original_food_id: null, original_food_name: null,
      original_proportion: null, original_weight_g: null,
    }));
    const reasons = calc.cost_complete ? [] : ["custo_indisponivel"];
    rec.review_reasons.forEach((x) => { if (!reasons.includes(x)) reasons.push(x); });
    reasons.push("reconhecimento_simulado"); // RECOGNITION_MOCK_REQUIRES_REVIEW=true
    Object.assign(tx, {
      charged_amount: calc.charged_amount, food_cost: calc.food_cost, gross_margin: calc.gross_margin,
      gross_margin_pct: calc.gross_margin_pct, requires_review: true, review_reasons: reasons,
    });
    state.transactions.push(tx);
    audit(tx.id, "create", username, null, null, { code: tx.code, status: tx.status }, now);
    return tx;
  }

  function audit(txId, action, username, reason, before, after, now) {
    (state.audit[txId] = state.audit[txId] || []).push({
      id: uuid(), created_at: iso(now), entity_type: "transaction", entity_id: txId, action,
      operator_id: USERS[username] ? USERS[username].id : null, operator_username: username, reason, before, after,
    });
  }

  function review(tx, body, now, username) {
    if (tx.status !== "pending_review") {
      throw apiError(409, "transaction_not_reviewable", "Somente transações em revisão podem ser corrigidas ou confirmadas (status atual: " + tx.status + ").");
    }
    const reason = String(body.reason || "").trim();
    if (reason.length < 3) throw apiError(422, "validation_error", "Informe o motivo da revisão (mínimo 3 caracteres).");
    const changes = [];
    if (body.items) changes.push(...applyItems(tx, body.items));
    if (body.notes !== undefined && body.notes !== tx.notes) { changes.push({ type: "notes", from: tx.notes, to: body.notes }); tx.notes = body.notes; }
    if (!changes.length && !body.confirm) throw apiError(422, "business_rule", "Nenhuma alteração em relação ao estado atual da transação.");
    if (changes.length) audit(tx.id, "correction", username, reason, null, { changes }, now);
    if (body.confirm) {
      const before = { status: tx.status, requires_review: tx.requires_review, review_reasons: tx.review_reasons.slice() };
      Object.assign(tx, { status: "confirmed", requires_review: false, confirmed_at: iso(now), reviewed_at: iso(now), reviewed_by_id: USERS[username].id });
      audit(tx.id, "status_change", username, reason, before, { status: "confirmed", requires_review: false, review_reasons: tx.review_reasons.slice() }, now);
    }
    tx.updated_at = iso(now);
    return tx;
  }

  function applyItems(tx, input) {
    if (!input.length) throw apiError(422, "validation_error", "A transação precisa de pelo menos um alimento.");
    const byWeight = input[0].weight_g !== undefined && input[0].weight_g !== null;
    if (input.some((i) => (i.weight_g !== undefined && i.weight_g !== null) !== byWeight)) {
      throw apiError(422, "validation_error", "Use o mesmo critério em todos os itens: só proportion ou só weight_g.");
    }
    const foods = input.map((i) => foodById(i.food_id));
    if (foods.some((f) => !f)) throw apiError(422, "business_rule", "Alimentos não encontrados.");
    const known = new Set(tx.items.map((i) => i.id));
    if (input.some((i) => i.item_id && !known.has(i.item_id))) throw apiError(422, "business_rule", "Itens que não pertencem a esta transação.");
    let calc;
    if (byWeight) {
      const weights = input.map((i) => Number(i.weight_g));
      if (weights.some((w) => !(w > 0))) throw apiError(422, "validation_error", "Os pesos devem ser maiores que zero.");
      const total = weights.reduce((a, b) => a + b, 0);
      const tolerance = Math.max(5, (tx.net_weight_g * 2) / 100);
      if (Math.abs(total - tx.net_weight_g) > tolerance + 1e-9) {
        throw apiError(422, "weights_do_not_match_net", "A soma dos pesos informados (" + total.toFixed(1) + " g) difere do peso líquido (" +
          tx.net_weight_g.toFixed(1) + " g) além da tolerância de " + tolerance.toFixed(1) + " g.");
      }
      calc = plateFromWeights(tx, weights, foods);
    } else {
      const props = input.map((i) => Number(i.proportion));
      const total = props.reduce((a, b) => a + b, 0);
      if (Math.abs(total - 1) > 0.01 + 1e-9) throw apiError(422, "proportions_do_not_sum_one", "A soma das proporções deve ser 1 (±0.01); recebido " + total.toFixed(4) + ".");
      calc = plateFromProportions(tx, props, foods);
    }
    const changes = [];
    const next = [];
    input.forEach((spec, index) => {
      const food = foods[index];
      const res = calc.items[index];
      const item = spec.item_id ? tx.items.find((i) => i.id === spec.item_id) : null;
      if (!item) {
        next.push({
          id: uuid(), position: index + 1, food_id: food.id, food_name: food.name, recognition_class: food.recognition_class, source: "manual",
          confidence: null, proportion: res.proportion, weight_g: res.weight_g, cost_per_kg: res.cost_per_kg, cost: res.cost,
          is_corrected: true, original_food_id: null, original_food_name: null, original_proportion: null, original_weight_g: null,
        });
        changes.push({ type: "added", food: food.name, proportion: res.proportion, weight_g: res.weight_g });
        return;
      }
      const diff = {};
      if (food.id !== item.food_id) diff.food = { from: item.food_name, to: food.name };
      if (res.proportion !== item.proportion) diff.proportion = { from: item.proportion, to: res.proportion };
      if (res.weight_g !== item.weight_g) diff.weight_g = { from: item.weight_g, to: res.weight_g };
      const changed = Object.keys(diff).length > 0;
      if (changed && !item.is_corrected) {
        Object.assign(item, { original_food_id: item.food_id, original_food_name: item.food_name, original_proportion: item.proportion, original_weight_g: item.weight_g });
      }
      Object.assign(item, {
        is_corrected: item.is_corrected || changed, position: index + 1, food_id: food.id, food_name: food.name,
        proportion: res.proportion, weight_g: res.weight_g, cost_per_kg: res.cost_per_kg, cost: res.cost,
      });
      next.push(item);
      if (changed) changes.push({ type: "corrected", item_id: item.id, food: food.name, fields: diff });
    });
    const kept = new Set(next.map((i) => i.id));
    tx.items.filter((i) => !kept.has(i.id)).forEach((i) => changes.push({ type: "removed", item_id: i.id, food: i.food_name, proportion: i.proportion, weight_g: i.weight_g }));
    tx.items = next;
    const reasons = tx.review_reasons.filter((x) => x !== "custo_indisponivel" && x !== "alimento_inativo");
    if (!calc.cost_complete) reasons.push("custo_indisponivel");
    Object.assign(tx, { review_reasons: reasons, charged_amount: calc.charged_amount, food_cost: calc.food_cost, gross_margin: calc.gross_margin, gross_margin_pct: calc.gross_margin_pct });
    return changes;
  }

  /* ----------------------------------------------- histórico fictício inicial */
  function seed() {
    const now = Date.now();
    const today = localDate(now);
    state = {
      version: DATA.data_version, base_day: today, seq: 0, captures: {}, images: {}, readings: {}, recognitions: {},
      transactions: [], audit: {}, idempotency: {}, scene: null,
    };
    const r = rng(20261126);
    const corrections = ["Peso da carne conferido no balcão", "Farofa estava como purê", "Ajuste de proporção do arroz", "Salada maior que o estimado"];
    for (let back = 27; back >= 0; back--) {
      const day = addDays(today, -back);
      const weekday = new Date(Date.parse(day + "T12:00:00Z")).getUTCDay();
      const count = back === 0 ? 4 : weekday === 0 ? randInt(r, 1, 3) : randInt(r, 3, 7);
      for (let k = 0; k < count; k++) {
        let ts = Date.parse(day + "T00:00:00Z") - OFFSET_MS + (11 * 60 + randInt(r, 0, 210)) * 60000;
        if (back === 0) ts = now - (count - k) * randInt(r, 6, 14) * 60000;
        const scene = newScene(r);
        const capture = makeCapture("camera", scene, null, 640, 480, ts, r);
        const reading = createReading(scene.weight_g, ts, r);
        const rec = createRecognition(capture, reading, ts + 900, r);
        const tx = createTransaction(rec, reading, DATA.price_per_kg, ts + 1500, r, "joao");
        if (back === 0 && k >= 1) continue; // ficam na fila de revisão de hoje
        const later = ts + randInt(r, 2, 40) * 60000;
        if (r() < 0.3 && tx.items.length > 1) {
          const items = tx.items.map((i) => ({ item_id: i.id, food_id: i.food_id, weight_g: i.weight_g }));
          const shift = Math.round(items[0].weight_g * (0.1 + r() * 0.2) * 10) / 10;
          items[0].weight_g = Math.round((items[0].weight_g - shift) * 10) / 10;
          items[1].weight_g = Math.round((items[1].weight_g + shift) * 10) / 10;
          if (tx.items.some((i) => i.cost === null)) {
            const swap = FOODS.find((f) => f.cost_per_kg !== null && !tx.items.some((i) => i.food_id === f.id));
            const idx = tx.items.findIndex((i) => i.cost === null);
            if (swap) items[idx].food_id = swap.id;
          }
          review(tx, { reason: pick(r, corrections), items, confirm: true }, later, "marina");
        } else if (tx.items.some((i) => i.cost === null)) {
          continue; // sem ficha técnica: aguarda o gerente
        } else {
          review(tx, { reason: "Conferido no balcão", confirm: true }, later, "joao");
        }
      }
    }
    state.readings = {}; // o histórico fictício não precisa das leituras e resultados intermediários
    state.recognitions = {};
    state.scene = newScene(r);
    return state;
  }

  /* ------------------------------------------------------- imagens simuladas */
  const LOOKS = {
    arroz_branco: ["#F6F2E6", "#E4DCC6"], feijao_carioca: ["#7B4A2C", "#5A3420"], carne_de_panela: ["#6E2F1E", "#8C3F26"],
    frango_grelhado: ["#D9A35A", "#B9792F"], farofa_simples: ["#E2BA74", "#C99A4E"], macarrao_alho_oleo: ["#F2D27A", "#E0B850"],
    pure_batata: ["#F0D27C", "#E0B65A"], salada_verde: ["#4E9A3A", "#D8432C"], sobremesa_do_dia: ["#B8336A", "#F2C6D7"],
  };

  function drawScene(ctx, W, H, scene, label) {
    const r = rng(scene.seed);
    const wood = ctx.createLinearGradient(0, 0, W, H);
    wood.addColorStop(0, "#8A6A4F"); wood.addColorStop(1, "#6E523C");
    ctx.fillStyle = wood; ctx.fillRect(0, 0, W, H);
    ctx.globalAlpha = 0.08;
    for (let y = 0; y < H; y += 7) { ctx.fillStyle = y % 14 ? "#000" : "#fff"; ctx.fillRect(0, y, W, 2); }
    ctx.globalAlpha = 1;
    const cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.42;
    ctx.fillStyle = "rgba(0,0,0,.28)"; ctx.beginPath(); ctx.ellipse(cx + 8, cy + 14, R, R * 0.97, 0, 0, 7); ctx.fill();
    const plate = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.3, R * 0.1, cx, cy, R);
    plate.addColorStop(0, "#FFFFFF"); plate.addColorStop(1, "#E6E2DC");
    ctx.fillStyle = plate; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,.08)"; ctx.lineWidth = R * 0.03; ctx.beginPath(); ctx.arc(cx, cy, R * 0.82, 0, 7); ctx.stroke();
    const total = scene.foods.reduce((a, f) => a + f.w, 0);
    let angle = r() * Math.PI * 2;
    scene.foods.forEach((entry) => {
      const food = foodById(entry.food_id) || {};
      const look = LOOKS[food.recognition_class] || ["#C9B79C", "#A8916F"];
      const share = entry.w / total;
      const mid = angle + share * Math.PI;
      angle += share * Math.PI * 2;
      const dist = scene.foods.length === 1 ? 0 : R * 0.4;
      const bx = cx + Math.cos(mid) * dist, by = cy + Math.sin(mid) * dist;
      const br = R * (0.2 + Math.sqrt(share) * 0.42);
      ctx.fillStyle = look[0];
      for (let k = 0; k < 16; k++) {
        const a = r() * Math.PI * 2, d = r() * br * 0.55;
        ctx.beginPath(); ctx.arc(bx + Math.cos(a) * d, by + Math.sin(a) * d, br * (0.35 + r() * 0.3), 0, 7); ctx.fill();
      }
      ctx.fillStyle = look[1];
      for (let k = 0; k < 70; k++) {
        const a = r() * Math.PI * 2, d = Math.sqrt(r()) * br * 0.8;
        ctx.beginPath(); ctx.ellipse(bx + Math.cos(a) * d, by + Math.sin(a) * d, br * 0.05, br * 0.025, r() * 3, 0, 7); ctx.fill();
      }
    });
    if (label) {
      ctx.fillStyle = "rgba(19,32,47,.72)"; ctx.fillRect(10, H - 34, ctx.measureText(label).width + 22, 24);
      ctx.fillStyle = "#fff"; ctx.font = "600 13px sans-serif"; ctx.fillText(label, 21, H - 17);
    }
  }

  function canvas(w, h) { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; }
  const toBlob = (c, q) => new Promise((resolve) => c.toBlob(resolve, "image/jpeg", q || 0.85));
  function dataUrlToBlob(url) {
    const [head, b64] = url.split(",");
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: head.slice(5, head.indexOf(";")) });
  }

  // Brilho médio (0-255) e nitidez (variância do Laplaciano) numa versão reduzida da imagem.
  function quality(source) {
    const c = canvas(160, 120);
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(source, 0, 0, 160, 120);
    const px = ctx.getImageData(0, 0, 160, 120).data;
    const g = new Float32Array(160 * 120);
    let sum = 0;
    for (let i = 0; i < g.length; i++) { g[i] = 0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2]; sum += g[i]; }
    let n = 0, mean = 0, m2 = 0;
    for (let y = 1; y < 119; y++) for (let x = 1; x < 159; x++) {
      const i = y * 160 + x;
      const lap = g[i - 1] + g[i + 1] + g[i - 160] + g[i + 160] - 4 * g[i];
      n++; const d = lap - mean; mean += d / n; m2 += d * (lap - mean);
    }
    return { brightness: Math.round((sum / g.length) * 100) / 100, sharpness: Math.round((m2 / n) * 100) / 100 };
  }

  /* --------------------------------------------------------------- webcam */
  const cam = { stream: null, video: null, error: null };
  const wantsWebcam = () => { try { return local() && local().getItem(CAM_PREF) === "1"; } catch (e) { return false; } };
  function setWebcam(on) { try { const s = local(); if (s) { if (on) s.setItem(CAM_PREF, "1"); else s.removeItem(CAM_PREF); } } catch (e) { /* opcional */ } }
  function stopWebcam() { if (cam.stream) cam.stream.getTracks().forEach((t) => t.stop()); cam.stream = null; cam.video = null; }

  async function openWebcam() {
    if (cam.video) return cam.video;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("este navegador não oferece acesso à câmera");
    cam.stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
    const video = document.createElement("video");
    video.muted = true; video.playsInline = true; video.srcObject = cam.stream;
    await video.play();
    for (let i = 0; i < 40 && !video.videoWidth; i++) await sleep(50);
    cam.video = video;
    return video;
  }

  // Quadro atual: webcam do visitante (se ele permitiu) ou o prato simulado da cena atual.
  async function frame() {
    if (wantsWebcam()) {
      try {
        const v = await openWebcam();
        const scale = Math.min(1, 960 / v.videoWidth);
        const c = canvas(Math.round(v.videoWidth * scale), Math.round(v.videoHeight * scale));
        c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
        cam.error = null;
        return { canvas: c, scene: null };
      } catch (e) {
        cam.error = e.message || String(e);
        setWebcam(false); stopWebcam(); syncCamButtons();
      }
    }
    const c = canvas(640, 480);
    const clock = new Date().toLocaleTimeString("pt-BR");
    drawScene(c.getContext("2d"), 640, 480, state.scene, "câmera simulada · " + clock);
    return { canvas: c, scene: state.scene };
  }

  function makeCapture(source, scene, dataUrl, width, height, now, r, metrics) {
    state.seq += 1;
    const label = "Prato " + String(state.seq).padStart(4, "0");
    const m = metrics || { brightness: 132.4, sharpness: 210.7 };
    const warnings = [];
    if (m.brightness < 60) warnings.push("Imagem escura: melhore a iluminação.");
    if (m.sharpness < 40) warnings.push("Imagem possivelmente desfocada ou tremida.");
    const capture = {
      id: uuid(r), source, mime_type: "image/jpeg", width, height, size_bytes: dataUrl ? Math.round(dataUrl.length * 0.75) : 48000,
      sha256: hex(r || Math.random, 64).toLowerCase(), brightness: m.brightness, sharpness: m.sharpness, is_dark: m.brightness < 60,
      is_blurry: m.sharpness < 40, device_index: source === "camera" ? 0 : null, created_at: iso(now),
      image_url: API + "/camera/captures/" + "{id}" + "/image", label, export_path: "Pratos/" + label + " (neste navegador)",
      duplicate_of: null, warnings, scene: scene || null,
    };
    capture.image_url = API + "/camera/captures/" + capture.id + "/image";
    state.captures[capture.id] = capture;
    if (dataUrl) state.images[capture.id] = dataUrl;
    return capture;
  }

  async function captureFromCanvas(source, c, scene) {
    const metrics = quality(c);
    let dataUrl = null;
    if (!scene) { // foto real: guarda uma cópia reduzida neste navegador
      const scale = Math.min(1, 640 / c.width);
      const small = canvas(Math.round(c.width * scale), Math.round(c.height * scale));
      small.getContext("2d").drawImage(c, 0, 0, small.width, small.height);
      dataUrl = small.toDataURL("image/jpeg", 0.72);
      const ids = Object.keys(state.images);
      if (ids.length >= 12) delete state.images[ids[0]];
    }
    return makeCapture(source, scene, dataUrl, c.width, c.height, Date.now(), null, metrics);
  }

  async function imageBlob(capture) {
    if (state.images[capture.id]) return dataUrlToBlob(state.images[capture.id]);
    if (capture.scene) {
      const c = canvas(640, 480);
      drawScene(c.getContext("2d"), 640, 480, capture.scene, capture.label + " · simulado");
      return toBlob(c);
    }
    const c = canvas(640, 480);
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#E9E2DA"; ctx.fillRect(0, 0, 640, 480);
    ctx.fillStyle = "#667085"; ctx.font = "600 20px sans-serif"; ctx.textAlign = "center";
    ctx.fillText("Foto não guardada (espaço do navegador)", 320, 240);
    return toBlob(c);
  }

  async function decodeUpload(file) {
    if (!file) throw apiError(422, "validation_error", "Envie um arquivo de imagem.");
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) throw apiError(415, "unsupported_media_type", "Formato não suportado. Use JPEG, PNG ou WebP.");
    if (file.size > 5 * 1024 * 1024) throw apiError(413, "payload_too_large", "Imagem maior que o limite de 5 MB.");
    let bitmap;
    try { bitmap = await createImageBitmap(file); } catch (e) { throw apiError(422, "invalid_image", "Não foi possível ler a imagem enviada."); }
    if (bitmap.width < 64 || bitmap.height < 64) throw apiError(422, "image_too_small", "Imagem muito pequena.");
    const scale = Math.min(1, 1280 / Math.max(bitmap.width, bitmap.height));
    const c = canvas(Math.round(bitmap.width * scale), Math.round(bitmap.height * scale));
    c.getContext("2d").drawImage(bitmap, 0, 0, c.width, c.height);
    return c;
  }

  /* --------------------------------------------------------------- relatórios */
  function period(q) {
    const today = localDate(Date.now());
    const to = q.get("date_to") || today;
    const from = q.get("date_from") || addDays(to, -29);
    if (from > to) throw apiError(422, "business_rule", "date_from não pode ser posterior a date_to.");
    const days = daysBetween(from, to) + 1;
    if (days > 366) throw apiError(422, "report_period_too_long", "Período máximo de 366 dias.");
    return { date_from: from, date_to: to, timezone: DATA.timezone, days };
  }
  const inPeriod = (p) => (tx) => { const d = localDate(Date.parse(tx.created_at)); return d >= p.date_from && d <= p.date_to; };
  const pct = (part, whole) => (whole > 0 ? rhu(part * 10000, whole) / 100 : null);

  function summary(p) {
    const txs = state.transactions.filter(inPeriod(p));
    const confirmed = txs.filter((t) => t.status === "confirmed");
    let net = 0, charged = 0, knownCharged = 0, cost = 0, margin = 0, complete = 0, incomplete = 0;
    confirmed.forEach((t) => {
      net += toDg(t.net_weight_g); charged += toCents(t.charged_amount);
      if (t.food_cost === null) incomplete++;
      else { complete++; knownCharged += toCents(t.charged_amount); cost += toCents(t.food_cost); margin += toCents(t.gross_margin); }
    });
    const pending = txs.filter((t) => t.status === "pending_review");
    const n = confirmed.length;
    return {
      period: p, transactions_confirmed: n, transactions_pending_review: pending.length,
      transactions_cancelled: txs.filter((t) => t.status === "cancelled").length,
      total_net_weight_g: net / 10, total_charged_amount: charged / 100,
      average_ticket: n ? rhu(charged, n) / 100 : null, average_net_weight_g: n ? rhu(net, n) / 10 : null,
      pending_review_charged_amount: pending.reduce((a, t) => a + toCents(t.charged_amount), 0) / 100,
      cost_complete_transactions: complete, cost_incomplete_transactions: incomplete,
      charged_amount_with_known_cost: knownCharged / 100, total_food_cost: cost / 100, total_gross_margin: margin / 100,
      gross_margin_pct: pct(margin, knownCharged), notes: [MARGIN_NOTE, COST_NOTE],
    };
  }

  function byDay(p) {
    if (p.days > 92) throw apiError(422, "report_period_too_long", "A série diária aceita no máximo 92 dias.");
    const buckets = {};
    for (let i = 0; i < p.days; i++) buckets[addDays(p.date_from, i)] = { transactions: 0, net: 0, charged: 0, cost: 0, margin: 0 };
    state.transactions.filter(inPeriod(p)).filter((t) => t.status === "confirmed").forEach((t) => {
      const b = buckets[localDate(Date.parse(t.created_at))];
      b.transactions++; b.net += toDg(t.net_weight_g); b.charged += toCents(t.charged_amount);
      if (t.food_cost !== null) { b.cost += toCents(t.food_cost); b.margin += toCents(t.gross_margin); }
    });
    return {
      period: p, notes: [MARGIN_NOTE, COST_NOTE],
      days: Object.keys(buckets).map((d) => ({
        date: d, transactions: buckets[d].transactions, net_weight_g: buckets[d].net / 10, charged_amount: buckets[d].charged / 100,
        food_cost: buckets[d].cost / 100, gross_margin: buckets[d].margin / 100,
      })),
    };
  }

  function byFood(p) {
    const groups = {};
    state.transactions.filter(inPeriod(p)).filter((t) => t.status === "confirmed").forEach((t) => t.items.forEach((i) => {
      const key = i.food_id || "nome:" + i.food_name;
      const g = groups[key] = groups[key] || { food_id: i.food_id, name: i.food_name, tx: new Set(), w: 0, cost: 0, kw: 0, missing: 0 };
      g.tx.add(t.id); g.w += toDg(i.weight_g);
      if (i.cost === null) g.missing++; else { g.cost += toCents(i.cost); g.kw += toDg(i.weight_g); }
    }));
    const total = Object.values(groups).reduce((a, g) => a + g.w, 0);
    const foods = Object.values(groups).map((g) => ({
      food_id: g.food_id, food_name: g.name, transactions: g.tx.size, weight_g: g.w / 10, weight_share_pct: pct(g.w, total) || 0,
      known_cost: g.cost / 100, items_without_cost: g.missing, average_cost_per_kg: g.kw > 0 ? rhu(g.cost * 10000, g.kw) / 100 : null,
    }));
    foods.sort((a, b) => b.weight_g - a.weight_g || a.food_name.localeCompare(b.food_name));
    return { period: p, foods, notes: ["Considera apenas transações confirmadas.", "Custo de itens sem ficha técnica não é estimado."] };
  }

  function reviewStats(p) {
    const txs = state.transactions.filter(inPeriod(p)).filter((t) => t.status !== "cancelled");
    const reasons = {};
    let recItems = 0, corrected = 0;
    const correctedTx = new Set();
    txs.forEach((t) => {
      new Set(t.review_reasons).forEach((r) => { reasons[r] = (reasons[r] || 0) + 1; });
      t.items.forEach((i) => {
        if (i.is_corrected) correctedTx.add(t.id);
        if (i.source === "recognition") { recItems++; if (i.is_corrected) corrected++; }
      });
    });
    return {
      period: p, transactions: txs.length, from_recognition: txs.filter((t) => t.recognition_result_id).length,
      simulated_recognition: txs.filter((t) => t.review_reasons.includes("reconhecimento_simulado")).length,
      reviewed: txs.filter((t) => t.reviewed_at).length, pending_review: txs.filter((t) => t.status === "pending_review").length,
      transactions_with_corrections: correctedTx.size, recognition_items: recItems, recognition_items_corrected: corrected,
      recognition_correction_rate_pct: pct(corrected, recItems),
      reasons: Object.entries(reasons).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([reason, transactions]) => ({ reason, transactions })),
      notes: ["Taxa de correção mede quanto o operador precisou ajustar os itens do reconhecimento. Com reconhecimento simulado (mock) ela NÃO mede a qualidade de um modelo real."],
    };
  }

  function csv(p, q) {
    const sep = q.get("delimiter") || ";";
    const cell = (v) => {
      if (v === null || v === undefined) return "";
      if (typeof v === "boolean") return v ? "sim" : "não";
      let s = String(v);
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
      return /["\r\n]/.test(s) || s.includes(sep) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const head = ["codigo", "data_hora_local", "status", "peso_bruto_g", "tara_g", "peso_liquido_g", "preco_por_kg", "valor_cobrado",
      "custo_alimentar_estimado", "margem_bruta_alimentar_estimada", "margem_bruta_alimentar_pct", "em_revisao", "motivos_revisao"];
    const status = q.get("status");
    const rows = state.transactions.filter(inPeriod(p)).filter((t) => !status || t.status === status).map((t) => [
      t.code, new Date(Date.parse(t.created_at) + OFFSET_MS).toISOString().slice(0, 19).replace("T", " "), t.status,
      t.gross_weight_g.toFixed(1), t.tare_g.toFixed(1), t.net_weight_g.toFixed(1), t.price_per_kg.toFixed(2), t.charged_amount.toFixed(2),
      t.food_cost === null ? null : t.food_cost.toFixed(2), t.gross_margin === null ? null : t.gross_margin.toFixed(2),
      t.gross_margin_pct === null ? null : t.gross_margin_pct.toFixed(2), t.requires_review, t.review_reasons.join(" | "),
    ]);
    return "﻿" + [head].concat(rows).map((r) => r.map(cell).join(sep)).join("\r\n") + "\r\n";
  }

  /* ----------------------------------------------------------------- rotas */
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const notFound = (what) => apiError(404, "not_found", what + " não encontrada.");

  async function handle(method, path, q, body) {
    let m;
    if (path === "/health" && method === "GET") return json(200, { status: "ok", version: DATA.version, demo: true });
    if (path === "/operators/me") return json(200, ME);

    if (path === "/foods" && method === "GET") {
      let items = FOODS.slice();
      if (q.get("active") === "true") items = items.filter((f) => f.active);
      return json(200, { items, total: items.length, limit: Number(q.get("limit") || 50), offset: 0 });
    }

    if (path === "/scale/status") {
      return json(200, {
        configured_mode: "mock", available_sources: ["mock", "manual"], device: { mode: "mock", device: "simulador no navegador" },
        tare_g: 0, min_weight_g: MIN_WEIGHT_G, stabilization: { samples: 3, tolerance_g: 2, timeout_s: 5, interval_ms: 150 },
        mock_weight_g: state.scene.weight_g, last_error: null,
      });
    }
    if (path === "/scale/readings" && method === "POST") {
      await sleep(350);
      const w = body && body.simulated_weight_g > 0 ? Number(body.simulated_weight_g) : state.scene.weight_g;
      const reading = createReading(w, Date.now());
      save();
      return json(201, reading);
    }

    if (path === "/camera/status") {
      return json(200, {
        mode: wantsWebcam() ? "webcam do navegador" : "simulada", enabled: true, device_index: 0, backend: "navegador",
        opened: Boolean(cam.video), requested_resolution: [1280, 720], last_frame_resolution: null, min_resolution: [64, 64],
        max_upload_mb: 5, last_error: cam.error,
      });
    }
    if (path === "/camera/preview") {
      const f = await frame();
      return new Response(await toBlob(f.canvas, 0.8), { status: 200, headers: { "Content-Type": "image/jpeg" } });
    }
    if (path === "/camera/captures" && method === "POST") {
      await sleep(250);
      const f = await frame();
      const capture = await captureFromCanvas("camera", f.canvas, f.scene);
      save();
      return json(201, capture);
    }
    if (path === "/camera/uploads" && method === "POST") {
      const c = await decodeUpload(body && body.get ? body.get("file") : null);
      const capture = await captureFromCanvas("upload", c, null);
      save();
      return json(201, capture);
    }
    if ((m = path.match(/^\/camera\/captures\/([\w-]+)\/image$/))) {
      const capture = state.captures[m[1]];
      if (!capture) throw notFound("Captura");
      return new Response(await imageBlob(capture), { status: 200, headers: { "Content-Type": "image/jpeg" } });
    }
    if ((m = path.match(/^\/camera\/captures\/([\w-]+)$/))) {
      const capture = state.captures[m[1]];
      if (!capture) throw notFound("Captura");
      return json(200, capture);
    }

    if (path === "/recognition/status") {
      return json(200, {
        mode: "mock", is_simulated: true, model_available: false, model_name: "mock-simulador", min_confidence: "0.70",
        details: { provider: "mock", scenario: "random" }, message: "Reconhecimento SIMULADO (mock): nenhum modelo treinado em uso.",
      });
    }
    if (path === "/recognition/analyze" && method === "POST") {
      await sleep(600);
      const capture = state.captures[body.image_capture_id];
      if (!capture) throw notFound("Captura");
      const reading = body.scale_reading_id ? state.readings[body.scale_reading_id] : null;
      if (body.scale_reading_id && !reading) throw notFound("Leitura");
      const rec = createRecognition(capture, reading || (body.net_weight_g ? { net_weight_g: Number(body.net_weight_g) } : null), Date.now());
      save();
      return json(201, rec);
    }

    if (path === "/transactions/from-recognition" && method === "POST") {
      await sleep(300);
      const key = body.__idempotency;
      if (key && state.idempotency[key]) return json(200, state.transactions.find((t) => t.id === state.idempotency[key]));
      const rec = state.recognitions[body.recognition_result_id];
      const reading = state.readings[body.scale_reading_id];
      if (!rec) throw notFound("Resultado de reconhecimento");
      if (!reading) throw notFound("Leitura");
      if (state.transactions.some((t) => t.scale_reading_id === reading.id)) throw apiError(409, "duplicate_transaction", "Esta leitura da balança já foi usada em outra transação.");
      if (!reading.valid_for_transaction) throw apiError(422, "invalid_reading", "A leitura da balança não é válida para transação.");
      if (!rec.detections.length) throw apiError(422, "no_detections", "O reconhecimento não encontrou alimentos.");
      const price = body.price_per_kg ? Math.round(Number(body.price_per_kg) * 100) / 100 : DATA.price_per_kg;
      if (!(price > 0) || price > 100000) throw apiError(422, "validation_error", "Preço por kg inválido.");
      const tx = createTransaction(rec, reading, price, Date.now(), null, "joao");
      if (key) state.idempotency[key] = tx.id;
      state.scene = newScene(rng(Date.now() % 2147483647)); // o próximo prato chega à balança
      save();
      return json(201, tx);
    }
    if (path === "/transactions" && method === "GET") {
      let items = state.transactions.slice().sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
      if (q.get("status")) items = items.filter((t) => t.status === q.get("status"));
      if (q.get("requires_review")) items = items.filter((t) => String(t.requires_review) === q.get("requires_review"));
      const limit = Number(q.get("limit") || 50), offset = Number(q.get("offset") || 0);
      return json(200, { items: items.slice(offset, offset + limit), total: items.length, limit, offset });
    }
    if ((m = path.match(/^\/transactions\/([\w-]+)\/history$/))) {
      if (!state.transactions.some((t) => t.id === m[1])) throw notFound("Transação");
      return json(200, state.audit[m[1]] || []);
    }
    if ((m = path.match(/^\/transactions\/([\w-]+)\/review$/)) && method === "POST") {
      const tx = state.transactions.find((t) => t.id === m[1]);
      if (!tx) throw notFound("Transação");
      review(tx, body, Date.now(), ME.username);
      save();
      return json(200, tx);
    }
    if ((m = path.match(/^\/transactions\/([\w-]+)$/)) && method === "GET") {
      const tx = state.transactions.find((t) => t.id === m[1]);
      if (!tx) throw notFound("Transação");
      return json(200, tx);
    }

    if (path === "/reports/summary") return json(200, summary(period(q)));
    if (path === "/reports/by-day") return json(200, byDay(period(q)));
    if (path === "/reports/by-food") return json(200, byFood(period(q)));
    if (path === "/reports/review") return json(200, reviewStats(period(q)));
    if (path === "/reports/transactions.csv") {
      return new Response(csv(period(q), q), { status: 200, headers: { "Content-Type": "text/csv; charset=utf-8" } });
    }
    throw apiError(404, "not_available_in_demo", "Este recurso não está disponível na demonstração online. Instale o sistema para usá-lo.");
  }

  PC.transport.fetch = async function (url, init) {
    init = init || {};
    const u = new URL(url, location.href);
    const path = u.pathname.slice(u.pathname.indexOf(API) + API.length);
    let body = init.body;
    if (typeof body === "string") { try { body = JSON.parse(body); } catch (e) { return json(422, { error: { code: "invalid_json", message: "JSON inválido." } }); } }
    const headers = init.headers || {};
    if (body && typeof body === "object" && !(body instanceof FormData) && headers["Idempotency-Key"]) body.__idempotency = headers["Idempotency-Key"];
    try {
      return await handle((init.method || "GET").toUpperCase(), path, u.searchParams, body);
    } catch (e) {
      if (e.http) return json(e.http.status, e.http.body);
      return json(500, { error: { code: "demo_error", message: "Erro na demonstração: " + (e.message || e), details: null } });
    }
  };

  /* --------------------------------------------- botões próprios da demonstração */
  function syncCamButtons() {
    document.querySelectorAll("[data-demo-cam]").forEach((b) => {
      b.textContent = wantsWebcam() ? "Voltar ao prato simulado" : "Usar minha webcam";
    });
    const note = document.getElementById("demo-cam-note");
    if (note) {
      note.textContent = cam.error ? "Não foi possível abrir a webcam (" + cam.error + "). Mostrando o prato simulado."
        : wantsWebcam() ? "Usando a sua webcam: a foto é real, mas o reconhecimento continua simulado. Nada sai do seu navegador."
          : "Câmera simulada. Você pode usar a sua webcam: a imagem fica só no seu navegador.";
      note.className = "notes" + (cam.error ? " warn" : "");
    }
  }

  function addWebcamToggle() {
    const preview = document.getElementById("preview");
    if (!preview) return;
    const card = preview.closest(".card");
    const actions = card && card.querySelector(".actions");
    if (!actions) return;
    const button = PC.el("button", { type: "button", class: "secondary", "data-demo-cam": "1" });
    button.addEventListener("click", () => {
      cam.error = null;
      if (wantsWebcam()) { setWebcam(false); stopWebcam(); } else setWebcam(true);
      syncCamButtons();
    });
    actions.appendChild(button);
    card.appendChild(PC.el("p", { id: "demo-cam-note", class: "notes" }));
    syncCamButtons();
  }

  load();
  const s = session();
  try { if (s && !s.getItem("pc_api_key")) s.setItem("pc_api_key", "demonstracao"); } catch (e) { /* sem login automático */ }
  const reset = document.getElementById("demo-reset");
  if (reset) {
    reset.addEventListener("click", () => {
      if (!window.confirm("Recomeçar a demonstração? Os pratos registrados neste navegador serão apagados.")) return;
      try { const st = local(); if (st) { st.removeItem(STORE); st.removeItem(CAM_PREF); } } catch (e) { /* nada a apagar */ }
      location.reload();
    });
  }
  addWebcamToggle();
  window.addEventListener("pagehide", stopWebcam);
})();
