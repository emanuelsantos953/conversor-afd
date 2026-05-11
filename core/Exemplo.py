import asyncio
import websockets
import json
from datetime import datetime
import threading

class SimpleWebSocketServer:
    def __init__(self, port):
        self.port = port
        self.connections = set()
        self.device_connections = {}
        self.is_running = False

    async def handle_connection(self, websocket, path):
        self.connections.add(websocket)
        print(f"Nova conexão: {websocket.remote_address}")
        print(f"Conexões ativas: {len(self.connections)}")
        self.show_console_prompt()

        try:
            async for message in websocket:
                print(f"Mensagem recebida de {websocket.remote_address}: {message}")
                try:
                    json_message = json.loads(message)

                    # Register device if it's a registration command
                    if "cmd" in json_message and json_message["cmd"] == "reg":
                        if "sn" in json_message:
                            sn = json_message["sn"]
                            self.device_connections[sn] = websocket
                            print(f"Dispositivo registrado: {sn}")

                            response = {
                                "ret": "reg",
                                "result": True,
                                "cloudtime": self.get_current_time(),
                                "nosenduser": True
                            }
                            await websocket.send(json.dumps(response))
                    
                    self.process_message(websocket, json_message)

                except json.JSONDecodeError as e:
                    print(f"Erro ao processar mensagem JSON: {e}")
                    error_response = {
                        "error": "Formato JSON inválido",
                        "message": str(e)
                    }
                    await websocket.send(json.dumps(error_response))
            
        except websockets.exceptions.ConnectionClosed as e:
            print(f"Conexão fechada: {websocket.remote_address}")
            print(f"Código: {e.code}, Razão: {e.reason}")
        finally:
            self.connections.remove(websocket)
            # Remove from device connections if it exists
            for sn, conn in list(self.device_connections.items()):
                if conn == websocket:
                    del self.device_connections[sn]
            print(f"Conexões ativas: {len(self.connections)}")
            self.show_console_prompt()

    def process_message(self, websocket, message):
        print(f"Processando mensagem JSON: {message}")
        
        if "cmd" in message:
            self.handle_command(websocket, message["cmd"], message)
        elif "ret" in message:
            self.handle_response(websocket, message["ret"], message)

    def handle_command(self, websocket, cmd, message):
        cmd = cmd.lower()
        if cmd == "reg":
            pass # Already handled
        elif cmd == "sendlog":
            self.handle_send_log(websocket, message)
        else:
            print(f"Comando não reconhecido: {cmd}")

    def handle_response(self, websocket, ret, message):
        print(f"Resposta recebida ({ret}): {message}")
        ret = ret.lower()
        if ret == "getuserlist":
            self.handle_user_list_response(message)
        elif ret == "getnewlog":
            self.handle_log_response(message)
        elif ret == "getuserinfo":
            self.handle_user_info_response(message)
        else:
            print(f"Resposta processada: {ret}")

    async def handle_send_log(self, conn, message):
        print("Log recebido do dispositivo:")
        if "record" in message:
            print(f"Registros: {message['record']}")
        
        response = {
            "ret": "sendlog",
            "result": True,
            "cloudtime": self.get_current_time()
        }
        if "count" in message:
            response["count"] = message["count"]
        if "logindex" in message:
            response["logindex"] = message["logindex"]
        
        await conn.send(json.dumps(response))

    def handle_user_list_response(self, message):
        if "result" in message and message["result"]:
            print("=== LISTA DE USUÁRIOS ===")
            if "count" in message:
                print(f"Total de usuários: {message['count']}")
            if "record" in message:
                print(f"Usuários: {message['record']}")
        else:
            print("Erro ao obter lista de usuários")
    
    def handle_log_response(self, message):
        if "result" in message and message["result"]:
            print("=== LOGS ===")
            if "count" in message:
                print(f"Total de logs: {message['count']}")
            if "record" in message:
                print(f"Registros: {message['record']}")
        else:
            print("Erro ao obter logs")
            
    def handle_user_info_response(self, message):
        if "result" in message and message["result"]:
            print("=== INFORMAÇÕES DO USUÁRIO ===")
            if "enrollid" in message:
                print(f"ID: {message['enrollid']}")
            if "name" in message:
                print(f"Nome: {message['name']}")
            if "admin" in message:
                print(f"Admin: {'Sim' if message['admin'] == 1 else 'Não'}")
            if "backupnum" in message:
                print(f"Tipo de backup: {message['backupnum']}")
        else:
            print("Erro ao obter informações do usuário")

    async def broadcast(self, message):
        if self.connections:
            await asyncio.gather(*[conn.send(message) for conn in self.connections])

    async def broadcast_json(self, json_object):
        await self.broadcast(json.dumps(json_object))

    def show_console_prompt(self):
        print("\n> ", end="", flush=True)

    def get_current_time(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async def run_server(self):
        self.is_running = True
        print(f"Servidor WebSocket iniciado na porta {self.port}")
        print("Aguardando conexões...")
        print("Digite 'help' para ver os comandos disponíveis")
        self.show_console_prompt()
        
        async with websockets.serve(self.handle_connection, "0.0.0.0", self.port):
            await asyncio.Future() # Runs forever until Ctrl+C

    def start_console_reader(self):
        async def process_command_async(input_str):
            await self.process_console_command(input_str)
        
        def run_sync():
            while True:
                try:
                    input_str = input()
                    asyncio.run_coroutine_threadsafe(process_command_async(input_str), self.loop)
                except EOFError:
                    break
                except Exception as e:
                    print(f"Erro ao processar comando: {e}")
                    self.show_console_prompt()

        self.loop = asyncio.get_event_loop()
        threading.Thread(target=run_sync, daemon=True).start()

    async def process_console_command(self, input_str):
        if not input_str.strip():
            return

        parts = input_str.strip().split()
        command = parts[0].lower()

        if command == "help":
            self.show_help()
        elif command == "list":
            if len(parts) > 1 and parts[1] == "devices":
                self.list_devices()
            else:
                await self.get_user_list()
        elif command == "logs":
            await self.get_logs()
        elif command == "adduser":
            if len(parts) >= 3:
                await self.add_user(parts[1], parts[2])
            else:
                print("Uso: adduser <id> <nome>")
        elif command == "userinfo":
            if len(parts) >= 2:
                try:
                    user_id = int(parts[1])
                    await self.get_user_info(user_id)
                except ValueError:
                    print("ID deve ser um número")
            else:
                print("Uso: userinfo <id>")
        elif command == "connections":
            self.show_connections()
        elif command in ["exit", "quit"]:
            print("Encerrando servidor...")
            self.is_running = False
            # This will stop the server gracefully
            self.loop.stop()
        else:
            print("Comando não reconhecido. Digite 'help' para ver os comandos disponíveis.")
        self.show_console_prompt()

    def show_help(self):
        print("=== COMANDOS DISPONÍVEIS ===")
        print("help              - Mostra esta ajuda")
        print("list              - Lista usuários dos dispositivos")
        print("list devices      - Lista dispositivos conectados")
        print("logs              - Obtém logs dos dispositivos")
        print("adduser <id> <nome> - Adiciona usuário")
        print("userinfo <id>     - Obtém informações de um usuário")
        print("connections       - Mostra conexões ativas")
        print("exit/quit         - Encerra o servidor")
    
    async def get_user_list(self):
        if not self.device_connections:
            print("Nenhum dispositivo conectado")
            return
        
        command = {"cmd": "getuserlist", "stn": True}
        await self.send_to_all_devices(command)

    async def get_logs(self):
        if not self.device_connections:
            print("Nenhum dispositivo conectado")
            return
        
        command = {"cmd": "getnewlog", "stn": True}
        await self.send_to_all_devices(command)
    
    async def add_user(self, enroll_id, name):
        if not self.device_connections:
            print("Nenhum dispositivo conectado")
            return
        
        try:
            user_id = int(enroll_id)
            command = {
                "cmd": "setuserinfo",
                "enrollid": user_id,
                "name": name,
                "backupnum": 0,
                "admin": 0,
                "record": ""
            }
            await self.send_to_all_devices(command)
            print(f"Comando de adicionar usuário enviado: ID={user_id}, Nome={name}")
        except ValueError:
            print("ID deve ser um número válido")

    async def get_user_info(self, user_id):
        if not self.device_connections:
            print("Nenhum dispositivo conectado")
            return
        
        command = {
            "cmd": "getuserinfo",
            "enrollid": user_id,
            "backupnum": 0
        }
        await self.send_to_all_devices(command)
        
    def list_devices(self):
        print("=== DISPOSITIVOS CONECTADOS ===")
        if not self.device_connections:
            print("Nenhum dispositivo conectado")
        else:
            for sn in self.device_connections:
                print(f"Dispositivo: {sn}")

    def show_connections(self):
        print("=== CONEXÕES ATIVAS ===")
        print(f"Total de conexões: {len(self.connections)}")
        print(f"Dispositivos registrados: {len(self.device_connections)}")
        
        for conn in self.connections:
            print(f"Conexão: {conn.remote_address}")

    async def send_to_all_devices(self, command):
        json_command = json.dumps(command)
        if self.device_connections:
            await asyncio.gather(*[
                conn.send(json_command) for conn in self.device_connections.values() if conn.open
            ])

async def main():
    port = 7788
    server = SimpleWebSocketServer(port)
    server.start_console_reader()
    await server.run_server()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServidor parado.")