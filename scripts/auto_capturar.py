"""Captura automática: tira a foto sozinho quando um prato aparece na câmera.

Usa a própria API (o servidor precisa estar rodando): lê quadros de
GET /camera/preview, detecta a chegada de um prato comparando com o fundo
vazio (bandeja/balança sem nada) e, quando o prato para de se mexer, chama
POST /camera/captures (que já salva em PrecoCusto/<mês>/<dia>/).

Máquina de estados:
  VAZIO -> (algo entra) -> ASSENTANDO -> (parado por --estavel s) -> FOTO
        -> AGUARDANDO_SAIDA -> (fundo vazio por --saida s) -> VAZIO

Uso:  .venv\\Scripts\\python.exe scripts\\auto_capturar.py [--debug]
Inicie com a bandeja VAZIA: os primeiros quadros viram o "fundo".
Se disparar à toa ou não disparar, rode com --debug e ajuste --area/--limiar.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

VAZIO, ASSENTANDO, AGUARDANDO_SAIDA = "VAZIO", "ASSENTANDO", "AGUARDANDO_SAIDA"


def buscar_quadro(api: str) -> np.ndarray | None:
    try:
        with urllib.request.urlopen(f"{api}/camera/preview", timeout=10) as resp:
            dados = resp.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        print(f"[aviso] sem quadro da câmera: {exc}", flush=True)
        return None
    img = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    img = cv2.resize(img, (320, int(img.shape[0] * 320 / img.shape[1])), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(img, (7, 7), 0)


def tirar_foto(api: str) -> dict | None:
    req = urllib.request.Request(f"{api}/camera/captures", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"[erro] captura recusada ({exc.code}): {exc.read()[:200]!r}", flush=True)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        print(f"[erro] captura falhou: {exc}", flush=True)
    return None


def aprender_fundo(api: str, n: int, intervalo: float) -> np.ndarray:
    quadros = []
    while len(quadros) < n:
        q = buscar_quadro(api)
        if q is not None:
            quadros.append(q)
        time.sleep(intervalo)
    return np.median(np.stack(quadros), axis=0).astype(np.uint8)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    p.add_argument("--intervalo", type=float, default=0.3, help="segundos entre quadros (0.3)")
    p.add_argument("--limiar", type=int, default=30, help="diferença de brilho (0-255) que conta como 'mudou' (30)")
    p.add_argument("--area", type=float, default=0.08, help="fração da imagem que precisa mudar p/ ser um prato (0.08)")
    p.add_argument("--estavel", type=float, default=1.5, help="segundos parado antes de fotografar (1.5)")
    p.add_argument("--saida", type=float, default=2.0, help="segundos de bandeja vazia p/ rearmar (2.0)")
    p.add_argument("--movimento", type=float, default=3.0, help="diferença média entre quadros considerada 'parado' (3.0)")
    p.add_argument("--debug", action="store_true", help="imprime as métricas a cada quadro")
    a = p.parse_args()

    print("Aprendendo o fundo... deixe a bandeja VAZIA por 3 segundos.", flush=True)
    fundo = aprender_fundo(a.api, 8, a.intervalo)
    print("Pronto. Aguardando prato (Ctrl+C para parar).", flush=True)

    estado, desde, anterior = VAZIO, time.monotonic(), None
    while True:
        t0 = time.monotonic()
        q = buscar_quadro(a.api)
        if q is None:
            time.sleep(1)
            continue

        presente_frac = float(np.mean(cv2.absdiff(q, fundo) > a.limiar))
        presente = presente_frac >= a.area
        movimento = float(np.mean(cv2.absdiff(q, anterior))) if anterior is not None else 99.0
        parado = movimento <= a.movimento
        anterior = q
        agora = time.monotonic()

        if a.debug:
            print(f"{estado:17} presente={presente_frac:5.1%} movimento={movimento:5.2f}", flush=True)

        if estado == VAZIO:
            if presente:
                estado, desde = ASSENTANDO, agora
            else:  # acompanha deriva lenta de iluminação
                fundo = cv2.addWeighted(fundo, 0.98, q, 0.02, 0)
        elif estado == ASSENTANDO:
            if not presente:
                estado = VAZIO
            elif not parado:
                desde = agora  # ainda se mexendo: reinicia a contagem
            elif agora - desde >= a.estavel:
                captura = tirar_foto(a.api)
                if captura:
                    print(f"[foto] prato capturado: {captura.get('export_path') or captura.get('id')}", flush=True)
                estado, desde = AGUARDANDO_SAIDA, agora
        elif estado == AGUARDANDO_SAIDA:
            if presente:
                desde = agora
            elif agora - desde >= a.saida:
                print("[ok] bandeja vazia, pronto para o próximo prato.", flush=True)
                estado = VAZIO

        time.sleep(max(0.0, a.intervalo - (time.monotonic() - t0)))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nEncerrado.")
