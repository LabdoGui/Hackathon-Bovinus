# Conectar uma balança real (porta serial)

O PratoCusto AI **não presume o protocolo de nenhum fabricante**. Toda a comunicação é
configurada pelo `.env`, com base no **manual da sua balança**. Enquanto a balança não estiver
pronta, use `SCALE_MODE=mock` (simulador) ou a fonte `manual` (peso digitado).

## 1. Descobrir a porta COM

1. Conecte o cabo serial (RS-232) ou o adaptador USB-serial e instale o driver do fabricante.
2. Com a API rodando, abra `GET /api/v1/scale/ports` (ou o Gerenciador de Dispositivos do
   Windows, em *Portas (COM e LPT)*). Anote a porta, por exemplo `COM4`.

## 2. Copiar os parâmetros do manual

Procure no manual a seção de comunicação serial / saída de dados e preencha:

| Variável | O que é | Onde encontrar no manual |
|----------|---------|--------------------------|
| `SCALE_SERIAL_PORT` | Porta COM | Gerenciador de Dispositivos |
| `SCALE_SERIAL_BAUDRATE` | Velocidade (baud) | "velocidade", "baud rate" |
| `SCALE_SERIAL_BYTESIZE` | Bits de dados (5–8) | "data bits" |
| `SCALE_SERIAL_PARITY` | `N`, `E`, `O`, `M` ou `S` | "paridade" |
| `SCALE_SERIAL_STOPBITS` | `1`, `1.5` ou `2` | "stop bits" |
| `SCALE_SERIAL_PROTOCOL` | `continuous` se a balança envia o peso sozinha; `request` se ela só responde a um comando | "modo de transmissão" |
| `SCALE_SERIAL_REQUEST_COMMAND` | Comando de solicitação (modo `request`), com escapes como `\x05` | "comando de leitura" |
| `SCALE_SERIAL_LINE_TERMINATOR` | Caractere(s) de fim de mensagem, ex.: `\r\n`, `\r`, `\x03` | "formato do protocolo" |
| `SCALE_SERIAL_WEIGHT_REGEX` | Expressão regular que extrai o peso (grupo `weight`) | "formato da mensagem" |
| `SCALE_SERIAL_STABLE_REGEX` | Expressão que só aparece quando o peso está estável (opcional) | "indicador de estabilidade" |
| `SCALE_SERIAL_UNIT` | `g` ou `kg`: unidade do número enviado | "formato do peso" |

Se o manual não indica estabilidade na mensagem, deixe `SCALE_SERIAL_STABLE_REGEX` vazio: o sistema
considera estável quando `SCALE_STABLE_SAMPLES` leituras seguidas variam no máximo
`SCALE_STABLE_TOLERANCE_G` gramas.

### Montando a expressão regular

A expressão precisa de um grupo nomeado `weight`. Exemplo **hipotético** (não é de nenhum
fabricante): se a balança enviasse `ST,GS,+000.523kg`, uma expressão possível seria

```
SCALE_SERIAL_WEIGHT_REGEX=(?P<weight>[-+]?\d+(?:[.,]\d+)?)\s*(?P<unit>kg|g)
SCALE_SERIAL_STABLE_REGEX=^ST
```

Vírgula decimal é aceita. Se houver grupo `unit`, ele prevalece sobre `SCALE_SERIAL_UNIT`.

## 3. Ativar e testar

```
SCALE_MODE=serial
```

Reinicie a API e chame `POST /api/v1/scale/readings` com `{}`.

* **201** com `stable=true`: a balança está funcionando.
* **503 `scale_unavailable`**: a porta não abriu (porta errada, cabo, driver ou porta em uso por
  outro programa).
* **503 `scale_timeout`**: a porta abriu, mas nada chegou no tempo limite. Confira baud, paridade,
  protocolo, comando e terminador.
* **503 `scale_protocol_error`**: chegou uma mensagem, mas a expressão regular não reconheceu o
  peso. A mensagem de erro mostra o texto recebido (caracteres de controle aparecem como `?`).

Toda falha fica registrada em `scale_readings` (campo `error`) e no histórico de auditoria
(`entity_type=hardware`). Com `SCALE_ALLOW_MOCK_FALLBACK=true` e `SCALE_ALLOW_MANUAL=true`, as
fontes `mock` e `manual` continuam disponíveis enquanto a balança é ajustada.

## Observações

* O peso usado é o da **última leitura estável**, sem médias, para corresponder ao visor da balança.
* A porta serial só é aberta na primeira leitura e é compartilhada por uma leitura de cada vez.
* Balanças usadas para venda por peso costumam estar sujeitas a regras metrológicas
  (no Brasil, do Inmetro). Confirme as exigências aplicáveis ao seu equipamento e uso.
