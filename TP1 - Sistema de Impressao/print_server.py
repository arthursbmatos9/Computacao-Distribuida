import grpc
from concurrent import futures
import time
import printing_pb2
import printing_pb2_grpc

class PrintingServer(printing_pb2_grpc.PrintingServiceServicer):
    def __init__(self):
        self.lamport_clock = 0
        
    def SendToPrinter(self, request, context):
        self.lamport_clock = max(self.lamport_clock, request.lamport_timestamp) + 1
        
        print(f"\n[Timestamp: {request.lamport_timestamp}] Cliente {request.client_id}")
        print(f"Mensagem: {request.message_content}")
        print(f"Requisicao numero: {request.request_number}")
        
        print("Processando impressao", end='', flush=True)
        for i in range(3):
            time.sleep(1)
            print(".", end='', flush=True)
        print(" concluido.\n")
        
        return printing_pb2.PrintResponse(
            success=True,
            confirmation_message=f"Impressao realizada - Cliente {request.client_id}",
            lamport_timestamp=self.lamport_clock
        )

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    printing_pb2_grpc.add_PrintingServiceServicer_to_server(PrintingServer(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    
    print("\nServidor de Impressao")
    print("Porta: 50051")
    print("Aguardando conexoes...\n")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
        server.stop(0)

if __name__ == '__main__':
    serve()