# Fase 4 — Reconhecimento mock e interface abstrata para IA

## O que foi implementado (`app/services/recognition/`)

* **`FoodRecognitionService`** (interface abstrata) com três implementações:
  * **`MockFoodRecognitionService`**: **simulado**, determinístico (hash da imagem), com cenários
    (`random`, `confident`, `uncertain`, `unknown_food`, `empty`, `failure`) para exercitar todos os
    fluxos sem API externa. Declara `is_simulated=true`, sem versão de modelo, e a resposta traz aviso.
  * **`ApiFoodRecognitionService`**: cliente HTTP (httpx) para um contrato próprio documentado
    (`docs/reconhecimento.md`); nenhum fornecedor presumido. HTTPS obrigatório, chave só no `.env`,
    sem seguir redirecionamentos, tempo limite, limite de resposta e validação estrita.
  * **`LocalFoodRecognitionService`**: apenas estrutura; informa claramente que **não há modelo**.
* **Dados de cada alimento**: nome, classe, confiança, área segmentada (px e fração, quando
  disponível), proporção estimada, peso estimado, origem do resultado e vínculo com o cadastro.
* **Interpretação independente do provedor** (`analysis.py`, funções puras): une classes repetidas,
  normaliza proporções para somar exatamente 1, deriva proporções das áreas, distribui o peso
  líquido (soma exata) e define motivos de revisão.
* **Encaminhamento à revisão humana** quando incerto: confiança baixa, alimento não cadastrado,
  nada reconhecido, proporções inconsistentes ou ausentes, imagem escura/desfocada.
* **Persistência**: `RecognitionResult` com provedor, modelo, `is_simulated`, status, confiança
  geral, motivos, peso líquido usado, detecções, erro e tempo; falhas registradas (`failed`) e auditadas.
* **Transação a partir do reconhecimento** (`POST /transactions/from-recognition`): itens
  `source=recognition` com confiança; alimentos fora do cadastro entram sem custo; um resultado só
  pode originar uma transação (restrição única + `Idempotency-Key`). Resultados simulados vão para
  revisão (`reconhecimento_simulado`), para dados fictícios nunca virarem venda confirmada.
* **Endpoints**: `GET /recognition/status`, `POST /recognition/analyze`, `GET /recognition/results[/{id}]`.
* **Migração `0003`**: `recognition_results.review_reasons` e `net_weight_g`; unicidade de
  `transactions.recognition_result_id`. Validada em SQLite (subida, descida, ausência de diferenças
  com os modelos) e no SQL gerado para PostgreSQL.

Detalhes: [`docs/reconhecimento.md`](../reconhecimento.md).

## Testes

285 testes no total (73 novos): interpretação (proporções, áreas, normalização, duplicatas, pesos
exatos, motivos de revisão), mock (determinismo, cenários, campos), serviço local (nunca finge ter
modelo), cliente API com servidor simulado (sucesso, cabeçalhos, 401/403/5xx/redirecionamento,
JSON inválido, valores fora de faixa, timeout, erro de conexão, resposta grande demais,
configuração inválida, HTTPS, chave jamais exposta em status/logs/erros) e endpoints (analisar,
cenários, qualidade da imagem, falha 503 + auditoria, fluxo completo até a transação, duplicidade,
idempotência). Sem hardware nem rede externa.

Verificação com servidor real: fluxo mock completo por `curl`, e modo `api` contra um servidor HTTP
local (confirmados multipart, autenticação, classes conhecidas e ausência da chave nos logs).

## Achados corrigidos durante a fase

* Para um resultado **falho** de um provedor simulado, o aviso de simulação ocultava a orientação
  de usar o fluxo manual; agora a orientação de falha tem prioridade.

## Limitações

* Não há modelo real: a identificação de alimentos de verdade exige uma API externa que siga o
  contrato ou um modelo local (a implementar).
* A correção pelo operador (alimentos, proporções, pesos) e o histórico de auditoria dessas
  correções ficam para a **Fase 5**; os campos `original_*` dos itens já existem.
