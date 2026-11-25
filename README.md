# PratoCusto AI — Backend

API REST local que conecta **balança**, **webcam USB**, **reconhecimento de alimentos**,
**motor de cálculo de custos**, **banco de dados** e **painel gerencial** de um restaurante
self-service. Projetada para rodar em um notebook ou mini-PC **Windows** (sem Raspberry Pi).

> **Importante:** o reconhecimento de alimentos começa em modo *mock* (simulado). Não existe
> modelo treinado neste projeto até que um seja integrado. Os dados de demonstração (seed)
> são **fictícios** e estão marcados com `is_demo=true` e o sufixo "(demo)".

## Status por fase

| Fase | Escopo | Status |
|------|--------|--------|
| 1 | Estrutura, configurações, banco de dados e API básica | ✅ Concluída |
| 2 | Simulador de balança e motor de cálculo | ✅ Concluída |
| 3 | Webcam e captura | ✅ Concluída |
| 4 | Reconhecimento mock e interface abstrata de IA | ⏳ Aguardando autorização |
| 5 | Revisão humana, histórico e relatórios | — |
| 6 | Testes, segurança, documentação e empacotamento | — |

Detalhes de cada fase em [`docs/fases/`](docs/fases/).

## Tecnologias

Python 3.12 · FastAPI · SQLAlchemy 2 · Pydantic 2 (+ pydantic-settings) · Alembic · SQLite
(PostgreSQL opcional) · OpenCV · PySerial · Uvicorn · Jinja2 · Pytest · HTTPX · Pillow ·
python-multipart.

## Instalação no Windows (PowerShell)

Pré-requisitos: [Python 3.12](https://www.python.org/downloads/) (marque *Add python.exe to PATH*)
e [Git](https://git-scm.com/download/win).

```powershell
git clone -b claude/magical-fermat-438tis https://github.com/LabdoGui/Hackathon-Bovinus.git
cd Hackathon-Bovinus
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Se o PowerShell bloquear a ativação do ambiente virtual, execute uma vez:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

```powershell
python -m app.cli seed                                                # dados fictícios (opcional)
python -m app.cli create-operator --name "Administrador" --username admin --role admin
python -m app                                                         # inicia em http://127.0.0.1:8000
```

O comando `create-operator` mostra a **chave de API uma única vez** — guarde-a. Ela é usada no
cabeçalho `X-API-Key` (botão **Authorize** em `/docs`) para operações administrativas.

## Instalação no Linux/macOS

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.cli seed
python -m app
```

## Endereços

| URL | Descrição |
|-----|-----------|
| http://127.0.0.1:8000/ | Página inicial (status da configuração) |
| http://127.0.0.1:8000/docs | Documentação interativa (Swagger/OpenAPI) |
| http://127.0.0.1:8000/redoc | Documentação ReDoc |
| http://127.0.0.1:8000/api/v1/health | Saúde da API |
| http://127.0.0.1:8000/camera | Teste da webcam (pré-visualização, captura, upload) |

## Configuração

Todas as configurações vêm de variáveis de ambiente (ou do arquivo `.env`). Veja
[`.env.example`](.env.example). Principais:

| Variável | Valores | Padrão |
|----------|---------|--------|
| `SCALE_MODE` | `mock`, `serial`, `manual` | `mock` |
| `CAMERA_MODE` | `webcam`, `upload`, `mock` | `webcam` |
| `RECOGNITION_MODE` | `mock`, `api`, `local` | `mock` |
| `DATABASE_MODE` | `sqlite`, `postgresql` | `sqlite` |
| `SQLITE_PATH` | caminho do arquivo | `data/pratocusto.db` |
| `DB_AUTO_MIGRATE` | aplica migrações ao iniciar | `true` |
| `CORS_ORIGINS` | origens separadas por vírgula (sem `*`) | `http://localhost:8000,http://127.0.0.1:8000` |
| `MAX_UPLOAD_MB` | limite de imagens | `5` |
| `DEFAULT_PRICE_PER_KG` | preço cobrado por kg (R$) | — (exemplo no `.env.example`) |
| `SCALE_DEFAULT_TARE_G` | tara padrão (g) | `0` |
| `SCALE_MIN_WEIGHT_G` | peso líquido mínimo (g) | `10` |
| `SCALE_STABLE_SAMPLES` / `SCALE_STABLE_TOLERANCE_G` | critério de estabilidade | `3` / `2` |
| `SCALE_SERIAL_*` | porta, baud, paridade, protocolo etc. | ver [docs/balanca-serial.md](docs/balanca-serial.md) |
| `CAMERA_DEVICE_INDEX` / `CAMERA_BACKEND` | webcam e backend (`auto`, `dshow`, `msmf`) | `0` / `auto` |
| `CAMERA_*` | resolução, limiares de qualidade, tempo limite etc. | ver [docs/webcam.md](docs/webcam.md) |

### PostgreSQL (opção futura)

```bash
pip install -r requirements-postgres.txt
```

Depois defina `DATABASE_MODE=postgresql` e `DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/pratocusto`
(ou os campos `POSTGRES_*`). As regras de negócio não mudam: só a conexão.

## Fluxo básico (balança simulada)

1. `POST /api/v1/scale/readings` com `{"simulated_weight_g": 650, "tare_g": 150}` → leitura estável.
2. `POST /api/v1/transactions` com o `id` da leitura e os alimentos com suas proporções
   (cabeçalho opcional `Idempotency-Key`).
3. A resposta traz peso líquido, peso de cada alimento, custo alimentar estimado, valor cobrado e
   margem bruta alimentar estimada.

Para conectar uma balança real, veja [docs/balanca-serial.md](docs/balanca-serial.md); para a webcam, [docs/webcam.md](docs/webcam.md).

## Arquitetura

```
app/
  main.py              # fábrica da aplicação FastAPI
  cli.py               # comandos: migrate, seed, create-operator
  core/                # config, logging (com mascaramento), security, exceções, middleware
  api/                 # deps, tratamento de erros, router /api/v1
    routes/            # health, operators, ingredients, recipes, foods, scale, transactions, camera, (recognition, reports)
  models/              # entidades SQLAlchemy
  schemas/             # modelos Pydantic de entrada/saída
  repositories/        # consultas ao banco (persistência)
  services/            # regras de negócio
    scale/             # ScaleService: mock, serial, manual + estabilização
    calculations/      # motor de cálculo (funções puras)
    camera/            # CameraService (OpenCV), qualidade e armazenamento de imagens
    recognition/ reports/   # fases 4–5
  database/            # conexão, migrações Alembic, seed
  templates/ static/   # páginas Jinja2
  utils/
tests/                 # testes automatizados (sem hardware físico)
docs/                  # documentação por fase
```

Fluxo de dependência: **rotas → serviços → repositórios → modelos**. Rotas não acessam o banco
diretamente; serviços não conhecem HTTP; integrações de hardware ficam isoladas em `services/`.

## Testes

```bash
python -m pytest
```

Nenhum teste depende de balança ou webcam físicas.

## Banco de dados e migrações

```bash
python -m app.cli migrate          # aplica migrações
alembic revision --autogenerate -m "descrição"   # nova migração (desenvolvimento)
```
