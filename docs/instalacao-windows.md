# Instalação no Windows (notebook ou mini-PC)

> Os scripts `.ps1`/`.bat` foram escritos com cuidado, mas **não puderam ser executados** no
> ambiente de desenvolvimento (que é Linux). Se algum passo falhar no seu computador, use o
> "passo a passo manual" abaixo e reporte o erro.

## Requisitos

* Windows 10 ou 11.
* **Python 3.12** (https://www.python.org/downloads/ — marque *Add python.exe to PATH*; ou
  `winget install Python.Python.3.12`).
* **Git** (https://git-scm.com/download/win), apenas para baixar o projeto.
* Webcam USB (opcional) e balança com saída serial/USB-serial (opcional). Sem eles o sistema
  funciona com a balança **simulada**, câmera por **envio de imagem** e reconhecimento **simulado**.

## Instalação rápida (scripts)

```powershell
git clone https://github.com/LabdoGui/Hackathon-Bovinus.git
cd Hackathon-Bovinus
.\instalar.bat            # ou:  .\instalar.bat -Demo   (inclui dados FICTÍCIOS de demonstração)
```

O instalador cria o ambiente virtual `.venv`, instala as dependências, cria o `.env` (sem
sobrescrever um existente) e prepara o banco. Depois:

```powershell
.venv\Scripts\python.exe -m app.cli create-operator --name "Administrador" --username admin --role admin
.\iniciar.bat
```

* O comando `create-operator` mostra a **chave de API uma única vez**: guarde-a.
* Abra **http://127.0.0.1:8000/dashboard** e entre com a chave. A documentação interativa está em
  `/docs`.
* Para parar o sistema, feche a janela ou pressione `Ctrl+C`.

Se o PowerShell reclamar de política de execução, os `.bat` já usam `-ExecutionPolicy Bypass`
**apenas para aquele processo**; não é preciso alterar a política do computador.

## Passo a passo manual

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # se bloquear: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.cli migrate
python -m app.cli seed                 # opcional: dados FICTÍCIOS
python -m app.cli create-operator --name "Administrador" --username admin --role admin
python -m app
```

## Configuração do `.env`

Revise os valores (todos têm comentário em `.env.example`). Os mais importantes:

| Situação | Variáveis |
|----------|-----------|
| Preço cobrado por kg | `DEFAULT_PRICE_PER_KG` |
| Tara do prato | `SCALE_DEFAULT_TARE_G` (ou `PUT /api/v1/scale/tare`) |
| Balança real | `SCALE_MODE=serial` e `SCALE_SERIAL_*` — veja [balanca-serial.md](balanca-serial.md) |
| Webcam | `CAMERA_MODE=webcam`, `CAMERA_DEVICE_INDEX`, `CAMERA_BACKEND` — veja [webcam.md](webcam.md) |
| Reconhecimento | `RECOGNITION_MODE=mock` (simulado) ou `api` — veja [reconhecimento.md](reconhecimento.md) |
| Acesso por outros equipamentos | `HOST`, `ALLOWED_HOSTS`, `CORS_ORIGINS`, `API_REQUIRE_KEY` — **leia [seguranca.md](seguranca.md) antes** |

Depois de editar o `.env`, reinicie o sistema.

## Atualizar para uma versão nova

```powershell
git pull
.venv\Scripts\python.exe -m pip install -r requirements.txt
.\iniciar.bat           # as migrações do banco são aplicadas automaticamente na inicialização
```

Antes de atualizar, faça um backup (`scripts\backup.ps1`; veja [backup.md](backup.md)).

## Iniciar junto com o Windows (opcional)

Crie uma tarefa no Agendador de Tarefas que execute `iniciar.bat` no logon do usuário. Evite rodar
como serviço do sistema com a webcam, que costuma depender da sessão do usuário.

## Problemas comuns

| Sintoma | O que fazer |
|---------|-------------|
| `Python 3.12 nao encontrado` | instale o Python 3.12 e abra um **novo** terminal |
| Webcam não abre / tela preta | feche Teams/Zoom/app Câmera; tente `CAMERA_BACKEND=dshow` ou `msmf` |
| `COM3` inexistente | veja a porta correta em `GET /api/v1/scale/ports` ou no Gerenciador de Dispositivos |
| Erro `invalid_host` (400) | o endereço usado no navegador não está em `ALLOWED_HOSTS` |
| `too_many_attempts` (429) | muitas chaves inválidas; aguarde o tempo indicado em `Retry-After` |
| Fuso horário desconhecido | `pip install tzdata` (já está no `requirements.txt`) |
