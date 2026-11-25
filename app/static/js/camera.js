const api = document.body.dataset.api || "/api/v1";
const $ = (id) => document.getElementById(id);

async function loadStatus() {
  try {
    const r = await fetch(`${api}/camera/status`);
    const s = await r.json();
    $("status").textContent = `Modo: ${s.mode} · câmera ${s.device_index} · ${s.enabled ? "habilitada" : "desativada (somente envio manual)"}`
      + (s.last_error ? ` · último erro: ${s.last_error}` : "");
  } catch (e) {
    $("status").textContent = "Não foi possível consultar o status.";
  }
}

function showError(body, fallback) {
  const message = body && body.error ? body.error.message : fallback;
  $("result").textContent = `Erro: ${message}`;
  $("warnings").replaceChildren();
  $("captured").removeAttribute("src");
}

function showCapture(c) {
  $("result").textContent = `Captura ${c.id} · ${c.source} · ${c.width}x${c.height} · brilho ${c.brightness} · nitidez ${c.sharpness}`;
  const items = (c.warnings.length ? c.warnings : ["Sem avisos de qualidade."]).map((w) => {
    const li = document.createElement("li");
    li.textContent = w;
    return li;
  });
  $("warnings").replaceChildren(...items);
  $("captured").src = `${c.image_url}?t=${Date.now()}`;
}

$("start").onclick = () => { $("preview").src = `${api}/camera/preview/stream?t=${Date.now()}`; };
$("stop").onclick = () => { $("preview").removeAttribute("src"); };

$("capture").onclick = async () => {
  $("result").textContent = "Capturando…";
  const r = await fetch(`${api}/camera/captures`, { method: "POST" });
  const body = await r.json().catch(() => null);
  r.ok ? showCapture(body) : showError(body, `HTTP ${r.status}`);
  loadStatus();
};

$("upload-form").onsubmit = async (event) => {
  event.preventDefault();
  const data = new FormData();
  data.append("file", $("file").files[0]);
  $("result").textContent = "Enviando…";
  const r = await fetch(`${api}/camera/uploads`, { method: "POST", body: data });
  const body = await r.json().catch(() => null);
  r.ok ? showCapture(body) : showError(body, `HTTP ${r.status}`);
};

loadStatus();
