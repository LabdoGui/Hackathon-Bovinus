# Backup e restauração (SQLite)

## O que é copiado

* **Banco de dados** (`data/pratocusto.db`): transações, cadastros, auditoria, operadores
  (chaves só como hash).
* **Não** estão no backup do banco: as **imagens** (`data/images`), o `.env` e os logs. Copie a
  pasta `data\images` e guarde o `.env` em local seguro separadamente (o `.env` pode conter chaves).

Os backups ficam em `data/backups/` com o nome `pratocusto-AAAAMMDD-HHMMSS.db` (hora UTC) e são
**um único arquivo** cada.

## Como o backup é feito

* Usa a API de backup online do SQLite: a cópia é **consistente mesmo com o sistema em uso**
  (diferente de copiar o arquivo `.db`, que pode sair corrompido).
* A cópia é escrita em arquivo temporário, **verificada** (`PRAGMA integrity_check` e versão do
  esquema) e só então renomeada: nunca aparece um backup pela metade.
* **Retenção:** mantém os `BACKUP_KEEP` (14) mais recentes e só apaga arquivos com o nome padrão
  (suas anotações e as cópias `pre-restore-*` nunca são removidas).

## Fazer backup

| Forma | Comando |
|-------|---------|
| Manual (CLI) | `python -m app.cli backup` |
| Windows (script) | `scripts\backup.ps1` |
| API (admin) | `POST /api/v1/admin/backups` — lista em `GET /api/v1/admin/backups` |
| Automático | `BACKUP_INTERVAL_HOURS=24` no `.env` (enquanto o sistema estiver rodando) |
| Agendador do Windows | veja abaixo |

O backup informa tamanho, **SHA-256**, resultado da verificação e a revisão do esquema.

### Agendador de Tarefas do Windows (recomendado)

```powershell
schtasks /Create /SC DAILY /ST 23:30 /TN "PratoCusto Backup" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\PratoCusto\scripts\backup.ps1"
```

Ajuste o caminho. Copie periodicamente `data\backups` para **outro disco ou nuvem**: um backup no
mesmo disco não protege contra falha do disco ou perda do computador.

## Restaurar

1. **Pare o sistema.**
2. Rode (o `--yes` confirma a substituição):

   ```powershell
   python -m app.cli restore data\backups\pratocusto-20261126-233000.db --yes
   ```

3. Inicie o sistema.

O que a restauração faz e garante:

* o banco atual é guardado antes em `data/backups/pre-restore-AAAAMMDD-HHMMSS.db`;
* o arquivo precisa passar na verificação de integridade e ter uma **versão de esquema conhecida**
  (backup de uma versão mais nova do sistema é recusado: atualize o código antes);
* backups de versões mais antigas são aceitos: as migrações rodam na próxima inicialização.

Teste a restauração **de vez em quando** em uma cópia da pasta do projeto: um backup que nunca foi
restaurado é só uma esperança.

## PostgreSQL

O backup automático só existe para SQLite (`POST /admin/backups` responde 422 com PostgreSQL).
Use `pg_dump`/`pg_restore`:

```bash
pg_dump -h localhost -U pratocusto -Fc pratocusto > pratocusto.dump
pg_restore -h localhost -U pratocusto -d pratocusto --clean pratocusto.dump
```

Com Docker: `docker compose exec db pg_dump -U pratocusto -Fc pratocusto > pratocusto.dump`.
