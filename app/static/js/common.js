/* Utilitários compartilhados do painel. Todo texto da API entra no DOM via textContent. */
(function () {
  "use strict";

  const API = document.body.dataset.api || "/api/v1";
  const KEY_NAME = "pc_api_key";
  const ROLE_LEVEL = { operator: 10, manager: 20, admin: 30 };

  const REASONS = {
    custo_indisponivel: "Custo indisponível (alimento sem ficha técnica)",
    alimento_inativo: "Alimento inativo",
    confianca_baixa: "Confiança baixa no reconhecimento",
    alimento_desconhecido: "Alimento não cadastrado",
    nenhum_alimento_reconhecido: "Nenhum alimento reconhecido",
    proporcoes_inconsistentes: "Proporções inconsistentes",
    proporcao_nao_informada: "Proporção não informada",
    imagem_com_baixa_qualidade: "Imagem com baixa qualidade",
    reconhecimento_simulado: "Reconhecimento SIMULADO (mock)",
  };
  const STATUS = { confirmed: "Confirmada", pending_review: "Em revisão", cancelled: "Cancelada", draft: "Rascunho" };
  const ACTIONS = {
    create: "Criação", update: "Alteração", delete: "Exclusão", correction: "Correção",
    status_change: "Mudança de status", hardware_failure: "Falha de equipamento/serviço",
  };

  function store() {
    try { return window.sessionStorage; } catch (e) { return null; }
  }
  function getKey() { const s = store(); return s ? s.getItem(KEY_NAME) || "" : ""; }
  function setKey(value) { const s = store(); if (s) s.setItem(KEY_NAME, value); }
  function clearKey() { const s = store(); if (s) s.removeItem(KEY_NAME); }

  class ApiError extends Error {
    constructor(status, body) {
      const e = body && body.error ? body.error : null;
      super(e && e.message ? e.message : "Erro HTTP " + status);
      this.status = status;
      this.code = e ? e.code : null;
      this.details = e ? e.details : null;
    }
  }

  async function api(path, opts) {
    opts = opts || {};
    const headers = {};
    const key = getKey();
    if (key) headers["X-API-Key"] = key;
    let url = API + path;
    if (opts.params) {
      const q = new URLSearchParams();
      Object.entries(opts.params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") q.set(k, v); });
      const qs = q.toString();
      if (qs) url += "?" + qs;
    }
    const init = { method: opts.method || "GET", headers };
    if (opts.form !== undefined) { init.body = opts.form; } // FormData: o navegador define o Content-Type
    else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
    const res = await fetch(url, init);
    if (opts.raw) {
      if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
      return res;
    }
    const data = res.status === 204 ? null : await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(res.status, data);
    return data;
  }

  /* Imagem protegida: <img src> não envia X-API-Key, então busca com fetch e usa uma URL blob:. */
  async function blobUrl(path) {
    const res = await api(path, { raw: true });
    return URL.createObjectURL(await res.blob());
  }

  function el(tag, props, children) {
    const node = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
      if (v === undefined || v === null || v === false) return;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    });
    [].concat(children || []).forEach((c) => {
      if (c === null || c === undefined || c === false) return;
      node.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    });
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

  const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const num1 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const num2 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmt = {
    money: (v) => (v === null || v === undefined ? "—" : brl.format(v)),
    grams: (v) => (v === null || v === undefined ? "—" : num1.format(v) + " g"),
    pct: (v) => (v === null || v === undefined ? "—" : num2.format(v) + " %"),
    ratioPct: (v) => (v === null || v === undefined ? "—" : num1.format(v * 100) + " %"),
    dateTime: (v) => (v ? new Date(v).toLocaleString("pt-BR") : "—"),
    day: (v) => { const p = String(v).split("-"); return p.length === 3 ? p[2] + "/" + p[1] : v; },
  };
  const reasonText = (r) => REASONS[r] || r;

  function showMessage(node, text, kind) {
    node.className = "msg " + (kind || "info");
    node.textContent = text;
    node.hidden = !text;
  }

  /* Tela de acesso: pede a chave de API (guardada só nesta aba) e confere o perfil. */
  async function requireLogin(minRole, onReady) {
    const box = document.getElementById("auth");
    const content = document.getElementById("content");

    function showForm(message) {
      content.hidden = true;
      clear(box);
      const input = el("input", { type: "password", id: "api-key", autocomplete: "off", placeholder: "Chave de API (X-API-Key)", required: true });
      const msg = el("p", { class: "msg error", hidden: !message, text: message || "" });
      const form = el("form", { class: "login" }, [
        el("label", { for: "api-key", text: "Acesso" }), input,
        el("button", { type: "submit", text: "Entrar" }), msg,
      ]);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        setKey(input.value.trim());
        start();
      });
      box.appendChild(form);
      box.hidden = false;
    }

    async function start() {
      if (!getKey()) return showForm("");
      try {
        const me = await api("/operators/me");
        if ((ROLE_LEVEL[me.role] || 0) < (ROLE_LEVEL[minRole] || 0)) {
          clearKey();
          return showForm("Este perfil (" + me.role + ") não tem acesso a esta página.");
        }
        clear(box);
        box.appendChild(el("p", { class: "who" }, [
          "Conectado: ", el("strong", { text: me.name }), " (" + me.role + ") ",
          el("button", { type: "button", class: "link", text: "Sair", onclick: () => { clearKey(); location.reload(); } }),
        ]));
        box.hidden = false;
        content.hidden = false;
        onReady(me);
      } catch (error) {
        clearKey();
        showForm(error.status === 401 ? "Chave inválida ou operador inativo." : error.message);
      }
    }
    start();
  }

  /* Páginas de apoio (ex.: câmera) só pedem chave quando o servidor exige (API_REQUIRE_KEY=true). */
  function startPage(minRole, onReady, options) {
    const needsKey = !(options && options.keyOptional) || document.body.dataset.requireKey === "true";
    if (needsKey) return requireLogin(minRole, onReady);
    document.getElementById("content").hidden = false;
    onReady(null);
  }

  window.PC = { api, blobUrl, ApiError, el, clear, fmt, reasonText, showMessage, requireLogin, startPage, STATUS, ACTIONS, REASONS };
})();
