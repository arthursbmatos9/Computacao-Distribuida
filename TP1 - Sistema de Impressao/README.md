## Como compilar e executar

### 1. Instalar Dependências

```bash
pip install -r requirements.txt
```


### 2. Compilar o Arquivo 

```bash
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. printing.proto
```

Isso gerará os arquivos:
- `printing_pb2.py`
- `printing_pb2_grpc.py`


## Como Executar

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
