import grpc
from concurrent import futures
import time
import printing_pb2
import printing_pb2_grpc

class PrintingServer(printing_pb2_grpc.PrintingServiceServicer):
    """Servidor de impressão 'burro' que apenas processa requisições de impressão.
    Não implementa nenhuma lógica de exclusão mútua - isso é responsabilidade dos clientes."""
    
    def __init__(self):
        # Relógio lógico de Lamport para ordenação de eventos
        self.lamport_clock = 0
        
    def SendToPrinter(self, request, context):
        """Processa uma requisição de impressão.
        
        Args:
            request: PrintRequest com client_id, mensagem e timestamp
            context: Contexto da chamada RPC
            
        Returns:
            PrintResponse indicando sucesso/falha da impressão
        """
        # Atualiza relógio local usando timestamp da requisição
        self.lamport_clock = max(self.lamport_clock, request.lamport_timestamp) + 1
        
        # Log da requisição recebida
        print(f"\n[Timestamp: {request.lamport_timestamp}] Cliente {request.client_id}")
        print(f"Mensagem: {request.message_content}")
        print(f"Requisicao numero: {request.request_number}")
        
        # Simula o tempo de processamento da impressão
        print("Processando impressao", end='', flush=True)
        for i in range(3):
            time.sleep(1)
            print(".", end='', flush=True)
        print(" concluido.\n")
        
        # Retorna confirmação com novo timestamp
        return printing_pb2.PrintResponse(
            success=True,
            confirmation_message=f"Impressao realizada - Cliente {request.client_id}",
            lamport_timestamp=self.lamport_clock
        )

def serve():
    """Inicializa e executa o servidor gRPC na porta 50051.
    
    Cria um servidor com pool de 10 threads para processar requisições
    concorrentes. O servidor continua rodando até receber CTRL+C."""
    
    # Cria servidor gRPC com pool de threads
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # Registra o serviço de impressão
    printing_pb2_grpc.add_PrintingServiceServicer_to_server(PrintingServer(), server)
    
    # Configura porta sem TLS (inseguro - apenas para demonstração)
    server.add_insecure_port('[::]:50051')
    server.start()
    
    print("\nServidor de Impressao")
    print("Porta: 50051")
    print("Aguardando conexoes...\n")
    
    try:
        # Bloqueia até CTRL+C
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
        server.stop(0)

if __name__ == '__main__':
    serve()