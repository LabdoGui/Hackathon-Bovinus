# Webcam USB e captura de imagens

## Modos (`CAMERA_MODE`)

| Modo | Comportamento |
|------|---------------|
| `webcam` | usa a webcam via OpenCV (padrão) |
| `upload` | sem câmera: somente envio manual de imagens |
| `mock` | câmera **simulada** (imagem sintética de um prato, marcada "SIMULADO"); para demonstração e testes |

Com `webcam`, se a câmera não estiver disponível a API responde **503** com mensagem clara e a
falha é registrada na auditoria (`entity_type=hardware`). O **envio manual** (`/camera/uploads`)
continua funcionando em qualquer modo.

## Configurar no Windows

1. Conecte a webcam e feche programas que a usem (Teams, Zoom, app Câmera).
2. Inicie a API e abra **http://127.0.0.1:8000/camera** (página de teste) ou use `/docs`.
3. `GET /api/v1/camera/devices` lista os índices (0, 1, 2…) com resolução. Para trocar de câmera:
   `PUT /api/v1/camera/device` com `{"index": 1}` (gerente/admin) ou defina `CAMERA_DEVICE_INDEX`.
4. Se a câmera não abrir, demorar muito ou mostrar tela preta, teste outro backend no `.env`:
   `CAMERA_BACKEND=dshow` (DirectShow) ou `CAMERA_BACKEND=msmf` (Media Foundation).
5. Ajuste `CAMERA_WIDTH`/`CAMERA_HEIGHT` se o driver não suportar 1280×720.

> A integração com webcam física **não pôde ser testada neste ambiente** (sem hardware). Foi
> testada com câmeras simuladas e falsas. Teste a sua webcam seguindo os passos acima e
> reporte qualquer problema.

## Endpoints (`/api/v1/camera`)

| Método | Caminho | Descrição | Acesso |
|--------|---------|-----------|--------|
| GET | `/status` | modo, câmera selecionada, resolução, último erro | público |
| GET | `/devices` | lista câmeras disponíveis | público |
| PUT | `/device` | seleciona a câmera | gerente/admin |
| GET | `/preview` | um quadro JPEG (reduzido) | público |
| GET | `/preview/stream` | pré-visualização contínua MJPEG (abra no navegador) | público |
| POST | `/captures` | captura da câmera, valida e registra | público* |
| POST | `/uploads` | envio manual (`multipart/form-data`, campo `file`) | público* |
| GET | `/captures`, `/captures/{id}` | lista / consulta | público |
| GET | `/captures/{id}/image` | baixa o JPEG salvo | público |

\* Se uma chave `X-API-Key` for enviada, o operador é registrado na captura.

## Validações e qualidade

* **Imagem vazia ou uniforme** (frame preto, câmera coberta, sem sinal): rejeitada (`image_empty`).
* **Resolução** abaixo de `CAMERA_MIN_WIDTH × CAMERA_MIN_HEIGHT`: rejeitada
  (`image_resolution_too_low`).
* **Escura, superexposta ou desfocada**: **não é rejeitada**; fica marcada (`is_dark`,
  `is_blurry`) e gera `warnings`. Medidas: brilho = média dos tons de cinza (0–255); nitidez =
  variância do Laplaciano. São **heurísticas simples**; ajuste os limiares (`CAMERA_*_THRESHOLD`)
  à iluminação do seu local.
* **Imagem idêntica** a uma captura anterior (mesmo SHA-256): aviso `duplicate_of`.

## Uploads (segurança)

* Limite `MAX_UPLOAD_MB` (413 acima disso) e `CAMERA_MAX_PIXELS`.
* Formato identificado pelo **conteúdo**, não pelo nome nem pelo `Content-Type`; só JPEG, PNG e
  WebP (415 para o resto, inclusive HTML/SVG/GIF/BMP).
* A imagem é decodificada, a orientação EXIF aplicada e **regravada como JPEG**: metadados
  (EXIF/GPS) e conteúdo extra são descartados.
* O nome do arquivo enviado é **ignorado**; os arquivos são salvos como
  `data/images/AAAA/MM/DD/<uuid>.jpg` com escrita atômica, e o download recusa qualquer caminho
  fora dessa pasta.

## Como a API não trava durante a captura

O acesso ao dispositivo roda em uma **thread dedicada da câmera**, com tempo limite
(`CAMERA_TIMEOUT_S`). As rotas são síncronas e executadas pelo pool de threads do FastAPI, então
nem a captura nem a pré-visualização bloqueiam o laço de eventos. Se o driver travar, a requisição
recebe 503 `camera_timeout` em vez de ficar presa.
