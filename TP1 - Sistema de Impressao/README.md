# Sistema Distribuído de Impressão com Ricart-Agrawala

## 📋 Descrição

Sistema de impressão distribuído que implementa:
- **gRPC** para comunicação entre processos
- **Algoritmo de Ricart-Agrawala** para exclusão mútua distribuída
- **Relógios Lógicos de Lamport** para sincronização e ordenação de eventos

## 🏗️ Arquitetura

### Servidor de Impressão (Burro)
- **Porta:** 50051
- **Função:** Recebe e imprime documentos
- **Características:** Não participa da exclusão mútua

### Clientes Inteligentes
- **Portas:** 50052, 50053, 50054, ...
- **Função:** Coordenam acesso ao servidor usando Ricart-Agrawala
- **Características:** Agem como clientes e servidores gRPC

## 🚀 Instalação

### 1. Instalar Dependências

```bash
pip install -r requirements.txt
```

### 2. Compilar o Arquivo .proto

```bash
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. printing.proto
```

Isso gerará os arquivos:
- `printing_pb2.py`
- `printing_pb2_grpc.py`

## 🎮 Como Executar

### Terminal 1: Servidor de Impressão

```bash
python print_server.py
```

### Terminal 2: Cliente 1

```bash
python smart_client.py 1 50052 50053 50054
```

**Parâmetros:**
- `1` = ID do cliente
- `50052` = Porta deste cliente
- `50053 50054` = Portas dos outros clientes

### Terminal 3: Cliente 2

```bash
python smart_client.py 2 50053 50052 50054
```

### Terminal 4: Cliente 3

```bash
python smart_client.py 3 50054 50052 50053
```

### Executando com 1..N clientes

A implementação detecta dinamicamente quais dos peers configurados estão realmente ativos antes de enviar REQUEST/RELEASE. Isso permite rodar com apenas 1 cliente (ou com qualquer subconjunto de clientes) mesmo se você passar portas de peers que não estão em execução — o cliente ignorará automaticamente peers inativos.

Recomendações e exemplos (PowerShell / Windows):

- Inicie primeiro o servidor de impressão (porta 50051):

```powershell
python .\print_server.py
```

- Exemplo: rodar um único cliente (não precisa iniciar outros clientes):

```powershell
python .\smart_client.py 1 50052
```

- Exemplo: rodar dois clientes (execute cada comando em um terminal separado):

```powershell
python .\smart_client.py 1 50052 50053
python .\smart_client.py 2 50053 50052
```

- Exemplo: rodar três clientes (cada um em seu terminal):

```powershell
python .\smart_client.py 1 50052 50053 50054
python .\smart_client.py 2 50053 50052 50054
python .\smart_client.py 3 50054 50052 50053
```

- Exemplo: rodar N clientes (padrão de portas):

   - Se você quiser rodar N clientes localmente, escolha portas sequenciais começando em 50052. Por exemplo, para N=4: portas 50052,50053,50054,50055.
   - Em cada terminal, passe o ID do cliente, a sua porta e as portas dos outros clientes (a ordem das portas não importa). Exemplo para N=4:

```powershell
python .\smart_client.py 1 50052 50053 50054 50055
python .\smart_client.py 2 50053 50052 50054 50055
python .\smart_client.py 3 50054 50052 50053 50055
python .\smart_client.py 4 50055 50052 50053 50054
```

Observações importantes:

- O cliente mantém uma lista `configured_peers` (as portas que você passou) e a cada requisição atualiza a lista `other_clients_ports` com os peers que estão realmente aceitando conexões. Assim, se um peer estiver off, ele será ignorado naquela rodada.
- Para testes rápidos em uma única máquina, você pode iniciar apenas os clientes que quiser e passar as portas dos demais — o sistema continuará a funcionar usando apenas os peers ativos.
- Para comportamento ideal em testes de concorrência, inicie todos os clientes relevantes antes de gerar várias requisições simultâneas.


## 📊 Cenários de Teste

### Cenário 1: Funcionamento Básico

1. Inicie o servidor de impressão
2. Inicie apenas 1 cliente
3. Observe que o cliente consegue imprimir sem concorrência

### Cenário 2: Concorrência Simples

1. Inicie o servidor de impressão
2. Inicie 2 clientes
3. Observe a coordenação através do algoritmo Ricart-Agrawala
4. Verifique que apenas um cliente imprime por vez

### Cenário 3: Concorrência Múltipla

1. Inicie o servidor de impressão
2. Inicie 3 ou mais clientes
3. Observe requisições simultâneas
4. Verifique que a ordem é decidida pelos timestamps de Lamport


## 🧪 Explicação do Algoritmo

### Relógio de Lamport

- Cada evento incrementa o relógio local
- Ao receber mensagem: `clock = max(clock_local, clock_recebido) + 1`
- Garante ordenação causal de eventos

### Ricart-Agrawala

1. **Requisição de Acesso:**
   - Cliente envia REQUEST para todos os outros
   - Aguarda resposta de todos antes de acessar

2. **Ao Receber REQUEST:**
   - Se não está interessado: responde imediatamente
   - Se está interessado: compara timestamps
     - Timestamp menor tem prioridade
     - Em empate, ID menor tem prioridade
   - Se não tem prioridade: adia resposta

3. **Liberação:**
   - Cliente envia RELEASE para todos
   - Envia respostas que foram adiadas

## 📝 Detalhes de Implementação

### Servidor de Impressão (`print_server.py`)
- Implementa apenas `PrintingService`
- Simula impressão com delay de 3 segundos
- Mantém relógio de Lamport para log

### Cliente Inteligente (`smart_client.py`)
- Implementa `MutualExclusionService` (como servidor)
- Usa `PrintingService` (como cliente para servidor burro)
- Usa `MutualExclusionService` (como cliente para outros clientes)
- Gerencia:
  - Relógio de Lamport
  - Estado da seção crítica
  - Fila de respostas adiadas
  - Threads para servidor gRPC

## 🔧 Resolução de Problemas

### Erro: "Address already in use"
- Verifique se não há outro processo usando a porta
- Use `lsof -i :50051` (Linux/Mac) ou `netstat -ano | findstr :50051` (Windows)

### Cliente não recebe respostas
- Verifique se todos os clientes foram iniciados
- Confirme que as portas estão corretas
- Verifique firewall

### Deadlock
- O algoritmo Ricart-Agrawala é livre de deadlock por design
- Se ocorrer, pode ser problema de implementação ou timeout de rede