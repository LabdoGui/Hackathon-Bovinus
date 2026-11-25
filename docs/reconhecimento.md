# Reconhecimento de alimentos

> **Não existe modelo de reconhecimento treinado neste projeto.** O modo padrão (`mock`) gera
> resultados **simulados**, apenas para testar o fluxo completo sem contratar uma API. Os
> alimentos que ele "reconhece" **não refletem a imagem**. Todo resultado simulado traz
> `is_simulated=true` e um aviso (`notice`), e as transações originadas dele vão para revisão.

## Interface

`FoodRecognitionService.recognize(imagem, contexto)` devolve detecções brutas. A interpretação
(proporções que somam 1, pesos estimados que somam o peso líquido, regras de revisão) é feita
depois, igual para qualquer provedor (`app/services/recognition/analysis.py`).

Cada alimento identificado contém: **nome**, **classe**, **confiança**, **área segmentada**
(`segmented_area_px` / `segmented_area_ratio`, quando disponível), **proporção estimada**,
**peso estimado** (proporção × peso líquido, quando há peso) e **origem do resultado**
(`source`: `mock`, `api` ou `local`), além do alimento cadastrado correspondente (`food_id`).

## Modos (`RECOGNITION_MODE`)

### `mock` (padrão): SIMULADO

Determinístico: a mesma imagem sempre gera o mesmo resultado (derivado do hash). Use
`RECOGNITION_MOCK_SCENARIO` para forçar cada situação:

| Cenário | Efeito |
|---------|--------|
| `random` | 2 a 4 alimentos cadastrados, confianças entre 0,62 e 0,99 |
| `confident` | confianças ≥ 0,90 |
| `uncertain` | um alimento com confiança 0,45 → revisão |
| `unknown_food` | inclui um alimento não cadastrado → revisão |
| `empty` | nada reconhecido → revisão |
| `failure` | simula serviço indisponível (503) |

### `api`: API externa

Nenhum fornecedor é presumido. O sistema fala um **contrato próprio ("PratoCusto v1")**; se a sua
API tiver outro formato, escreva um adaptador que o implemente (ou uma subclasse de
`ApiFoodRecognitionService.parse_response`).

Requisição: `POST RECOGNITION_API_URL`, `multipart/form-data`:

* `image`: JPEG;
* `context`: JSON `{"known_classes": [{"recognition_class": "arroz_branco", "name": "Arroz branco"}]}`.

Resposta `200` (JSON):

```json
{
  "model": {"name": "nome-do-modelo", "version": "1.0"},
  "detections": [
    {"recognition_class": "arroz_branco", "name": "Arroz branco", "confidence": 0.93,
     "proportion": 0.6, "segmented_area_px": 123456, "segmented_area_ratio": 0.31},
    {"recognition_class": "feijao_carioca", "confidence": 0.88, "proportion": 0.4}
  ]
}
```

`name`, `proportion` e as áreas são opcionais. Sem `proportion`, as proporções saem das áreas; sem
nenhum dos dois, divide-se igualmente **e** o resultado vai para revisão.

Segurança e privacidade:

* **A imagem do prato é enviada ao serviço externo.** Confirme a política de dados do fornecedor.
* A chave fica só no `.env` (`RECOGNITION_API_KEY`); nunca aparece em logs, erros, status ou
  respostas. O cabeçalho de autenticação é configurável (`RECOGNITION_API_AUTH_HEADER`,
  `RECOGNITION_API_AUTH_SCHEME`).
* HTTPS obrigatório (http só para `localhost`); URL sem usuário/senha; redirecionamentos **não** são
  seguidos; tempo limite e tamanho máximo de resposta; resposta validada estritamente.
* Falhas (rede, 401/403, 5xx, resposta inválida) → 503 com mensagem clara, resultado `failed`
  registrado e orientação para o fluxo manual.

### `local`: estrutura preparada

`LocalFoodRecognitionService` define onde um modelo local seria integrado
(`_load_model`, `_predict`). **Nenhum modelo é fornecido e nada foi implementado**: o serviço
responde 503 `recognition_local_unavailable` e `model_available=false`.

## Quando o resultado vai para revisão humana

`requires_review=true` (e `status=uncertain`) com os motivos:

| Motivo | Quando |
|--------|--------|
| `confianca_baixa` | algum alimento com confiança < `RECOGNITION_MIN_CONFIDENCE` |
| `alimento_desconhecido` | classe não cadastrada em `foods` |
| `nenhum_alimento_reconhecido` | lista vazia |
| `proporcoes_inconsistentes` | soma das proporções fora da tolerância (são normalizadas) |
| `proporcao_nao_informada` | sem proporção nem área (divisão igual) |
| `imagem_com_baixa_qualidade` | captura escura ou desfocada |

Na transação (`POST /transactions/from-recognition`) somam-se `custo_indisponivel` (alimento sem
ficha técnica ou fora do cadastro), `alimento_inativo` e `reconhecimento_simulado` (resultado do
mock, desligável com `RECOGNITION_MOCK_REQUIRES_REVIEW=false`). Transação com qualquer motivo fica
`pending_review`. **A tela/endpoints de correção pelo operador são a Fase 5.**

## Endpoints (`/api/v1/recognition`)

| Método | Caminho | Descrição |
|--------|---------|-----------|
| GET | `/status` | modo, se é simulado, se há modelo real disponível |
| POST | `/analyze` | analisa uma captura (`image_capture_id`; opcional `scale_reading_id` **ou** `net_weight_g`) |
| GET | `/results`, `/results/{id}` | consulta resultados (filtro `image_capture_id`) |
| POST | `/transactions/from-recognition` | cria a transação a partir do resultado + leitura da balança |

## Fluxo completo (mock)

```
POST /camera/captures (ou /camera/uploads)      -> image_capture_id
POST /scale/readings                            -> scale_reading_id
POST /recognition/analyze                       -> recognition_result_id
POST /transactions/from-recognition             -> transação (pending_review se simulada/incerta)
```
