# Chat cliente-servidor com salas e criptografia (Python)

Projeto da atividade avaliativa de redes com arquitetura cliente-servidor, sockets TCP e mensagens criptografadas.

## Linguagem

- Python 3.10+ (somente biblioteca padrao, incluindo Tkinter para a interface)

## O que foi implementado

- Servidor TCP multicliente com threads.
- Cliente com interface grafica (Tkinter) em tres telas:
1. login;
2. lobby de salas;
3. chat da sala.
- Lobby central com lista ordenada de salas e numero de usuarios.
- Estado vazio intuitivo: se nao houver salas, aparece apenas o fluxo de criar sala.
- Criacao de sala por modal (mais intuitivo que campo solto).
- Salas de chat (criar, entrar, sair e listar salas abertas).
- Log do servidor mostra apenas payload criptografado das mensagens do chat.
- Serializacao manual (JSON + framing de 4 bytes).
- Criptografia didatica obrigatoria nas mensagens do chat.
- Persistencia de historico criptografado por sala em pasta local do projeto.

## Persistencia de salas e historico

As salas e mensagens ficam persistidas no servidor em:

- `storage/rooms.json` (cadastro de salas)
- `storage/history/` (historico criptografado por sala)

Com isso, ao reiniciar o servidor:
- as salas continuam aparecendo no lobby (mesmo com `0` usuarios online);
- qualquer cliente pode entrar nessas salas e receber o historico.

Cada arquivo contem registros JSONL com:
- timestamp (`ts`)
- remetente (`sender`)
- payload criptografado (`payload` com `nonce`, `ciphertext`, `tag`)

Ao entrar em uma sala, o cliente recebe e renderiza o historico recente (descriptografando localmente com a chave).

## Arquitetura da solucao

- `server.py`
Gerencia conexoes, usuarios, salas e historico criptografado por sala. Recebe comandos do cliente (`create_room`, `join_room`, `leave_room`, `message`) e faz broadcast por sala.

- `client.py`
Cliente GUI com 3 telas:
- login de usuario;
- lobby de salas com tabela ordenada e UX de criacao/entrada;
- chat da sala com carregamento de historico.

- `protocol.py`
Camada de transporte e serializacao:
- `send_packet`: envia `len(4 bytes) + JSON`;
- `recv_packet`: reconstrui pacotes do socket.

- `crypto_utils.py`
Criptografia didatica com chave compartilhada:
- derivacao da chave com SHA-256;
- cifra de fluxo baseada em SHA-256 + nonce aleatorio;
- HMAC-SHA256 para integridade/autenticidade;
- dados em Base64 para trafegar no JSON.

## Como executar

Abra 2 terminais na raiz do projeto.

### 1) Iniciar o servidor

```bash
python server.py --host 0.0.0.0 --port 5000 --key "minha-chave-secreta"
```

### 2) Iniciar o cliente (abre a janela)

```bash
python client.py --host 127.0.0.1 --port 5000 --key "minha-chave-secreta"
```

Se quiser simular varios usuarios, abra mais de um cliente em paralelo.

## Conectar outro PC na mesma rede

1. No seu PC, rode o servidor com `--host 0.0.0.0`.
2. O servidor exibira no terminal um ou mais identificadores no formato `IP:porta` (ex.: `192.168.1.20:5000`).
3. No PC do seu amigo, rode `python client.py --key "minha-chave-secreta"`.
4. Na tela de login do cliente, no campo `Identificador do servidor (IP:porta)`, informe o identificador exibido no servidor.
5. Informe o nome de usuario e conecte.

Se nao conectar, libere a porta TCP (ex.: `5000`) no firewall do PC que esta rodando o servidor.

## Chave e criptografia

A chave deve ser a mesma no servidor e em todos os clientes (`--key` ou `CHAT_SHARED_KEY`).

Formato da mensagem criptografada no chat:

```json
{
  "nonce": "...",
  "ciphertext": "...",
  "tag": "..."
}
```

- `nonce`: valor aleatorio por mensagem.
- `ciphertext`: conteudo cifrado.
- `tag`: HMAC-SHA256 para detectar alteracao ou chave errada.

## Observacao tecnica

Implementacao didatica para fins academicos. Em producao, use TLS e bibliotecas criptograficas consolidadas com algoritmos padronizados (ex.: AES-GCM).
