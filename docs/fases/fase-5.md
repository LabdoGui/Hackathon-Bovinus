# Fase 5 — Revisão humana, histórico e relatórios

## O que foi implementado

* **Revisão humana** (`POST /transactions/{id}/review`): o operador corrige alimentos, proporções e
  pesos (por peso ou por proporção), acrescenta/remove itens e confirma. Custo, margem e motivos de
  revisão são recalculados; os pesos digitados são respeitados exatamente (nova função
  `calculate_plate_from_weights` no motor de cálculo).
* **Valores originais e auditoria**: `original_*` gravados na primeira correção e nunca
  sobrescritos; auditoria `correction`/`status_change` com antes/depois, mudanças, operador e
  motivo; consultas `GET /transactions/{id}/history` e `GET /audit-logs` (gerente/admin).
* **Relatórios** (gerente/admin): resumo, por dia, por alimento, estatísticas de revisão e CSV, em
  `Decimal`, no fuso `APP_TIMEZONE`; margem = margem bruta alimentar estimada (nunca "lucro
  líquido"); custo/margem só de transações com custo completo, informando as excluídas.
* **Painel gerencial** (Jinja2 + JS sem dependências): `/dashboard` e `/review`, com acesso por
  chave de API digitada na página, CSP restritiva, sem `innerHTML`.
* Migração `0004` (`transactions.reviewed_at`, `reviewed_by_id`); dependência `tzdata` (fusos no
  Windows).

Detalhes: [`docs/revisao-e-relatorios.md`](../revisao-e-relatorios.md).

## Testes

331 testes no total (46 novos): revisão (permissões, validações, correção por peso e proporção,
originais preservados em rodadas seguidas, acrescentar/remover, recálculo de custo conferido contra
o motor, tolerâncias, auditoria completa, estados não revisáveis), relatórios (números exatos,
fronteiras de fuso horário, itens sem custo, soma exata de 250 transações, permissões, CSV com
proteção de fórmulas) e páginas (CSP, ausência de script/estilo/handler inline, nenhum
`innerHTML`/`eval`).

Verificado em Chromium contra servidor real: login (perfil insuficiente, chave inválida, gerente),
dashboard com dados reais, exportação CSV autenticada, revisão (trocar alimento, ajustar pesos,
confirmar), histórico, e tentativa de XSS via nome de alimento/observação (não executa; sem
violações de CSP).

## Decisões e limitações

* A tela de revisão por navegador exige digitar a chave; não há login com sessão/cookie (evita
  CSRF e armazenamento persistente de segredo). Pode ser evoluído na Fase 6 se desejado.
* Transações confirmadas não podem mais ser corrigidas (só canceladas por gerente/admin); isso
  mantém o histórico simples e imutável. Se precisar de "reabrir" uma confirmada, é uma extensão.
* A série diária e o painel agregam em Python para manter `Decimal` exato; adequado para o volume
  de um restaurante (centenas de transações/dia), não para milhões de linhas.
* Telefone/tablet: o layout é responsivo, mas o painel não foi testado em dispositivos reais.
