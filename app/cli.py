"""Comandos administrativos.

Uso:
    python -m app.cli migrate
    python -m app.cli seed
    python -m app.cli create-operator --name "Maria" --username maria --role admin
"""

import argparse
import sys

from app.core.config import get_settings
from app.core.enums import OperatorRole
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.database.connection import Database
from app.database.migrate import upgrade_to_head
from app.database.seed import seed_demo_data
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
