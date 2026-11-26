# Fase 6 — Testes, segurança, documentação e empacotamento

## Segurança: auditoria e endurecimento

Auditoria do que existia até a Fase 5 encontrou lacunas, todas fechadas e testadas:

| Achado | Correção |
|--------|----------|
| API local alcançável por **DNS rebinding** (site malicioso resolvendo para 127.0.0.1) | Cabeçalho `Host` validado contra `ALLOWED_HOSTS` (400 `invalid_host`) |
| **Escritas entre sites** sem preflight (POST sem corpo na câmera, upload multipart) | Verificação de `Origin` em POST/PUT/PATCH/DELETE (403 `origin_not_allowed`); `Origin: null` recusado |
| **Força bruta** de chaves de API sem limite | Bloqueio por origem após 10 falhas em 5 min (429 + `Retry-After`) |
| Só dava para **criar** operadores | `PATCH /operators/{id}` (nome, perfil, ativo), `POST /operators/{id}/rotate-key`, CLI `rotate-key`/`list-operators`; nunca se remove o último admin |
| Consultas, câmera e fotos **sempre públicas** | `API_REQUIRE_KEY=true` exige chave em tudo (exceto `/health`); páginas buscam imagens com a chave (`blob:`) |
| Sem aviso ao expor na rede | Aviso no log se `HOST` não é local e `API_REQUIRE_KEY=false` |
| Risco de expor rota de escrita por engano | `app/api/inventory.py` classifica cada rota; teste falha se surgir rota de escrita aberta fora da lista documentada |

Análise estática com `ruff` (regras de erro, bugbear, segurança, modernização): sem pendências.
Detalhes e limites: [`docs/seguranca.md`](../seguranca.md).

## Backup e restauração (SQLite)

* `BackupService`: API de backup online do SQLite (consistente com o sistema em uso), arquivo
  temporário → verificação de integridade e de versão do esquema → renomeação atômica; SHA-256;
  retenção (`BACKUP_KEEP`); agendamento opcional (`BACKUP_INTERVAL_HOURS`).
* Acesso: CLI (`backup`, `restore --yes`), script `scripts/backup.ps1` (Agendador do Windows) e API
  (`/admin/backups`, admin, auditado). Restauração guarda cópia do banco atual
  (`pre-restore-*`) e recusa backups corrompidos ou de esquema desconhecido.
* PostgreSQL: resposta 422 clara; usar `pg_dump` ([`docs/backup.md`](../backup.md)).
* **Defeito encontrado e corrigido na verificação real**: o backup herdava o modo WAL do banco e
  deixava arquivos `*.tmp-wal`/`-shm` órfãos (a pasta tinha 11 arquivos em vez de 3). Agora cada
  backup é um arquivo único e há testes de regressão.

## Empacotamento

* `Dockerfile` (Python 3.12, usuário sem privilégios, `HEALTHCHECK`), `.dockerignore` (sem `.env`,
  dados, testes), `docker-compose.yml` (porta só em `127.0.0.1`, `no-new-privileges`,
  `cap_drop: ALL`, volumes) e `docker-compose.postgres.yml` (senha obrigatória, banco sem porta
  publicada).
* Windows: `instalar.bat`/`instalar.ps1`, `iniciar.bat`/`iniciar.ps1`, `scripts/backup.ps1`
  (ASCII por causa do PowerShell 5.1; CRLF garantido por `.gitattributes`).
* `requirements.txt` fixado (inclui `tzdata`), `requirements-postgres.txt`, `requirements-dev.txt`.

## Documentação

`README.md` reescrito; novos: `docs/instalacao-windows.md`, `docs/seguranca.md`, `docs/backup.md`,
`docs/docker.md`, `docs/endpoints.md` (**gerado do código** por `python -m app.cli docs` e conferido
por teste: não fica desatualizado). `docs/balanca-serial.md` cobre a conexão futura de uma balança
real.

## Testes

**407 testes** (76 a mais que na Fase 5), **98% de cobertura** de `app/`. Novos: Host/Origin,
limite de tentativas, `API_REQUIRE_KEY`, gestão de operadores, inventário de rotas e documentação
de endpoints, backup/restauração/agendador/CLI, persistência entre reinícios, **concorrência**
(8 threads disputando a mesma `Idempotency-Key` e a mesma leitura: exatamente 1 transação),
fluxo ponta a ponta, empacotamento (propriedades de segurança do Dockerfile, compose e scripts) e
robustez (falhas de banco, log em arquivo com máscara, entrypoint, SQL de migração para PostgreSQL).

Verificações reais, fora dos testes: servidor com `curl` (Host/Origin/força bruta/retenção/aviso de
exposição) e Chromium (câmera e revisão com `API_REQUIRE_KEY=true`, pedido de chave, prévia e foto
por `blob:`).

## Não verificado (por limitação do ambiente)

* **Webcam e balança físicas.**
* **Execução do Docker** (sem daemon): `docker compose config` valida a sintaxe, mas a imagem não
  foi construída.
* **Scripts PowerShell/BAT** (sem PowerShell no ambiente).
* **PostgreSQL real** (SQL gerado e verificado, sem servidor).
* Painel em celular/tablet.
