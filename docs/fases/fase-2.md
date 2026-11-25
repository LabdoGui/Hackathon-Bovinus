# Fase 2 — Simulador de balança e motor de cálculo

## Balança (`app/services/scale/`)

* **`ScaleService`** (interface abstrata) com `read_sample()` e três implementações:
  * **`MockScaleService`**: simulador determinístico. Ao "colocar o prato", as primeiras leituras
    oscilam com amplitude decrescente e depois estabilizam. Resolução configurável.
  * **`SerialScaleService`**: PySerial com porta COM, baud rate, bits de dados, paridade, bits de
    parada, tempo limite, modo `continuous` ou `request`, comando, terminador e interpretação por
    expressões regulares. **Nenhum protocolo de fabricante foi presumido.** A porta é aberta só na
    primeira leitura; falhas fecham a porta para reabrir na próxima.
  * **`ManualScaleService`**: peso digitado pelo operador (contingência).
* **Estabilização** (`read_stable`): N leituras consecutivas dentro da tolerância, com tempo limite.
  Se a balança informar instabilidade, a janela recomeça. O peso final é a última leitura (igual ao
  visor), sem médias.
* **Peso mínimo** e **tara configurável** (padrão no `.env`, alterável por `PUT /scale/tare` e por
  leitura).
* **`ScaleManager`**: escolhe a fonte (configurada, `mock` ou `manual`), serializa o acesso ao
  hardware e mantém o simulador disponível quando a balança real falha.
* **Falhas de hardware**: resposta 503 com mensagem clara e fontes alternativas; registro da leitura
  com erro e entrada de auditoria `hardware_failure`.
* **Não bloqueio**: as rotas de leitura são síncronas e o FastAPI as executa em pool de threads, sem
  travar o laço de eventos.

## Motor de cálculo (`app/services/calculations/engine.py`)

Funções puras, independentes de banco, balança, câmera e reconhecimento:

| Função | Regra |
|--------|-------|
| `net_weight` | peso líquido = peso bruto − tara (erro se a tara for maior) |
| `normalize_proportions` | proporções somando exatamente 1,0000 |
| `distribute_weight` | distribui o peso líquido pelo **método do maior resto**: a soma dos pesos é exatamente o peso líquido (0,1 g) |
| `recipe_cost` | custo da ficha = Σ(quantidade bruta × custo unitário); custo/kg = custo ÷ rendimento |
| `correction_factor` | fator de correção = bruto ÷ líquido |
| `item_cost` | peso do item (kg) × custo/kg da preparação |
| `charged_amount` | valor cobrado = peso líquido (kg) × preço/kg |
| `gross_food_margin` | margem bruta alimentar estimada = valor cobrado − custo alimentar (R$ e %) |
| `calculate_plate` | combina tudo para um prato |

Arredondamento ROUND_HALF_UP: pesos 0,1 g; proporções 0,0001; custo/kg R$ 0,0001; valores R$ 0,01.
O termo usado é **margem bruta alimentar estimada** (não é lucro líquido).

## Transações

* `POST /transactions` a partir de uma leitura da balança válida (estável, acima do peso mínimo,
  com no máximo `SCALE_READING_MAX_AGE_S` segundos de idade e ainda não usada).
* Itens informados manualmente nesta fase (`food_id` + `proportion`); o reconhecimento automático
  entra na Fase 4.
* Custos fotografados no momento (`cost_per_kg` e `cost` em cada item); mudanças futuras nas fichas
  não alteram transações antigas.
* **Revisão humana**: alimento sem ficha técnica (`custo_indisponivel`) ou inativo
  (`alimento_inativo`) gera `status=pending_review`; caso contrário `confirmed`. As telas de
  correção ficam para a Fase 5.
* **Duplicidade**: cabeçalho opcional `Idempotency-Key` (reenvio com o mesmo conteúdo devolve a
  transação existente com 200; com conteúdo diferente, 409) e restrição única de leitura por
  transação (migração `0002`).
* `POST /transactions/preview` calcula sem gravar; `POST /transactions/{id}/cancel` (gerente/admin).
* `GET /recipes/{id}/cost`: custo detalhado da ficha técnica.

## Novos endpoints

| Método | Caminho | Acesso |
|--------|---------|--------|
| GET | `/scale/status`, `/scale/ports`, `/scale/tare` | público (rede local) |
| PUT | `/scale/tare` | gerente/admin |
| POST | `/scale/readings` | público (operador registrado se enviar chave) |
| GET | `/scale/readings`, `/scale/readings/{id}` | público (rede local) |
| POST | `/transactions/preview`, `/transactions` | público (operador registrado se enviar chave) |
| GET | `/transactions` (filtros `status`, `requires_review`, `created_from`, `created_to`), `/transactions/{id}` | público (rede local) |
| POST | `/transactions/{id}/cancel` | gerente/admin |
| GET | `/recipes/{id}/cost` | público (rede local) |

## Testes

158 testes no total (78 novos): cálculo de peso líquido, distribuição (500 casos aleatórios
conferindo soma exata), custo, margem, arredondamentos, simulador, estabilização, interpretação
serial, porta serial simulada (sem hardware), falha de hardware com alternativa mock, endpoints da
balança, criação de transações, idempotência, validações e cancelamento.

Correção feita durante a fase: `SCALE_SERIAL_BYTESIZE` e `SCALE_SERIAL_STOPBITS` não eram aceitos
quando lidos do `.env` (texto). Agora há um teste que carrega o `.env.example` completo.

## Conectar a balança real

Ver [`docs/balanca-serial.md`](../balanca-serial.md).
