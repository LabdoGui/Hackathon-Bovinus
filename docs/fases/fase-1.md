# Fase 1 — Estrutura, configurações, banco de dados e API básica

## O que foi implementado

### Estrutura e configuração
- Projeto organizado em `core`, `api/routes`, `models`, `schemas`, `repositories`, `services`,
  `database`, `templates`, `static`, `utils` e `tests` (na raiz).
- `app/core/config.py`: todas as configurações lidas de variáveis de ambiente / `.env`
  (pydantic-settings), com validação. Modos iniciais: `SCALE_MODE=mock`, `CAMERA_MODE=webcam`,
  `RECOGNITION_MODE=mock`, `DATABASE_MODE=sqlite`. Segredos usam `SecretStr` e não aparecem em
  `repr`/logs.
- Caminhos relativos (`data/`, `logs/`) resolvidos a partir da raiz do projeto.

### Banco de dados
- SQLAlchemy 2 com as 11 entidades: `Food`, `Recipe`, `RecipeIngredient`, `Ingredient`,
  `Transaction`, `TransactionItem`, `RecognitionResult`, `ImageCapture`, `ScaleReading`,
  `Operator`, `AuditLog`.
- Identificadores UUID; datas sempre em UTC com fuso; valores monetários/pesos em `Decimal`
  (`NUMERIC`), sem `float`.
- Relacionamentos, índices, restrições `UNIQUE`, `CHECK` (pesos/custos não negativos, proporção
  entre 0 e 1, rendimento > 0, quantidade líquida ≤ bruta) e chaves estrangeiras com política de
  exclusão explícita (`CASCADE`, `RESTRICT`, `SET NULL`).
- `Transaction.idempotency_key` único (base para evitar transações duplicadas na Fase 2) e
  `code` único legível.
- `TransactionItem` já possui campos `original_*` e `is_corrected` para a revisão humana (Fase 5).
- `RecognitionResult.is_simulated` identifica resultados do modo mock.
- SQLite com `foreign_keys=ON`, WAL e `busy_timeout`. PostgreSQL suportado só por configuração
  (`JSONB`, `TIMESTAMP WITH TIME ZONE`), sem mudar regras de negócio.
- Alembic: migração inicial `0001`, aplicada automaticamente ao iniciar (`DB_AUTO_MIGRATE`).
  Testado: upgrade, downgrade, ausência de diferença entre modelos e migração, e geração do SQL
  para PostgreSQL.
- Seed idempotente com 16 ingredientes, 8 fichas técnicas e 9 alimentos **fictícios**
  (`is_demo=true`, sufixo "(demo)", observação "DADO FICTÍCIO…"). Um alimento propositalmente
  sem ficha técnica ("Sobremesa do dia (demo)") para exercitar o fluxo de custo desconhecido.

### API (`/api/v1`)
| Método | Caminho | Acesso |
|--------|---------|--------|
| GET | `/health` | público |
| GET | `/operators/me` | qualquer operador |
| GET, POST | `/operators` | admin |
| GET | `/ingredients`, `/ingredients/{id}` | público (rede local) |
| POST, PATCH, DELETE | `/ingredients`, `/ingredients/{id}` | gerente ou admin |
| GET | `/recipes`, `/recipes/{id}` | público (rede local) |
| POST, PATCH, DELETE | `/recipes`, `/recipes/{id}` | gerente ou admin |
| GET | `/foods`, `/foods/{id}` (filtros `q`, `active`, `category`) | público (rede local) |
| POST, PATCH, DELETE | `/foods`, `/foods/{id}` | gerente ou admin |

- Listagens paginadas (`limit` 1–200, `offset`) com `total`.
- Exclusão bloqueada (409) quando o registro está em uso; a alternativa é desativar (`active=false`).
- Toda alteração de cadastro gera `AuditLog` com estado antes/depois e operador responsável.
- Erros padronizados: `{"error": {"code", "message", "details"}}`; erros de validação não ecoam
  o valor enviado; erros 500 não expõem detalhes internos.
- OpenAPI em `/docs`, `/redoc` e `/api/v1/openapi.json`, com esquema de segurança `X-API-Key`.

### Segurança já presente
- Chaves de API por operador (`python -m app.cli create-operator`), exibidas uma vez e
  armazenadas apenas como hash SHA-256. Papéis: `operator` < `manager` < `admin`.
- CORS restritivo (origens explícitas, sem `*`, sem credenciais).
- Limite de tamanho do corpo da requisição (413).
- Cabeçalhos `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` e `X-Request-ID`.
- Logs com mascaramento de chaves, senhas, tokens e credenciais em URLs; log de acesso sem
  query string.

### Rotas reservadas
`transactions.py`, `scale.py`, `camera.py`, `recognition.py` e `reports.py` existem sem
endpoints; serão preenchidas nas fases 2 a 5.

## Testes
80 testes em `tests/` cobrindo configuração, persistência (decimais, UTC, restrições, FKs,
cascatas, idempotência), migrações, seed, segurança, endpoints de cadastro e auditoria.

## Decisões a validar
- **Leitura do cadastro sem chave**: listar/consultar alimentos, fichas e ingredientes não exige
  chave (a API escuta só em `127.0.0.1` por padrão). Escrita exige gerente/admin. Pode ser
  endurecido se desejado.
- **Pesos** em gramas com 1 casa decimal; **dinheiro** com 2 casas; **custos unitários** com 4.
- **Ficha técnica**: custo calculado sobre a quantidade **bruta** de cada ingrediente, dividido
  pelo rendimento total da preparação pronta (`yield_weight_g`). Implementação do cálculo na Fase 2.
- `pydantic-settings` foi adicionado (parte do ecossistema Pydantic 2) para ler as variáveis de ambiente.
