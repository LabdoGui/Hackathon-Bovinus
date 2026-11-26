(function () {
  "use strict";
  const { api, blobUrl, clear, el, requireLogin, startPage } = window.PC;
  const $ = (id) => document.getElementById(id);
  let timer = null;
  let lastPreview = null;

  function setImage(img, url) {
    if (img.dataset.blob) URL.revokeObjectURL(img.dataset.blob);
    img.src = url;
    img.dataset.blob = url;
  }

  async function loadStatus() {
    try {
      const s = await api("/camera/status");
      $("status").textContent = "Modo: " + s.mode + " · câmera " + s.device_index + " · " +
        (s.enabled ? "habilitada" : "desativada (somente envio manual)") + (s.last_error ? " · último erro: " + s.last_error : "");
    } catch (e) {
      $("status").textContent = "Não foi possível consultar o status: " + e.message;
    }
  }

  function showError(error) {
    $("result").textContent = "Erro: " + error.message;
    clear($("warnings"));
    $("captured").removeAttribute("src");
  }

  async function showCapture(c) {
    $("result").textContent = "Captura " + c.id + " · " + c.source + " · " + c.width + "x" + c.height +
      " · brilho " + c.brightness + " · nitidez " + c.sharpness;
    const lines = c.warnings.length ? c.warnings : ["Sem avisos de qualidade."];
    clear($("warnings")).append(...lines.map((w) => el("li", { text: w })));
    setImage($("captured"), await blobUrl("/camera/captures/" + encodeURIComponent(c.id) + "/image"));
  }

  /* Pré-visualização por quadros (funciona com ou sem chave de API; ~4 quadros/s). */
  async function previewTick() {
    try {
      setImage($("preview"), await blobUrl("/camera/preview"));
    } catch (e) {
      stopPreview();
      $("status").textContent = "Pré-visualização interrompida: " + e.message;
      return;
    }
    if (timer !== null) timer = setTimeout(previewTick, 250);
  }
  function startPreview() { if (timer === null) { timer = setTimeout(previewTick, 0); } }
  function stopPreview() { if (timer !== null) { clearTimeout(timer); timer = null; } }

  function init() {
    $("start").onclick = startPreview;
    $("stop").onclick = stopPreview;
    $("capture").onclick = async () => {
      $("result").textContent = "Capturando…";
      try { await showCapture(await api("/camera/captures", { method: "POST" })); } catch (e) { showError(e); }
      loadStatus();
    };
    $("upload-form").onsubmit = async (event) => {
      event.preventDefault();
      const form = new FormData();
      form.append("file", $("file").files[0]);
      $("result").textContent = "Enviando…";
      try { await showCapture(await api("/camera/uploads", { method: "POST", form })); } catch (e) { showError(e); }
    };
    loadStatus();
  }

  startPage("operator", init, { keyOptional: true });
})();
