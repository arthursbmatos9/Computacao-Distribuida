# Relatório Técnico - Sistema de Impressão Distribuído

**Disciplina:** Sistemas Distribuídos  
**Trabalho:** Exclusão Mútua com Ricart-Agrawala  
**Data:** 29 de Outubro 2025

---

## 1. Arquitetura do Sistema

### 1.1 Visão Geral

O sistema implementa uma arquitetura distribuída onde múltiplos clientes disputam acesso exclusivo a um servidor de impressão compartilhado. A coordenação é realizada através do algoritmo de Ricart-Agrawala, sem necessidade de um coordenador central.


### 1.2 Componentes

#### Servidor de Impressão ("Burro")
- **Função:** Recebe e processa requisições de impressão
- **Porta:** 50051
- **Características:**
  - Não participa da exclusão mútua
  - Implementa apenas `PrintingService`
  - Simula tempo de impressão (3 segundos)
  - Mantém relógio de Lamport para logging

#### Clientes Inteligentes
- **Função:** Coordenam acesso exclusivo ao servidor
- **Portas:** 50052, 50053, 50054, ...
- **Características:**
  - Atuam como **servidor gRPC** (implementam `MutualExclusionService`)
  - Atuam como **cliente gRPC** (usam `PrintingService` e `MutualExclusionService`)
  - Implementam algoritmo completo de Ricart-Agrawala
  - Mantêm relógio lógico de Lamport sincronizado

---

## 2. Implementação do Algoritmo de Ricart-Agrawala

### 2.1 Princípios do Algoritmo

O algoritmo de Ricart-Agrawala (1981) é uma solução elegante para exclusão mútua distribuída que garante:
- **Exclusão mútua:** Apenas um processo na seção crítica por vez
- **Ausência de deadlock:** O sistema nunca entra em deadlock
- **Ausência de starvation:** Todos os processos eventualmente acessam a seção crítica
- **Ordenação justa:** Processos são ordenados por timestamps de Lamport

### 2.2 Funcionamento Implementado

#### Fase 1: Requisição de Acesso
```python
def request_critical_section(self):
    # 1. Incrementa relógio de Lamport
    current_ts = self.increment_clock("Solicitar SC")
    
    # 2. Marca estado como "solicitando"
    self.requesting_cs = True
    self.request_timestamp = current_ts
    
    # 3. Envia REQUEST para todos os clientes ativos
    for other_port in self.other_clients_ports:
        self.send_request_to_client(other_port, current_ts)
    
    # 4. Aguarda GRANT de todos
    self.wait_for_replies()
    
    # 5. Entra na seção crítica
    self.in_cs = True
```

#### Fase 2: Recepção de REQUEST
```python
def RequestAccess(self, request, context):
    # Atualiza relógio: max(local, recebido) + 1
    self.update_clock(request.lamport_timestamp)
    
    # Caso 1: Não estou interessado → Concede imediatamente
    if not self.requesting_cs and not self.in_cs:
        return AccessResponse(access_granted=True)
    
    # Caso 2: Estou interessado → Compara prioridades
    our_priority = (self.request_timestamp, self.client_id)
    their_priority = (request.lamport_timestamp, request.client_id)
    
    if our_priority < their_priority:
        # Nossa prioridade é maior → Adia resposta
        self.deferred_replies.append(request.client_id)
        return AccessResponse(access_granted=False)
    else:
        # Nossa prioridade é menor → Concede acesso
        return AccessResponse(access_granted=True)
```

#### Fase 3: Liberação
```python
def release_critical_section(self):
    # 1. Marca como fora da seção crítica
    self.in_cs = False
    
    # 2. Envia GRANTs para requisições adiadas
    for client_id in self.deferred_replies:
        self.send_grant_to_client(client_id)
    
    # 3. Limpa lista de adiados
    self.deferred_replies.clear()
```

### 2.3 Critério de Prioridade

A prioridade é determinada pela tupla `(timestamp, client_id)`:
- Menor timestamp = maior prioridade
- Em caso de empate (timestamps iguais): menor ID = maior prioridade

**Exemplo:**
```
Cliente 1 (TS: 10, ID: 1) vs Cliente 2 (TS: 15, ID: 2)
→ Cliente 1 tem prioridade (10 < 15)

Cliente 1 (TS: 10, ID: 1) vs Cliente 2 (TS: 10, ID: 2)
→ Cliente 1 tem prioridade (IDs: 1 < 2)
```

---

## 3. Sincronização com Relógios de Lamport

### 3.1 Implementação

```python
# Evento local (envio de mensagem)
def increment_clock(self):
    self.lamport_clock += 1
    return self.lamport_clock

# Recepção de mensagem
def update_clock(self, received_timestamp):
    self.lamport_clock = max(self.lamport_clock, received_timestamp) + 1
    return self.lamport_clock
```

### 3.2 Propriedades Garantidas

1. **Ordenação Causal:** Se evento A causou evento B, então TS(A) < TS(B)
2. **Sincronização:** Relógios são sincronizados ao receber mensagens
3. **Consistência:** Todos os processos concordam na ordem dos eventos


## 4. Comunicação gRPC

### 4.1 Protocolo Definido

```protobuf
// Cliente → Servidor de Impressão
service PrintingService {
  rpc SendToPrinter (PrintRequest) returns (PrintResponse);
}

// Cliente ↔ Cliente
service MutualExclusionService {
  rpc RequestAccess (AccessRequest) returns (AccessResponse);
  rpc ReleaseAccess (AccessRelease) returns (EmptyResponse);
}
```

## 5. Resultados dos Testes

### 5.1 Cenário 1: Operação Básica (1 Cliente)

**Configuração:**
- 1 servidor de impressão
- 1 cliente

**Resultado:**
```
✓ Cliente consegue imprimir sem concorrência
✓ Timestamps incrementam corretamente
✓ Comunicação com servidor funciona
```

### 5.2 Cenário 2: Concorrência Simples (2 Clientes)

**Configuração:**
- 1 servidor de impressão
- 2 clientes ativos

**Resultado:**
```
Cliente 1 (TS: 1)  → Imprime primeiro
Cliente 2 (TS: 6)  → Aguarda e imprime após Cliente 1 liberar
✓ Exclusão mútua garantida
✓ Ordenação por timestamp funcionando
```

### 5.3 Cenário 3: Concorrência Múltipla (3+ Clientes)

**Configuração:**
- 1 servidor de impressão
- 3 clientes simultâneos

**Resultado:**
```
Cliente A (TS: 5)  → Imprime primeiro
Cliente B (TS: 8)  → Imprime segundo
Cliente C (TS: 12) → Imprime terceiro
✓ Algoritmo coordena múltiplos clientes
✓ Sem deadlock ou starvation
✓ Ordem respeitada corretamente
```

### 5.4 Cenário 4: Dinâmica de Clientes

**Teste:** Cliente inicia/termina durante execução

**Resultado:**
```
✓ Sistema detecta peers inativos (refresh_active_peers)
✓ Continua funcionando com subconjunto de clientes
✓ Não trava quando peer está offline
```

---

## 6. Dificuldades Encontradas e Soluções

### 6.1 Problema: Deadlock entre Clientes

**Descrição:** Clientes ficavam esperando respostas um do outro indefinidamente.

**Causa:** GRANTs adiados não eram enviados após liberação da seção crítica.

**Solução Implementada:**
```python
def release_critical_section(self):
    # Envia GRANTs para todos os clientes que foram adiados
    for client_id in self.deferred_replies:
        self.send_grant_to_client(client_id)
    self.deferred_replies.clear()
```

### 6.2 Problema: Saltos nos Timestamps

**Descrição:** Timestamps aparentavam "pular" valores.

**Causa:** Múltiplas operações (envio, recepção, update_clock) não estavam sendo logadas.

**Solução Implementada:**
- Modo debug com logs detalhados de cada mudança de clock
- Mensagens indicando razão de cada incremento
```python
def increment_clock(self, reason=""):
    if self.debug_mode:
        print(f"Clock: {old} → {new} [{reason}]")
```

---

## 7. Conclusões

### 7.1 Objetivos Alcançados

✅ **Correto:** Algoritmo de Ricart-Agrawala implementado corretamente  
✅ **Sincronização:** Relógios de Lamport funcionando perfeitamente  
✅ **Comunicação:** gRPC funcionando para cliente-servidor e cliente-cliente  
✅ **Escalabilidade:** Sistema suporta N clientes dinamicamente  
✅ **Robustez:** Tratamento de falhas e clientes inativos  

---

## 8. Referências

1. Ricart, Glenn, and Ashok K. Agrawala. "An optimal algorithm for mutual exclusion in computer networks." *Communications of the ACM* 24.1 (1981): 9-17.

2. Lamport, Leslie. "Time, clocks, and the ordering of events in a distributed system." *Concurrency: the Works of Leslie Lamport*. 2019. 179-196.

3. Documentação oficial gRPC: https://grpc.io/

4. Tanenbaum, Andrew S., and Maarten Van Steen. *Distributed systems: principles and paradigms*. Prentice-Hall, 2007.

---

## Apêndice A: Como Executar

```bash
# 1. Compilar .proto
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. printing.proto

# 2. Terminal 1: Servidor
python print_server.py

# 3. Terminal 2: Cliente 1
python smart_client.py 1 50052 50053 50054

# 4. Terminal 3: Cliente 2  
python smart_client.py 2 50053 50052 50054

# 5. Terminal 4: Cliente 3
python smart_client.py 3 50054 50052 50053

# Modo Debug
python smart_client.py 1 50052 50053 --debug
```

## Apêndice B: Estrutura de Arquivos

```
projeto/
├── printing.proto          # Definição dos serviços gRPC
├── printing_pb2.py         # Gerado automaticamente
├── printing_pb2_grpc.py    # Gerado automaticamente
├── print_server.py         # Servidor de impressão
├── smart_client.py         # Cliente inteligente
├── requirements.txt        # Dependências Python
├── README.md              # Documentação do usuário
└── RELATORIO_TECNICO.md   # Este documento
```