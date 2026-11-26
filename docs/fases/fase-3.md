# Fase 3 — Integração com webcam e captura

## O que foi implementado (`app/services/camera/`)

* **`CameraService`** (OpenCV): captura, pré-visualização (quadro único e MJPEG), seleção de
  dispositivo, listagem de câmeras (sonda índices `0..CAMERA_MAX_PROBE-1`) e liberação segura do
  dispositivo. Backend configurável (`auto`, `dshow`, `msmf`, `v4l2`).
* **Não bloqueia a API**: todo acesso ao hardware ocorre em uma thread dedicada, com tempo limite;
  driver travado gera 503 `camera_timeout` e o dispositivo é liberado.
* **Validação** (`quality.py`): imagem vazia/uniforme e resolução mínima são rejeitadas; imagem
  escura, superexposta ou desfocada é **marcada e avisada** (heurísticas documentadas), não
  rejeitada.
* **Upload manual** como alternativa (`POST /camera/uploads`), com limite de tamanho e de pixels,
  detecção de formato pelo conteúdo, recodificação para JPEG (remove metadados), nome de arquivo
  ignorado e armazenamento com escrita atômica.
* **Registro** na tabela `image_captures` (hash SHA-256, dimensões, brilho, nitidez, origem,
  câmera, operador) e detecção de imagem idêntica (`duplicate_of`).
* **Falhas de hardware**: 503 com mensagem clara e alternativa (`/camera/uploads`), registradas na
  auditoria (`hardware_failure`).
* **Modos**: `webcam`, `upload` (sem câmera) e `mock` (câmera **simulada**, imagem sintética
  marcada "SIMULADO").
* **Página de teste** `/camera` (pré-visualização, captura e upload), para validar a webcam na
  instalação. O painel gerencial completo fica para a Fase 5.

Detalhes e endpoints: [`docs/webcam.md`](../webcam.md). Nenhuma migração nova: a tabela
`image_captures` já existia desde a Fase 1.

## Testes

212 testes no total (54 novos): qualidade de imagem (escura, desfocada, superexposta, vazia, baixa
resolução, canais), upload (formatos por conteúdo, HTML disfarçado, corrompido, gigante, EXIF),
armazenamento (atômico, bloqueio de caminhos fora da raiz), serviço da câmera com dispositivos
falsos (thread dedicada, tempo limite, falha de leitura, listagem, seleção, MJPEG), endpoints
(captura, upload, duplicata, limites, falha 503 + auditoria, permissões, modo `upload`).
Nenhum teste usa webcam física.

Verificações manuais feitas: servidor real com `CAMERA_MODE=mock` e `webcam` (sem hardware),
uploads via `curl`, e a página `/camera` em Chromium headless (captura, prévia MJPEG e upload, sem
erros de console).

## Limitação conhecida

Nesta fase a webcam **física** não foi testada (o ambiente de desenvolvimento não tem câmera).
Depois, a equipe testou o sistema com webcam física, inclusive com a captura automática do prato
(`scripts/auto_capturar.py`). O código usa
a API padrão do OpenCV; por isso há `CAMERA_BACKEND` para contornar diferenças de driver no
Windows. Os limiares de brilho/nitidez são pontos de partida e precisam de ajuste com a
iluminação real do restaurante.
