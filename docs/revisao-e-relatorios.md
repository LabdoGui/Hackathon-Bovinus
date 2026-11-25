# Revisão humana, histórico, relatórios e painel

## Revisão humana de transações

Uma transação fica `pending_review` quando há motivo para conferência (reconhecimento incerto ou
simulado, alimento fora do cadastro, custo desconhecido, alimento inativo...). A fila é
`GET /api/v1/transactions?status=pending_review&requires_review=true`, ou a seção **Fila de
revisão** do painel.

### Corrigir e confirmar — `POST /api/v1/transactions/{id}/review`

Exige a chave (`X-API-Key`) de **qualquer operador**. Só transações `pending_review` (outras → 409).

```json
{
  "reason": "Sobremesa era farofa",
  "items": [
    {"item_id": "<id do item>", "food_id": "<alimento correto>", "weight_g": 300},
    {"item_id": "<id do item>", "food_id": "<alimento correto>", "weight_g": 150},
    {"food_id": "<alimento que faltou>", "weight_g": 20}
  ],
  "confirm": true,
  "notes": "opcional"
}
```

* `reason` é obrigatório (3 a 500 caracteres) e fica na auditoria.
* `items` é a lista **completa** após a correção: itens omitidos são **removidos**; itens sem
  `item_id` são **acrescentados** (`source=manual`). Omita `items` para só confirmar.
* Cada item informa `weight_g` **ou** `proportion` (todos com o mesmo critério).
  * Por peso: a soma deve ficar dentro da tolerância do peso líquido (o maior entre
    `REVIEW_WEIGHT_TOLERANCE_G` e `REVIEW_WEIGHT_TOLERANCE_PCT`%); dentro dela os pesos são
    reescalados para somar exatamente o peso líquido. Se a soma for igual, os pesos digitados
    são mantidos exatamente.
  * Por proporção: a soma deve ser 1 (±0,01).
* `confirm=true` confirma após as correções. Só confirma se todos os itens têm alimento
  cadastrado (`items_without_food`). Sem `confirm`, as correções são salvas e a transação continua
  em revisão (pode haver várias rodadas).
* Custo alimentar, margem bruta alimentar estimada e motivos de revisão são **recalculados** pelo
  motor de cálculo. Peso líquido e valor cobrado não mudam (vêm da balança).

### Valores originais e auditoria

* Na **primeira** correção de um item, ficam gravados `original_food_id/name`,
  `original_proportion` e `original_weight_g`, e `is_corrected=true`. Rodadas seguintes **nunca**
  sobrescrevem os originais. Itens acrescentados têm `is_corrected=true` e `original_*` vazios.
* A **detecção original do reconhecimento** continua intacta em `recognition_results`.
* Cada correção gera um registro `correction` em `audit_logs` com o estado completo **antes** e
  **depois**, a lista de mudanças (`changes`: corrigido, acrescentado, removido, observação), o
  operador e o motivo. A confirmação gera `status_change`. Os registros só são inseridos, nunca
  alterados pela API.
* Consulta: `GET /transactions/{id}/history` e `GET /audit-logs` (filtros `entity_type`,
  `entity_id`, `action`, `created_from`, `created_to`), **gerente/admin**.

## Relatórios (`/api/v1/reports`, gerente/admin)

Parâmetros: `date_from` e `date_to` (datas inclusivas no fuso `APP_TIMEZONE`; padrão: últimos 30
dias; máximo `REPORT_MAX_DAYS`).

| Endpoint | Conteúdo |
|----------|----------|
| `GET /summary` | transações confirmadas / em revisão / canceladas, valor cobrado, peso líquido, ticket médio, custo e margem |
| `GET /by-day` | série diária (até 92 dias), com dias sem vendas zerados |
| `GET /by-food` | peso, participação e custo por alimento |
| `GET /review` | revisões, correções e taxa de correção dos itens do reconhecimento |
| `GET /transactions.csv` | exportação (`status`, `delimiter=,` ou `;`) |

Regras de leitura dos números:

* Totais financeiros usam só transações **confirmadas**; as em revisão aparecem à parte
  (`pending_review_charged_amount`) e **não** entram nos totais.
* **Margem bruta alimentar estimada** = valor cobrado − custo alimentar estimado (fichas
  técnicas). **Não é lucro líquido** (não inclui mão de obra, aluguel, impostos etc.).
* Custo e margem só consideram transações cujos itens têm **todos** custo conhecido
  (`cost_complete_transactions`); as demais ficam fora e são contadas em
  `cost_incomplete_transactions`.
* A taxa de correção mede o ajuste do operador sobre o reconhecimento; com o reconhecimento
  **simulado** (mock) ela não mede a qualidade de um modelo real.
* Somas em `Decimal` (sem erro de ponto flutuante). O CSV é UTF-8 com BOM, datas no fuso local, e
  células de texto que começam com `= + - @` recebem um apóstrofo (proteção contra injeção de
  fórmulas no Excel/Sheets); números negativos legítimos não são alterados.

## Painel gerencial

| Página | Perfil | Conteúdo |
|--------|--------|----------|
| `/dashboard` | gerente/admin | resumo, fila de revisão, gráfico diário, por alimento, estatísticas de revisão, exportar CSV |
| `/review?id=<id>` | qualquer operador | foto do prato, itens editáveis (alimento, peso ou proporção), motivo, salvar/confirmar, histórico |

Como o navegador não envia cabeçalhos personalizados em navegação normal, as páginas são apenas a
"casca": os dados vêm da API com a chave de API que você digita na própria página. A chave fica só
no `sessionStorage` da aba (some ao fechar) e nunca no HTML nem na URL. O histórico completo na
tela de revisão aparece para gerente/admin.

Segurança das páginas: CSP restritiva (`script-src 'self'`, sem inline), nenhum `innerHTML` (todo
texto da API entra com `textContent`), `Cache-Control: no-store`. Verificado no navegador com um
nome de alimento e observação contendo `<script>`/`<img onerror>`: nada é executado.

Criar chaves: `python -m app.cli create-operator --name "Maria" --username maria --role manager`
(perfis: `operator` < `manager` < `admin`).
