import grpc
from concurrent import futures
import time
import threading
import random
import sys
import printing_pb2
import printing_pb2_grpc

class SmartClient(printing_pb2_grpc.MutualExclusionServiceServicer):
    def __init__(self, client_id, port, other_clients_ports):
        self.client_id = client_id
        self.port = port
        self.configured_peers = [p for p in sorted(set(other_clients_ports)) if p != port]
        self.other_clients_ports = self.configured_peers.copy()
        
        self.lamport_clock = 0
        self.clock_lock = threading.Lock()
        
        self.requesting_cs = False
        self.in_cs = False
        self.request_timestamp = 0
        self.request_number = 0
        self.replies_received = 0
        self.deferred_replies = []
        
        self.cs_lock = threading.Lock()
        self.reply_lock = threading.Lock()
        self.server = None
        
        self.print_separator = "="*50  # Adicionar separador visual
    
        self.max_retries = 3  # Número máximo de tentativas
        self.retry_delay = 2  # Delay base entre tentativas (segundos)

    def increment_clock(self):
        with self.clock_lock:
            self.lamport_clock += 1
            return self.lamport_clock
    
    def update_clock(self, received_timestamp):
        with self.clock_lock:
            self.lamport_clock = max(self.lamport_clock, received_timestamp) + 1
            return self.lamport_clock
    
    def RequestAccess(self, request, context):
        current_clock = self.update_clock(request.lamport_timestamp)
        
        print(f"\n{self.print_separator}")
        print(f"↓ REQUISIÇÃO RECEBIDA [TS: {request.lamport_timestamp}]")
        print(f"  • De: Cliente {request.client_id}")
        print(f"  • Estado local: {'OCUPADO' if (self.requesting_cs or self.in_cs) else 'LIVRE'}")
        
        with self.cs_lock:
            if self.requesting_cs or self.in_cs:
                our_priority = (self.request_timestamp, self.client_id)
                their_priority = (request.lamport_timestamp, request.client_id)
                
                # Se timestamps iguais, menor ID tem prioridade
                if request.lamport_timestamp == self.request_timestamp:
                    if self.client_id > request.client_id:
                        their_priority = (request.lamport_timestamp - 1, request.client_id)
                    else:
                        our_priority = (self.request_timestamp - 1, self.client_id)
                
                if our_priority < their_priority:
                    self.deferred_replies.append(request.client_id)
                    print(f"  ⏳ Adiando resposta - nossa prioridade é maior")
                    print(f"     (TS:{self.request_timestamp} < TS:{request.lamport_timestamp})")
                    print(f"{self.print_separator}")
                    return printing_pb2.AccessResponse(
                        access_granted=False,
                        lamport_timestamp=current_clock
                    )
                else:
                    print(f"  ⌛ Nossa prioridade é menor - concedendo acesso")
                    print(f"     (TS:{self.request_timestamp} > TS:{request.lamport_timestamp})")
        
        print(f"  ✓ Acesso concedido")
        print(f"{self.print_separator}")
        return printing_pb2.AccessResponse(
            access_granted=True,
            lamport_timestamp=current_clock
        )
    
    def request_critical_section(self):
        retries = 0
        while retries < self.max_retries:
            self.request_number += 1
            current_ts = self.increment_clock()
            
            print(f"\n{self.print_separator}")
            print(f"→ SOLICITANDO SEÇÃO CRÍTICA")
            print(f"  • Timestamp: {current_ts}")
            print(f"  • Requisição #{self.request_number}")
            if retries > 0:
                print(f"  • Tentativa {retries + 1}/{self.max_retries}")
            
            with self.cs_lock:
                self.requesting_cs = True
                self.request_timestamp = current_ts
                self.replies_received = 0
            
            self.refresh_active_peers()
            
            if not self.other_clients_ports:
                print("  ✓ Sem outros clientes ativos - acesso imediato")
                with self.cs_lock:
                    self.requesting_cs = False
                    self.in_cs = True
                return True

            for other_port in self.other_clients_ports:
                self.send_request_to_client(other_port, current_ts)
            
            if self.wait_for_replies():
                with self.cs_lock:
                    self.requesting_cs = False
                    self.in_cs = True
                print(f"  ✓ Acesso concedido (TS: {current_ts})")
                return True
            
            retries += 1
            if retries < self.max_retries:
                delay = self.retry_delay * (1 + random.random())  # Adiciona jitter
                print(f"  ↻ Tentando novamente em {delay:.1f}s...")
                time.sleep(delay)
        
        print("  ⚠ Número máximo de tentativas excedido")
        with self.cs_lock:
            self.requesting_cs = False
        return False

    def send_request_to_client(self, port, timestamp):
        try:
            channel = grpc.insecure_channel(f'localhost:{port}')
            stub = printing_pb2_grpc.MutualExclusionServiceStub(channel)
            
            request = printing_pb2.AccessRequest(
                client_id=self.client_id,
                lamport_timestamp=timestamp,
                request_number=self.request_number
            )
            
            response = stub.RequestAccess(request, timeout=10)
            
            with self.reply_lock:
                if response.access_granted:  # Só conta como resposta se access_granted=True
                    self.replies_received += 1
            self.update_clock(response.lamport_timestamp)
            
            status = "✓ OK" if response.access_granted else "⏳ Adiado"
            print(f"  • Porta {port}: {status}")
            
            channel.close()
        except grpc.RpcError:
            print(f"Porta {port} inativa — contando como resposta.")
            with self.reply_lock:
                self.replies_received += 1
    
    def wait_for_replies(self):
        required_replies = len(self.other_clients_ports)
        print(f"\n  Aguardando {required_replies} respostas...")
        print(f"  Peers ativos: {self.other_clients_ports}")
        
        timeout = time.time() + 30
        while True:
            with self.reply_lock:
                if self.replies_received >= required_replies:
                    break
            if time.time() > timeout:
                print("  ⚠ Timeout esperando respostas!")
                # Não deveria prosseguir em caso de timeout
                with self.cs_lock:
                    self.requesting_cs = False
                return False  # Retorna False indicando falha
            time.sleep(0.1)

        return True  # Retorna True indicando sucesso

    def release_critical_section(self):
        current_ts = self.increment_clock()
        
        print(f"\n{self.print_separator}")
        print(f"← LIBERANDO SEÇÃO CRÍTICA")
        print(f"  • Timestamp: {current_ts}")
        if self.deferred_replies:
            print(f"  • Respostas adiadas para: {self.deferred_replies}")
        
        with self.cs_lock:
            self.in_cs = False
            deferred = self.deferred_replies.copy()
            self.deferred_replies.clear()
        
        self.refresh_active_peers()
        for other_port in self.other_clients_ports:
            self.send_release_to_client(other_port, current_ts)

        for deferred_client_id in deferred:
            target_port = 50052 + (deferred_client_id - 1)
            if target_port == self.port:
                continue
            self.send_release_to_client(target_port, current_ts)

    def refresh_active_peers(self, timeout=1.0):
        """
        Check which configured peers are currently reachable and update self.other_clients_ports.
        Uses grpc.channel_ready_future to detect whether a server is accepting connections.
        """
        active = []
        for port in self.configured_peers:
            try:
                channel = grpc.insecure_channel(f'localhost:{port}')
                grpc.channel_ready_future(channel).result(timeout=timeout)
                active.append(port)
                channel.close()
            except Exception:
                print(f"Porta {port} parece inativa.")
        self.other_clients_ports = active
    
    def send_release_to_client(self, port, timestamp):
        try:
            channel = grpc.insecure_channel(f'localhost:{port}')
            stub = printing_pb2_grpc.MutualExclusionServiceStub(channel)
            
            release = printing_pb2.AccessRelease(
                client_id=self.client_id,
                lamport_timestamp=timestamp,
                request_number=self.request_number
            )
            
            stub.ReleaseAccess(release, timeout=5)
            channel.close()
        except grpc.RpcError:
            print(f"Nao foi possivel enviar release para porta {port} (inativa).")
    
    def send_grant_to_client(self, client_id, timestamp):
        try:
            target_port = 50052 + (client_id - 1)
            channel = grpc.insecure_channel(f'localhost:{target_port}')
            stub = printing_pb2_grpc.MutualExclusionServiceStub(channel)
            
            response = printing_pb2.AccessResponse(
                access_granted=True,
                lamport_timestamp=timestamp
            )
            
            print(f"Enviando grant para Cliente {client_id}")
            channel.close()
        except grpc.RpcError as e:
            print(f"Erro ao enviar grant para Cliente {client_id}: {e}")
            
    def send_to_printer(self, message):
        try:
            channel = grpc.insecure_channel('localhost:50051')
            stub = printing_pb2_grpc.PrintingServiceStub(channel)
            
            current_ts = self.increment_clock()
            
            request = printing_pb2.PrintRequest(
                client_id=self.client_id,
                message_content=message,
                lamport_timestamp=current_ts,
                request_number=self.request_number
            )
            
            print(f"\n{self.print_separator}")
            print(f"📨 ENVIANDO PARA IMPRESSÃO")
            print(f"  • Mensagem: {message}")
            print(f"  • Timestamp: {current_ts}")
            response = stub.SendToPrinter(request, timeout=10)
            
            self.update_clock(response.lamport_timestamp)
            print(f"  ✓ {response.confirmation_message}")
            print(f"{self.print_separator}")
            
            channel.close()
            return True
        except grpc.RpcError as e:
            print(f"Erro ao conectar com servidor: {e}")
            return False
    
    def ReleaseAccess(self, request, context):
        current_clock = self.update_clock(request.lamport_timestamp)
        print(f"\n{self.print_separator}")
        print(f"↑ RELEASE RECEBIDO [TS: {request.lamport_timestamp}]")
        print(f"  • De: Cliente {request.client_id}")
        return printing_pb2.EmptyResponse()

    def start_server(self):
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        printing_pb2_grpc.add_MutualExclusionServiceServicer_to_server(self, self.server)
        self.server.add_insecure_port(f'[::]:{self.port}')
        self.server.start()
        print(f"Cliente {self.client_id} iniciado na porta {self.port}")
    
    def run(self):
        print(f"\nCliente {self.client_id}")
        print(f"Porta: {self.port}")
        print(f"Outros clientes: {self.other_clients_ports}\n")
        
        self.start_server()
        time.sleep(2)
        
        message_count = 0
        while True:
            try:
                wait_time = random.randint(5, 15)
                print(f"\nAguardando {wait_time}s ate proxima requisicao...")
                time.sleep(wait_time)
                
                message_count += 1
                message = f"Documento #{message_count} do Cliente {self.client_id}"
                
                if self.request_critical_section():
                    self.send_to_printer(message)
                    self.release_critical_section()
                else:
                    print("  ⚠ Tentando novamente em alguns segundos...")
                
            except KeyboardInterrupt:
                print(f"\nCliente {self.client_id} encerrado.")
                break
        
        if self.server:
            self.server.stop(0)

def main():
    if len(sys.argv) < 3:
        print("Uso: python smart_client.py <client_id> <port> [other_ports...]")
        print("Exemplo: python smart_client.py 1 50052 50053 50054")
        sys.exit(1)
    
    client_id = int(sys.argv[1])
    port = int(sys.argv[2])
    other_ports = [int(p) for p in sys.argv[3:]]
    
    client = SmartClient(client_id, port, other_ports)
    client.run()

if __name__ == '__main__':
    main()