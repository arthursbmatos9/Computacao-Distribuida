import grpc
from concurrent import futures
import time
import threading
import random
import sys
import printing_pb2
import printing_pb2_grpc

class SmartClient(printing_pb2_grpc.MutualExclusionServiceServicer):
    """Cliente que participa do algoritmo distribuído de exclusão mútua.

    Implementa uma versão do algoritmo Ricart-Agrawala usando relógios de Lamport
    para ordenar requisições. Cada cliente expõe dois RPCs (RequestAccess e
    ReleaseAccess) para negociar acesso à seção crítica. Quando um pedido é
    adiado, guardamos o ID e, ao liberar a seção crítica, notificamos os
    clientes adiados (neste código usamos ReleaseAccess como notificação).
    """
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
        self.deferred_replies = []  # Armazena client_id dos requests adiados
        
        self.cs_lock = threading.Lock()
        self.reply_lock = threading.Lock()
        self.server = None
        
        self.print_separator = "="*50
    
        self.max_retries = 3
        self.retry_delay = 2

    def increment_clock(self):
        # Incrementa o relógio de Lamport de forma atômica e retorna o novo valor.
        # Deve ser chamado sempre que este processo gera um evento local (ex.:
        # antes de enviar uma requisição) para garantir ordenação correta.
        with self.clock_lock:
            self.lamport_clock += 1
            return self.lamport_clock
    
    def update_clock(self, received_timestamp):
        # Atualiza o relógio local usando o timestamp recebido (regra de Lamport):
        # L = max(L, received) + 1
        # Deve ser chamado ao receber mensagens para manter a ordenação global.
        with self.clock_lock:
            self.lamport_clock = max(self.lamport_clock, received_timestamp) + 1
            return self.lamport_clock
    
    def RequestAccess(self, request, context):
        """Recebe requisição de acesso (RPC) de outro cliente.

            Lógica:
            - Atualiza o relógio com o timestamp recebido.
            - Se este cliente não está interessado na SC, concede o acesso.
            - Se estiver interessado/ocupado, compara prioridades (timestamp, client_id).
                O par (timestamp, client_id) determina a prioridade: menor par => maior
                prioridade para entrar primeiro.
            - Se nossa prioridade for maior, adiamos a resposta (guardamos o ID).
                Caso contrário, concedemos imediatamente.

            Observação: a implementação atual armazena apenas os IDs nas respostas
            adiadas e envia uma notificação via ReleaseAccess quando libera a SC.
            Uma implementação mais robusta seria ter um RPC específico de GRANT.
        """
        current_clock = self.update_clock(request.lamport_timestamp)
        
        print(f"\n{self.print_separator}")
        print(f"↓ REQUISIÇÃO RECEBIDA [TS: {request.lamport_timestamp}]")
        print(f"  • De: Cliente {request.client_id}")
        print(f"  • Estado local: {'OCUPADO' if (self.requesting_cs or self.in_cs) else 'LIVRE'}")
        
        with self.cs_lock:
            # Se não estamos interessados na seção crítica, concede imediatamente
            if not self.requesting_cs and not self.in_cs:
                print(f"  ✓ Acesso concedido imediatamente")
                print(f"{self.print_separator}")
                return printing_pb2.AccessResponse(
                    access_granted=True,
                    lamport_timestamp=current_clock
                )
            
            # Se estamos interessados, compara prioridades
            our_priority = (self.request_timestamp, self.client_id)
            their_priority = (request.lamport_timestamp, request.client_id)
            
            if our_priority < their_priority:
                # Nossa prioridade é maior - adia a resposta
                # Guardamos o ID do cliente para enviar GRANTs quando liberarmos
                self.deferred_replies.append(request.client_id)
                print(f"  ⏳ Adiando resposta - nossa prioridade é maior")
                print(f"     Nossa: (TS:{self.request_timestamp}, ID:{self.client_id})")
                print(f"     Deles: (TS:{request.lamport_timestamp}, ID:{request.client_id})")
                print(f"{self.print_separator}")
                # Retorna False para indicar que a resposta foi adiada
                return printing_pb2.AccessResponse(
                    access_granted=False,
                    lamport_timestamp=current_clock
                )
            else:
                # Nossa prioridade é menor - concede acesso
                print(f"  ✓ Concedendo acesso - nossa prioridade é menor")
                print(f"     Nossa: (TS:{self.request_timestamp}, ID:{self.client_id})")
                print(f"     Deles: (TS:{request.lamport_timestamp}, ID:{request.client_id})")
                print(f"{self.print_separator}")
                return printing_pb2.AccessResponse(
                    access_granted=True,
                    lamport_timestamp=current_clock
                )
    
    def request_critical_section(self):
        """Solicita entrada na seção crítica usando Ricart-Agrawala.

        Passos principais:
        1. Incrementa o relógio e marca que está requisitando a CS.
        2. Envia Request (RPC) para todos peers ativos.
        3. Aguarda GRANTs (aqui modelados como AccessResponse.access_granted=True
           ou notificações via ReleaseAccess que incrementam replies_received).
        4. Ao receber todos os GRANTs, entra na CS; caso contrário, desiste.
        """
        self.request_number += 1
        current_ts = self.increment_clock()
        
        print(f"\n{self.print_separator}")
        print(f"→ SOLICITANDO SEÇÃO CRÍTICA")
        print(f"  • Timestamp: {current_ts}")
        print(f"  • Requisição #{self.request_number}")
        
        with self.cs_lock:
            self.requesting_cs = True
            self.request_timestamp = current_ts
            self.replies_received = 0
        
        self.refresh_active_peers()
        
        if not self.other_clients_ports:
            print("  ✓ Sem outros clientes ativos - acesso imediato")
            print(f"{self.print_separator}")
            with self.cs_lock:
                self.requesting_cs = False
                self.in_cs = True
            return True

        # Envia REQUEST para todos os outros clientes
        for other_port in self.other_clients_ports:
            self.send_request_to_client(other_port, current_ts)
        
        # Aguarda todas as respostas GRANT
        if self.wait_for_replies():
            with self.cs_lock:
                self.requesting_cs = False
                self.in_cs = True
            print(f"  ✓ Todas as permissões recebidas - entrando na SC")
            print(f"{self.print_separator}")
            return True
        
        print(f"  ✗ Falha ao obter todas as permissões")
        print(f"{self.print_separator}")
        with self.cs_lock:
            self.requesting_cs = False
        return False

    def send_request_to_client(self, port, timestamp):
        """Envia requisição de acesso para um cliente específico.

        Nota sobre timeouts: se o peer estiver inativo ou o stub levantar um
        RpcError, contamos isso como um GRANT (assumimos que esse peer não está
        participando). Se o peer responder com access_granted=False, isso indica
        que o peer adiou a resposta e esperará até liberar a CS para notificar.
        """
        try:
            channel = grpc.insecure_channel(f'localhost:{port}')
            stub = printing_pb2_grpc.MutualExclusionServiceStub(channel)
            
            request = printing_pb2.AccessRequest(
                client_id=self.client_id,
                lamport_timestamp=timestamp,
                request_number=self.request_number
            )
            
            response = stub.RequestAccess(request, timeout=10)
            # Atualiza relógio local com timestamp da resposta
            self.update_clock(response.lamport_timestamp)

            # Só conta como resposta se foi concedido acesso
            if response.access_granted:
                with self.reply_lock:
                    self.replies_received += 1
                print(f"  • Porta {port}: ✓ GRANT recebido")
            else:
                # access_granted=False => peer adiou; ele irá notificar (via ReleaseAccess)
                print(f"  • Porta {port}: ⏳ Resposta adiada (aguardando liberação)")
            
            channel.close()
        except grpc.RpcError as e:
            print(f"  • Porta {port}: ✗ Inativa (contando como grant)")
            with self.reply_lock:
                self.replies_received += 1
    
    def wait_for_replies(self):
        """Aguarda respostas GRANT de todos os clientes ativos"""
        required_replies = len(self.other_clients_ports)
        print(f"\n  Aguardando {required_replies} GRANTs...")
        print(f"  Peers ativos: {self.other_clients_ports}")
        
        # Timeout razoável para esperar GRANTs (pode ser ajustado conforme necessidade)
        timeout = time.time() + 60  # Aumentado para 60 segundos
        while True:
            with self.reply_lock:
                current = self.replies_received

            if current >= required_replies:
                print(f"  ✓ Todos os {required_replies} GRANTs recebidos!")
                return True

            if time.time() > timeout:
                print(f"  ⚠ Timeout! Recebidos {current}/{required_replies} GRANTs")
                return False

            time.sleep(0.1)

    def release_critical_section(self):
        """Libera a seção crítica e envia GRANTs para requisições adiadas.

        Ao liberar, atualizamos o relógio, marcamos in_cs=False e notificamos
        todos os clientes cujas requisições foram adiadas. A notificação é feita
        hoje via RPC ReleaseAccess (um pouco impropriamente, já que o .proto não
        possui um método Grant explícito), que por sua vez incrementa
        replies_received no cliente solicitante.
        """
        current_ts = self.increment_clock()
        
        print(f"\n{self.print_separator}")
        print(f"← LIBERANDO SEÇÃO CRÍTICA")
        print(f"  • Timestamp: {current_ts}")
        
        # Marca que não está mais na seção crítica e captura a lista de adiados
        with self.cs_lock:
            self.in_cs = False
            deferred = self.deferred_replies.copy()
            self.deferred_replies.clear()
        
        # Envia notificação (GRANT) para cada cliente cujo pedido foi adiado
        if deferred:
            print(f"  • Enviando GRANTs adiados para clientes: {deferred}")
            for client_id in deferred:
                self.send_grant_to_client(client_id, current_ts)
        else:
            print(f"  • Sem GRANTs adiados para enviar")
        
        print(f"{self.print_separator}")

    def refresh_active_peers(self, timeout=1.0):
        """Verifica quais peers configurados estão atualmente acessíveis"""
        active = []
        for port in self.configured_peers:
            try:
                channel = grpc.insecure_channel(f'localhost:{port}')
                grpc.channel_ready_future(channel).result(timeout=timeout)
                active.append(port)
                channel.close()
            except Exception:
                pass  # Peer inativo
        self.other_clients_ports = active
    
    def send_grant_to_client(self, client_id, timestamp):
        """Envia GRANT (resposta adiada) para um cliente específico"""
        try:
            target_port = 50052 + (client_id - 1)
            if target_port == self.port:
                return
            
            channel = grpc.insecure_channel(f'localhost:{target_port}')
            stub = printing_pb2_grpc.MutualExclusionServiceStub(channel)
            
            # Envia um AccessRequest "fake" que será interpretado como GRANT
            # Na prática, seria melhor ter um método específico para isso
            response = printing_pb2.AccessResponse(
                access_granted=True,
                lamport_timestamp=timestamp
            )
            
            # Como não temos um método para enviar GRANT diretamente,
            # vamos usar o ReleaseAccess como notificação
            release = printing_pb2.AccessRelease(
                client_id=self.client_id,
                lamport_timestamp=timestamp,
                request_number=self.request_number
            )
            
            stub.ReleaseAccess(release, timeout=5)
            print(f"    ✓ GRANT enviado para Cliente {client_id}")
            
            channel.close()
        except grpc.RpcError as e:
            print(f"    ✗ Erro ao enviar GRANT para Cliente {client_id}")
    
    def send_to_printer(self, message):
        """Envia documento para o servidor de impressão"""
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
            print(f"  ✗ Erro ao conectar com servidor: {e}")
            print(f"{self.print_separator}")
            return False
    
    def ReleaseAccess(self, request, context):
        """Recebe notificação de liberação de outro cliente"""
        current_clock = self.update_clock(request.lamport_timestamp)
        
        print(f"\n{self.print_separator}")
        print(f"↑ RELEASE/GRANT RECEBIDO [TS: {request.lamport_timestamp}]")
        print(f"  • De: Cliente {request.client_id}")
        print(f"{self.print_separator}")
        
        # Incrementa o contador de respostas recebidas
        with self.reply_lock:
            self.replies_received += 1
        
        return printing_pb2.EmptyResponse()

    def start_server(self):
        """Inicia o servidor gRPC para receber requisições de outros clientes"""
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        printing_pb2_grpc.add_MutualExclusionServiceServicer_to_server(self, self.server)
        self.server.add_insecure_port(f'[::]:{self.port}')
        self.server.start()
        print(f"\n{'='*50}")
        print(f"Cliente {self.client_id} iniciado na porta {self.port}")
        print(f"Peers configurados: {self.configured_peers}")
        print(f"{'='*50}\n")
    
    def run(self):
        """Loop principal do cliente"""
        self.start_server()
        time.sleep(2)
        
        message_count = 0
        while True:
            try:
                wait_time = random.randint(5, 15)
                print(f"\n💤 Aguardando {wait_time}s até próxima requisição...")
                time.sleep(wait_time)
                
                message_count += 1
                message = f"Documento #{message_count} do Cliente {self.client_id}"
                
                # Tenta entrar na seção crítica
                if self.request_critical_section():
                    # Envia para impressão
                    self.send_to_printer(message)
                    # Libera a seção crítica
                    time.sleep(1)  # Pequeno delay antes de liberar
                    self.release_critical_section()
                else:
                    print(f"  ⚠ Falha ao obter acesso - tentando novamente em breve")
                
            except KeyboardInterrupt:
                print(f"\n\n{'='*50}")
                print(f"Cliente {self.client_id} encerrando...")
                print(f"{'='*50}\n")
                break
            except Exception as e:
                print(f"\n⚠ Erro inesperado: {e}")
                time.sleep(2)
        
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