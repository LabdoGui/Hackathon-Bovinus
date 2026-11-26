# Endpoints da API (`/api/v1`)

> Arquivo **gerado automaticamente** (`python -m app.cli docs`); não edite à mão. A documentação interativa completa está em `/docs` (Swagger) e `/redoc`.

**Autenticação:** cabeçalho `X-API-Key` (chaves criadas com `python -m app.cli create-operator`). Perfis: `operador` < `gerente` < `admin`.

**Acesso:** *público* = sem chave (a menos que `API_REQUIRE_KEY=true`; então todas as rotas, exceto `/health`, exigem chave); *público + chave opcional* = sem chave funciona, e com chave registra o operador.


## Sistema

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/health` | Verificar saúde da aplicação | público |

## Operadores

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/operators` | Listar operadores (admin) | admin |
| POST | `/api/v1/operators` | Criar operador (admin) | admin |
| GET | `/api/v1/operators/me` | Operador autenticado | operador |
| PATCH | `/api/v1/operators/{operator_id}` | Alterar nome, perfil ou situação (admin) | admin |
| POST | `/api/v1/operators/{operator_id}/rotate-key` | Gerar nova chave de API (admin); a anterior deixa de valer | admin |

## Ingredientes

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/ingredients` | Listar ingredientes | público |
| POST | `/api/v1/ingredients` | Cadastrar ingrediente (gerente/admin) | gerente/admin |
| DELETE | `/api/v1/ingredients/{ingredient_id}` | Excluir ingrediente (gerente/admin) | gerente/admin |
| GET | `/api/v1/ingredients/{ingredient_id}` | Consultar ingrediente | público |
| PATCH | `/api/v1/ingredients/{ingredient_id}` | Alterar ingrediente (gerente/admin) | gerente/admin |

## Fichas técnicas

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/recipes` | Listar fichas técnicas | público |
| POST | `/api/v1/recipes` | Cadastrar ficha técnica (gerente/admin) | gerente/admin |
| DELETE | `/api/v1/recipes/{recipe_id}` | Excluir ficha técnica (gerente/admin) | gerente/admin |
| GET | `/api/v1/recipes/{recipe_id}` | Consultar ficha técnica | público |
| PATCH | `/api/v1/recipes/{recipe_id}` | Alterar ficha técnica (gerente/admin) | gerente/admin |
| GET | `/api/v1/recipes/{recipe_id}/cost` | Custo estimado da ficha técnica | público |

## Alimentos

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/foods` | Listar alimentos | público |
| POST | `/api/v1/foods` | Cadastrar alimento (gerente/admin) | gerente/admin |
| DELETE | `/api/v1/foods/{food_id}` | Excluir alimento (gerente/admin) | gerente/admin |
| GET | `/api/v1/foods/{food_id}` | Consultar alimento | público |
| PATCH | `/api/v1/foods/{food_id}` | Alterar alimento (gerente/admin) | gerente/admin |

## Balança

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/scale/ports` | Listar portas seriais (COM) do computador | público |
| GET | `/api/v1/scale/readings` | Listar leituras recentes | público |
| POST | `/api/v1/scale/readings` | Ler a balança (com estabilização) | público + chave opcional |
| GET | `/api/v1/scale/readings/{reading_id}` | Consultar leitura | público |
| GET | `/api/v1/scale/status` | Status e configuração da balança | público |
| GET | `/api/v1/scale/tare` | Tara padrão atual | público |
| PUT | `/api/v1/scale/tare` | Alterar tara padrão (gerente/admin) | gerente/admin |

## Câmera

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/camera/captures` | Listar capturas | público |
| POST | `/api/v1/camera/captures` | Capturar imagem da câmera | público + chave opcional |
| GET | `/api/v1/camera/captures/{capture_id}` | Consultar captura | público |
| GET | `/api/v1/camera/captures/{capture_id}/image` | Baixar a imagem capturada | público |
| PUT | `/api/v1/camera/device` | Selecionar câmera (gerente/admin) | gerente/admin |
| GET | `/api/v1/camera/devices` | Listar câmeras disponíveis | público |
| GET | `/api/v1/camera/preview` | Pré-visualização: um quadro JPEG | público |
| GET | `/api/v1/camera/preview/stream` | Pré-visualização contínua (MJPEG, abra no navegador) | público |
| GET | `/api/v1/camera/status` | Status e configuração da câmera | público |
| POST | `/api/v1/camera/uploads` | Enviar imagem manualmente (alternativa à câmera) | público + chave opcional |

## Reconhecimento

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| POST | `/api/v1/recognition/analyze` | Reconhecer os alimentos de uma captura | público + chave opcional |
| GET | `/api/v1/recognition/results` | Listar resultados de reconhecimento | público |
| GET | `/api/v1/recognition/results/{result_id}` | Consultar resultado | público |
| GET | `/api/v1/recognition/status` | Status do serviço de reconhecimento | público |

## Transações

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/transactions` | Listar transações | público |
| POST | `/api/v1/transactions` | Registrar transação a partir de uma leitura da balança | público + chave opcional |
| POST | `/api/v1/transactions/from-recognition` | Registrar transação a partir de um resultado de reconhecimento | público + chave opcional |
| POST | `/api/v1/transactions/preview` | Simular cálculo sem gravar | público |
| GET | `/api/v1/transactions/{transaction_id}` | Consultar transação | público |
| POST | `/api/v1/transactions/{transaction_id}/cancel` | Cancelar transação (gerente/admin) | gerente/admin |
| GET | `/api/v1/transactions/{transaction_id}/history` | Histórico de auditoria da transação (gerente/admin) | gerente/admin |
| POST | `/api/v1/transactions/{transaction_id}/review` | Revisar transação: corrigir alimentos, proporções e pesos e/ou confirmar | operador |

## Relatórios

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/reports/by-day` | Série diária (até 92 dias) | gerente/admin |
| GET | `/api/v1/reports/by-food` | Peso e custo por alimento | gerente/admin |
| GET | `/api/v1/reports/review` | Estatísticas de revisão e correções | gerente/admin |
| GET | `/api/v1/reports/summary` | Resumo do período | gerente/admin |
| GET | `/api/v1/reports/transactions.csv` | Exportar transações em CSV | gerente/admin |

## Auditoria

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/audit-logs` | Consultar histórico de auditoria (gerente/admin) | gerente/admin |

## Administração

| Método | Caminho | Descrição | Acesso |
|---|---|---|---|
| GET | `/api/v1/admin/backups` | Listar backups do banco (admin) | admin |
| POST | `/api/v1/admin/backups` | Criar backup consistente do banco SQLite (admin) | admin |
