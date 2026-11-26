"""Comandos administrativos.

Uso:
    python -m app.cli migrate
    python -m app.cli seed
    python -m app.cli create-operator --name "Maria" --username maria --role admin
    python -m app.cli list-operators
    python -m app.cli rotate-key --username maria
    python -m app.cli backup
    python -m app.cli restore ARQUIVO.db --yes      (com a aplicação PARADA)
    python -m app.cli docs                          (regenera docs/endpoints.md)
"""

import argparse
import sys
from pathlib import Path

from app.core.config import BASE_DIR, get_settings
from app.core.enums import OperatorRole
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.database.connection import Database
from app.database.migrate import upgrade_to_head
from app.database.seed import seed_demo_data
from app.services.backup import BackupError, BackupService
from app.services.operators import OperatorService


def _database() -> Database:
    settings = get_settings()
    setup_logging(settings)
    database = Database(settings.sqlalchemy_url, echo=settings.db_echo)
    database.prepare()
    return database


def cmd_migrate(_: argparse.Namespace) -> int:
    database = _database()
    upgrade_to_head(database.url)
    print("Migrações aplicadas.")
    return 0


def cmd_seed(_: argparse.Namespace) -> int:
    database = _database()
    upgrade_to_head(database.url)
    with database.session_scope() as session:
        report = seed_demo_data(session)
    print(f"Dados de demonstração (FICTÍCIOS). Criados: {report.created} | Já existentes: {report.skipped}")
    return 0


def cmd_create_operator(args: argparse.Namespace) -> int:
    database = _database()
    upgrade_to_head(database.url)
    with database.session_scope() as session:
        try:
            operator, api_key = OperatorService(session).create(
                name=args.name, username=args.username, role=OperatorRole(args.role)
            )
        except AppError as exc:
            print(f"Erro: {exc.message}", file=sys.stderr)
            return 1
    print(f"Operador '{operator.username}' criado com perfil '{operator.role.value}'.")
    print("Chave de API (exibida apenas agora; guarde em local seguro):")
    print(api_key)
    return 0


def cmd_list_operators(_: argparse.Namespace) -> int:
    database = _database()
    upgrade_to_head(database.url)
    with database.session_scope() as session:
        operators, _total = OperatorService(session).list(limit=200, offset=0)
        for op in operators:
            print(f"{op.username:20} {op.role.value:9} {'ativo' if op.active else 'INATIVO':8} {op.name}")
    return 0


def cmd_rotate_key(args: argparse.Namespace) -> int:
    """Recuperação local: gera nova chave para um operador (útil se a chave do admin foi perdida)."""
    database = _database()
    upgrade_to_head(database.url)
    with database.session_scope() as session:
        service = OperatorService(session)
        operator = service.repository.get_by_username(args.username)
        if operator is None:
            print(f"Erro: operador '{args.username}' não existe.", file=sys.stderr)
            return 1
        operator, api_key = service.rotate_key(operator.id, changed_by=None)
    print(f"Nova chave de API de '{operator.username}' (exibida apenas agora; a anterior foi invalidada):")
    print(api_key)
    return 0


def cmd_backup(_: argparse.Namespace) -> int:
    settings = get_settings()
    database = _database()
    try:
        info = BackupService(database, settings).create()
    except (BackupError, Exception) as exc:  # noqa: BLE001 - mensagem clara para o operador
        print(f"Erro no backup: {getattr(exc, 'message', exc)}", file=sys.stderr)
        return 1
    print(f"Backup criado: {settings.backup_dir / info.filename} ({info.size_bytes} bytes, integridade {info.integrity})")
    print(f"SHA-256: {info.sha256}")
    print("Lembrete: as imagens (data/images) não fazem parte do backup do banco.")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    if not args.yes:
        print("Restauração substitui o banco atual (uma cópia de segurança é guardada).", file=sys.stderr)
        print("Pare a aplicação e repita com --yes para confirmar.", file=sys.stderr)
        return 2
    settings = get_settings()
    database = _database()
    try:
        live, safety = BackupService(database, settings).restore(Path(args.file))
    except Exception as exc:  # noqa: BLE001
        print(f"Erro na restauração: {getattr(exc, 'message', exc)}", file=sys.stderr)
        return 1
    print(f"Banco restaurado em {live}")
    if safety:
        print(f"Cópia do banco anterior: {safety}")
    return 0


def cmd_docs(_: argparse.Namespace) -> int:
    from app.api.inventory import render_endpoints_markdown
    from app.main import create_app

    target = BASE_DIR / "docs" / "endpoints.md"
    target.write_text(render_endpoints_markdown(create_app()), encoding="utf-8")
    print(f"Gerado: {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Comandos do PratoCusto AI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="Aplica as migrações do banco").set_defaults(func=cmd_migrate)
    sub.add_parser("seed", help="Cria dados FICTÍCIOS de demonstração (idempotente)").set_defaults(func=cmd_seed)

    create = sub.add_parser("create-operator", help="Cria um operador e exibe sua chave de API")
    create.add_argument("--name", required=True)
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=[r.value for r in OperatorRole], default=OperatorRole.OPERATOR.value)
    create.set_defaults(func=cmd_create_operator)

    sub.add_parser("list-operators", help="Lista operadores").set_defaults(func=cmd_list_operators)
    rotate = sub.add_parser("rotate-key", help="Gera nova chave de API para um operador (recuperação local)")
    rotate.add_argument("--username", required=True)
    rotate.set_defaults(func=cmd_rotate_key)
    sub.add_parser("backup", help="Cria backup verificado do banco SQLite").set_defaults(func=cmd_backup)
    restore = sub.add_parser("restore", help="Restaura um backup (com a aplicação parada)")
    restore.add_argument("file")
    restore.add_argument("--yes", action="store_true", help="confirma a substituição do banco atual")
    restore.set_defaults(func=cmd_restore)
    sub.add_parser("docs", help="Regenera docs/endpoints.md").set_defaults(func=cmd_docs)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
