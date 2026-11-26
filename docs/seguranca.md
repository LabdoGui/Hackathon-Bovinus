# Segurança

O PratoCusto AI foi pensado para rodar **localmente** (notebook/mini-PC) e ser usado por
navegador. Esta página resume os controles existentes, o que fica por sua conta e os limites.

## Controles implementados

| Tema | Como está tratado |
|------|-------------------|
| Acesso administrativo | Chaves de API por operador (`X-API-Key`), guardadas **só como hash SHA-256**; perfis `operador` < `gerente` < `admin`. Cadastro, relatórios, auditoria, cancelamento, backup e gestão de operadores exigem perfil. A lista completa, com o nível de cada rota, está em [endpoints.md](endpoints.md) (gerada do código e conferida por teste). |
| Rotas de escrita abertas | Somente o fluxo de pesagem (leitura da balança, captura/upload, reconhecimento, criar/pré-visualizar transação). Um teste falha se qualquer outra rota de escrita ficar sem controle. |
| Força bruta de chaves | Após `AUTH_MAX_FAILURES` (10) chaves inválidas em `AUTH_WINDOW_S` (300 s) a origem recebe 429 com `Retry-After`; vale também para a chave correta durante o bloqueio. Contador em memória (reinicia com o servidor). |
| DNS rebinding | O cabeçalho `Host` precisa estar em `ALLOWED_HOSTS` (padrão `localhost,127.0.0.1`); outros recebem 400 `invalid_host`. |
| Escritas entre sites (CSRF) | Em POST/PUT/PATCH/DELETE com cabeçalho `Origin` (sempre enviado por navegadores entre sites), a origem precisa estar em `CORS_ORIGINS` ou ser a própria. Fecha o buraco das "requisições simples" (upload multipart, POST sem corpo), que o CORS sozinho não impede. A API não usa cookies. |
| CORS | Restritivo: só `CORS_ORIGINS`, sem `*`, sem credenciais, métodos e cabeçalhos explícitos. |
| Consultas e câmera | Abertas por padrão (uso local). Com `API_REQUIRE_KEY=true` **tudo**, exceto `/health`, exige chave — inclusive fotos e pré-visualização (as páginas buscam imagens com a chave e as exibem como `blob:`). |
| Uploads | Limite `MAX_UPLOAD_MB` e de pixels; formato detectado pelo **conteúdo** (JPEG/PNG/WebP); recodificação para JPEG (remove EXIF/GPS e conteúdo embutido); nome enviado ignorado; gravação atômica; download recusa caminhos fora da pasta. |
| Segredos | Nenhuma chave no código; `.env` no `.gitignore` e no `.dockerignore`; senhas e chaves em `SecretStr` (não aparecem em `repr`, status, respostas ou logs). A chave da API de reconhecimento só vai no cabeçalho da requisição. |
| Logs | Mascaram chaves, senhas, tokens e credenciais em URLs; log de acesso só registra método, caminho e status (sem query string nem corpo); erros de validação não ecoam o valor enviado; erros 500 não expõem detalhes. |
| Páginas do painel | CSP restritiva (`script-src 'self'`, sem inline), sem `innerHTML` (texto da API entra via `textContent`), `no-store`, `X-Frame-Options: DENY`. A chave digitada fica só no `sessionStorage` da aba. |
| Reconhecimento externo | HTTPS obrigatório (http só em localhost), sem redirecionamentos, tempo limite, limite de resposta, validação estrita. |
| Duplicidade de transações | `Idempotency-Key`, leitura da balança e resultado de reconhecimento únicos por transação (restrição no banco, testado com requisições simultâneas). |
| Auditoria | Cadastros, correções, mudanças de status, falhas de equipamento, backups e troca de chaves, com operador e motivo. Registros só são inseridos pela API. Nunca contêm chaves. |
| Banco | `PRAGMA foreign_keys=ON`; restrições `CHECK`/`UNIQUE`; valores monetários em `NUMERIC`/`Decimal`. |
| Contêiner | Usuário sem privilégios, `no-new-privileges`, `cap_drop: ALL`, porta publicada só em `127.0.0.1`, imagem sem `.env`/dados. |

## Operadores e chaves

```powershell
python -m app.cli create-operator --name "Maria" --username maria --role manager
python -m app.cli list-operators
python -m app.cli rotate-key --username maria     # nova chave; a anterior deixa de valer
```

Pela API (admin): `PATCH /api/v1/operators/{id}` (nome, perfil, ativo) e
`POST /api/v1/operators/{id}/rotate-key`. O sistema **nunca** deixa de ter um administrador ativo
(`last_admin_protected`). Se perder a chave do último admin, use `rotate-key` no computador do
servidor (quem tem acesso ao computador já tem acesso ao banco).

Boas práticas: uma chave por pessoa; perfil `operador` no caixa; `gerente` para o painel; `admin`
só para quem administra. Troque a chave se um funcionário sair ou se ela for exposta.

## Se for expor o sistema na rede local

O padrão (`HOST=127.0.0.1`) só atende o próprio computador. Para outros equipamentos:

1. `HOST=0.0.0.0` (ou o IP da interface) **e** `API_REQUIRE_KEY=true`.
2. `ALLOWED_HOSTS` com o nome/IP usado (ex.: `192.168.0.10`) e, se houver outro front-end,
   `CORS_ORIGINS` (a própria página do sistema não precisa).
3. Firewall do Windows: libere a porta só para a rede local; nunca para a Internet.
4. A comunicação é **HTTP sem criptografia**: chaves e dados trafegam em texto puro na rede.
   Em rede de confiança isso pode ser aceitável; caso contrário, coloque um proxy reverso com
   HTTPS (Caddy, nginx, IIS) na frente. **Não** publique diretamente na Internet.
5. O sistema avisa no log na inicialização se `HOST` não é local e `API_REQUIRE_KEY=false`.

## Limites conhecidos (seja realista)

* A limitação de tentativas usa o endereço de origem visto pelo servidor; atrás de um proxy todas
  as requisições parecem vir do proxy.
* Não há login com usuário/senha nem sessões; a chave é um segredo compartilhado por pessoa.
* O banco SQLite e as imagens ficam sem criptografia no disco: proteja o computador (conta do
  Windows, BitLocker) e os backups.
* As imagens do prato podem ser enviadas a um serviço externo se você configurar
  `RECOGNITION_MODE=api`: avalie a política de dados do fornecedor.
* A documentação interativa (`/docs`, `/redoc`) carrega scripts de uma CDN pública; sem
  Internet ela pode não abrir (a API continua funcionando).
* Esta análise cobre o código do projeto; não substitui um teste de invasão nem a revisão da
  configuração do seu ambiente (rede, Windows, equipamentos).
