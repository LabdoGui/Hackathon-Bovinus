# Docker

> A imagem e o `docker-compose.yml` **não puderam ser construídos/executados** no ambiente de
> desenvolvimento (não havia daemon do Docker). Foram validados estaticamente: sintaxe do compose
> (`docker compose config`), testes automatizados das propriedades de segurança do `Dockerfile` e
> dos arquivos de compose. Se o build falhar no seu computador, reporte a mensagem de erro.

## Quando usar

* **Bom para:** demonstração (balança, reconhecimento e câmera simulados/por upload), servidor,
  testes e uso com PostgreSQL.
* **Não recomendado para:** uso com webcam e balança USB **no Windows**. O Docker Desktop não
  repassa esses dispositivos com facilidade. Nesse caso instale nativamente
  ([instalacao-windows.md](instalacao-windows.md)).
* Em **Linux**, é possível repassar `/dev/video0` e `/dev/ttyUSB0` (veja os comentários
  `devices:` no `docker-compose.yml`; use `CAMERA_MODE=webcam` e `SCALE_MODE=serial`).

## SQLite (padrão)

```bash
cp .env.example .env            # opcional; ajuste (NUNCA versione o .env)
docker compose up --build
docker compose exec app python -m app.cli create-operator --name Admin --username admin --role admin
docker compose exec app python -m app.cli seed          # opcional: dados FICTÍCIOS
```

Abra http://127.0.0.1:8000/dashboard. Dados e logs ficam nos volumes `pratocusto-data` e
`pratocusto-logs` (sobrevivem a `docker compose down`; só somem com `docker compose down -v`).

## PostgreSQL

Defina `POSTGRES_PASSWORD` no `.env` (**obrigatória**, sem valor padrão) e:

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

O banco não publica porta: só o contêiner `app` o alcança. As migrações são aplicadas na
inicialização. Backup: `pg_dump` ([backup.md](backup.md)).

## Backup com SQLite em Docker

```bash
docker compose exec app python -m app.cli backup
docker compose cp app:/app/data/backups ./backups-copia
```

## Características de segurança

* Usuário sem privilégios (`uid 10001`), `no-new-privileges`, `cap_drop: ALL`.
* Porta publicada só em `127.0.0.1:8000`. Para outros equipamentos leia
  [seguranca.md](seguranca.md) (`ALLOWED_HOSTS`, `API_REQUIRE_KEY`, HTTPS).
* `.dockerignore` mantém `.env`, `data/`, `logs/`, `backups/`, `.git`, testes e documentação fora
  da imagem.
* `HEALTHCHECK` consulta `/api/v1/health`.
