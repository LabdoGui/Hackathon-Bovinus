# PratoCusto AI — Backend

API REST local que conecta **balança**, **webcam USB**, **reconhecimento de alimentos**,
**motor de cálculo de custos**, **banco de dados** e **painel gerencial** de um restaurante
self-service. Roda em um notebook ou mini-PC **Windows** (sem Raspberry Pi).

**Demonstração online:** https://labdogui.github.io/Hackathon-Bovinus/ — roda no navegador, com
balança e reconhecimento simulados e dados fictícios (como ativar: [docs/github-pages.md](docs/github-pages.md)).

**Vídeo de apresentação:** [docs/media/pratocusto.mp4](docs/media/pratocusto.mp4) — narrado, 4min48s (também
na página inicial do site).

**Documentos do projeto:**

* [Detalhamento e Desenvolvimento do Projeto](docs/media/documentos/Detalhamento_Desenvolvimento_PratoCusto_AI_Bovinus.pdf)
  — problema, solução, arquitetura, fluxo, cálculo de custos, revisão humana, testes e próximas etapas.
* [Anexo Técnico](docs/media/documentos/Anexo_Tecnico_PratoCusto_AI_Bovinus.pdf) — diagramas, modelo do
  banco de dados, organização do código-fonte e roteiro para avaliação.

> ## Leia antes de usar em produção
>
> * **Não existe modelo de reconhecimento de alimentos treinado neste projeto.** O modo padrão
>   (`RECOGNITION_MODE=mock`) é uma **simulação**: os alimentos "reconhecidos" não refletem a
>   imagem, e as transações originadas dele vão para revisão humana. Para reconhecimento real é
>   preciso integrar uma API externa (contrato em [docs/reconhecimento.md](docs/reconhecimento.md))
>   ou um modelo local (apenas a estrutura existe).
> * Os dados do `seed` são **fictícios** (`is_demo=true`, sufixo "(demo)").
> * **Webcam física, balança real, Docker e os scripts do Windows não puderam ser testados** no
>   ambiente de desenvolvimento (Linux, sem hardware, sem daemon do Docker). O que foi testado:
>   toda a lógica com equipamentos simulados/falsos, a API, o painel em navegador (Chromium) e os
>   arquivos de empacotamento de forma estática. Veja [Limitações](#limitações-conhecidas).
> * "Margem" no sistema é a **margem bruta alimentar estimada** (valor cobrado − custo alimentar
>   estimado pelas fichas técnicas). **Não é lucro líquido.**

## Status

| Fase | Escopo | Status |
|------|--------|--------|
| 1 | Estrutura, configurações, banco de dados e API básica | ✅ |
| 2 | Simulador de balança e motor de cálculo | ✅ |
| 3 | Webcam e captura | ✅ (webcam física não testada) |
| 4 | Reconhecimento mock e interface abstrata de IA | ✅ (sem modelo real) |
| 5 | Revisão humana, histórico e relatórios | ✅ |
| 6 | Testes, segurança, documentação e empacotamento | ✅ |

Relatório de cada fase em [docs/fases/](docs/fases/). **460 testes**.

Depois das fases: página **Balcão** (pesa, fotografa, reconhece e registra num clique), nova
identidade visual (tomate, tinta e creme; fonte Plus Jakarta Sans servida localmente) e o site de
demonstração no GitHub Pages.

## Começando

### Windows (recomendado)

Requisitos: Python 3.12 e Git. Passo a passo completo em
[docs/instalacao-windows.md](docs/instalacao-windows.md).

```powershell
git clone https://github.com/LabdoGui/Hackathon-Bovinus.git
cd Hackathon-Bovinus
.\instalar.bat -Demo
.venv\Scripts\python.exe -m app.cli create-operator --name "Administrador" --username admin --role admin
.\iniciar.bat
```

Abra **http://127.0.0.1:8000/** (página inicial) ou **/dashboard** e entre com a chave que o
`create-operator` mostrou (aparece uma única vez).

### Docker

```bash
docker compose up --build
docker compose exec app python -m app.cli create-operator --name Admin --username admin --role admin
```

Detalhes (PostgreSQL, Linux com dispositivos, limitações no Windows): [docs/docker.md](docs/docker.md).

### Linux/macOS (desenvolvimento)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.cli seed && python -m app.cli create-operator --name Admin --username admin --role admin
python -m app
```

## Endereços

| URL | Descrição |
|-----|-----------|
| `/` | Página inicial com atalhos e a configuração atual |
| `/balcao` | Balcão: pesa, fotografa, reconhece e registra o prato num clique |
| `/dashboard` | Painel gerencial (chave de gerente/admin) |
| `/review?id=…` | Revisão de uma transação (chave de operador) |
| `/camera` | Teste da webcam (pré-visualização, captura, upload) |
| `/docs`, `/redoc` | Documentação interativa da API (OpenAPI) |
| `/api/v1/health` | Saúde da API |

## Como funciona (fluxo do dia a dia)

Na página **/balcao** os passos 1 a 4 acontecem com um clique ("Pesar, fotografar e registrar").
Pela API:

1. **Balança** → `POST /api/v1/scale/readings` (peso estável, tara, peso mínimo).
2. **Câmera** → `POST /api/v1/camera/captures` (ou `/uploads`) → valida a imagem.
3. **Reconhecimento** → `POST /api/v1/recognition/analyze` → alimentos, confianças, proporções e pesos.
4. **Transação** → `POST /api/v1/transactions/from-recognition` (ou `/transactions`, informando os
   alimentos): peso líquido, distribuição, custo, valor cobrado e margem bruta alimentar estimada.
   Incerteza, alimento fora do cadastro, custo desconhecido ou resultado simulado → `pending_review`.
5. **Revisão humana** → `/review` ou `POST /transactions/{id}/review`: o operador corrige
   alimentos, proporções e pesos; os **valores originais** e todo o histórico ficam registrados.
6. **Gestão** → `/dashboard`, `/api/v1/reports/*` e exportação CSV.

## Configuração

Tudo vem de variáveis de ambiente (ou `.env`). Modelo comentado em [`.env.example`](.env.example).
Valores iniciais exigidos: `SCALE_MODE=mock`, `CAMERA_MODE=webcam`, `RECOGNITION_MODE=mock`,
`DATABASE_MODE=sqlite`.

| Tema | Variáveis | Documentação |
|------|-----------|--------------|
| Balança | `SCALE_*` (porta COM, baud, paridade, protocolo, estabilização, tara) | [balanca-serial.md](docs/balanca-serial.md) |
| Câmera | `CAMERA_*` | [webcam.md](docs/webcam.md) |
| Reconhecimento | `RECOGNITION_*` | [reconhecimento.md](docs/reconhecimento.md) |
| Revisão e relatórios | `APP_TIMEZONE`, `REVIEW_*`, `REPORT_*` | [revisao-e-relatorios.md](docs/revisao-e-relatorios.md) |
| Segurança | `ALLOWED_HOSTS`, `CORS_ORIGINS`, `API_REQUIRE_KEY`, `AUTH_*`, `MAX_UPLOAD_MB` | [seguranca.md](docs/seguranca.md) |
| Backup | `BACKUP_KEEP`, `BACKUP_INTERVAL_HOURS` | [backup.md](docs/backup.md) |
| Banco | `DATABASE_MODE`, `SQLITE_PATH`, `DATABASE_URL`, `POSTGRES_*` | abaixo |

### PostgreSQL (opção futura)

```bash
pip install -r requirements-postgres.txt
```

`DATABASE_MODE=postgresql` e `DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/pratocusto`
(ou `POSTGRES_*`). As regras de negócio não mudam; as migrações são as mesmas (o SQL para
PostgreSQL é verificado nos testes, mas o projeto **não foi executado contra um servidor
PostgreSQL real**).

## Documentação

| Documento | Conteúdo |
|-----------|----------|
| [docs/instalacao-windows.md](docs/instalacao-windows.md) | Instalação e operação no Windows |
| [docs/endpoints.md](docs/endpoints.md) | Todos os endpoints e o nível de acesso de cada um (gerado do código) |
| [docs/balanca-serial.md](docs/balanca-serial.md) | **Conectar uma balança real depois** |
| [docs/webcam.md](docs/webcam.md) | Webcam, captura, qualidade de imagem, upload |
| [docs/reconhecimento.md](docs/reconhecimento.md) | Reconhecimento (mock/API/local) e revisão automática |
| [docs/revisao-e-relatorios.md](docs/revisao-e-relatorios.md) | Revisão humana, auditoria, relatórios, painel |
| [docs/seguranca.md](docs/seguranca.md) | Controles, operação em rede, limites |
| [docs/backup.md](docs/backup.md) | Backup e restauração |
| [docs/docker.md](docs/docker.md) | Docker e PostgreSQL |
| [docs/github-pages.md](docs/github-pages.md) | Site online (GitHub Pages): o que é simulado, como ativar e atualizar |
| [docs/fases/](docs/fases/) | Relatório de cada fase de desenvolvimento |

## Arquitetura

```
app/
  main.py              # fábrica da aplicação FastAPI
  cli.py               # migrate, seed, create-operator, rotate-key, backup, restore, docs
  core/                # config, logging (com máscara), security, middleware (Host/Origin), limitador
  api/                 # deps (acesso), erros, router /api/v1, inventário de rotas
    routes/            # health, operators, ingredients, recipes, foods, scale, camera, recognition,
                       # transactions, reports, audit, admin
  models/              # entidades SQLAlchemy (Food, Recipe, RecipeIngredient, Ingredient, Transaction,
                       # TransactionItem, RecognitionResult, ImageCapture, ScaleReading, Operator, AuditLog)
  schemas/             # modelos Pydantic de entrada/saída
  repositories/        # consultas ao banco
  services/            # regras de negócio
    scale/             # ScaleService: mock, serial, manual + estabilização
    camera/            # CameraService (OpenCV), qualidade, armazenamento de imagens
    recognition/       # FoodRecognitionService: mock (simulado), API, local + interpretação
    calculations/      # motor de cálculo (funções puras)
    reports/           # relatórios (Decimal, fuso local, CSV)
    reviews.py backup.py transactions.py ...
  database/            # conexão, migrações Alembic (0001-0004), seed idempotente
  templates/ static/   # painel (Jinja2 + JS sem dependências)
tests/                 # 407 testes, sem hardware físico
scripts/ docs/ Dockerfile docker-compose*.yml
```

Fluxo de dependência: **rotas → serviços → repositórios → modelos**. Rotas não acessam o banco
diretamente; serviços não conhecem HTTP; integrações de hardware ficam isoladas em `services/`.

## Testes e qualidade

```bash
python -m pytest                      # 407 testes, sem balança nem webcam físicas
pip install -r requirements-dev.txt   # opcional: cobertura
coverage run --source=app -m pytest && coverage report
```

Cobrem: peso líquido, distribuição, custo, margem, reconhecimento mock, validação de imagem,
transações, revisão humana, endpoints, persistência (inclusive entre reinícios), migrações,
segurança (acesso, Host/Origin, força bruta, XSS), backup/restauração, concorrência e
empacotamento. O código passa em `ruff` (erros, bugbear, segurança, modernização).

## Limitações conhecidas

* **Sem reconhecimento real**: só simulado, API externa (contrato próprio, nenhum fornecedor
  integrado) ou estrutura para modelo local.
* **Hardware não testado**: webcam física, balança real. A balança serial depende de configurar o
  protocolo conforme o manual do equipamento (nada foi presumido).
* **Docker e scripts do Windows não executados** pelos autores (apenas validados estaticamente).
* **PostgreSQL**: o SQL é gerado e verificado, mas não houve execução contra um servidor real; o
  backup automático cobre apenas SQLite.
* **Segurança**: sem login de usuário/senha nem HTTPS embutido (veja
  [docs/seguranca.md](docs/seguranca.md) antes de expor na rede).
* O painel não foi testado em celular/tablet.
* Transações confirmadas não são reabertas (somente canceladas por gerente/admin).
* Balanças usadas na venda por peso podem estar sujeitas a regras metrológicas (no Brasil, do
  Inmetro): confirme as exigências do seu equipamento e uso.
