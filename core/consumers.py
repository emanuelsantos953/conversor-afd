import json
from channels.generic.websocket import AsyncWebsocketConsumer
from datetime import datetime
from asgiref.sync import sync_to_async
from .models import Funcionario, RegistroPonto, Grupo

class RelogioEvoConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.device_sn = None
        await self.accept()
        print("Nova conexão do Relógio Ponto WebSocket")

    async def disconnect(self, close_code):
        print(f"Conexão do relógio encerrada (Código: {close_code})")

    async def receive(self, text_data):
        try:
            message = json.loads(text_data)
            print(f"Mensagem recebida do relógio: {message}")
            
            # Comando de registro
            if "cmd" in message and message["cmd"] == "reg":
                if "sn" in message:
                    self.device_sn = message["sn"]
                    print(f"Dispositivo registrado: {self.device_sn}")

                    response = {
                        "ret": "reg",
                        "result": True,
                        "cloudtime": self.get_current_time(),
                        "nosenduser": True
                    }
                    await self.send(text_data=json.dumps(response))
            
            # Comando de envio de batidas
            elif "cmd" in message and message["cmd"] == "sendlog":
                await self.handle_send_log(message)

            # Respostas (ret) para quando nós solicitamos algo ao relógio
            elif "ret" in message:
                ret = message["ret"].lower()
                if ret == "getuserlist":
                    print("Lista de usuários recebida:", message)
                elif ret == "getnewlog":
                    print("Novos logs recebidos via getnewlog:", message)
                elif ret == "getuserinfo":
                    print("Info de usuário recebida:", message)

        except json.JSONDecodeError as e:
            print(f"Erro ao processar mensagem JSON: {e}")
            error_response = {
                "error": "Formato JSON inválido",
                "message": str(e)
            }
            await self.send(text_data=json.dumps(error_response))

    async def handle_send_log(self, message):
        print("Log recebido do dispositivo:")
        if "record" in message:
            registros = message["record"]
            print(f"Registros: {registros}")
            
            # Aqui vamos processar as batidas e salvar no banco de forma assíncrona
            await self.processar_batidas(registros)

        response = {
            "ret": "sendlog",
            "result": True,
            "cloudtime": self.get_current_time()
        }
        if "count" in message:
            response["count"] = message["count"]
        if "logindex" in message:
            response["logindex"] = message["logindex"]
        
        await self.send(text_data=json.dumps(response))

    @sync_to_async
    def processar_batidas(self, registros):
        # Essa função roda num contexto síncrono para poder acessar o ORM do Django
        dias_semana_pt = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']

        if isinstance(registros, list):
            for reg in registros:
                # Dependendo do modelo da EVO, a matrícula pode vir em 'enrollid' ou 'pin'
                # E o horário em 'time' ou algo parecido (ex: '2023-01-01 08:00:00')
                matricula = str(reg.get("enrollid", reg.get("pin", "")))
                hora_str = reg.get("time", "")

                if matricula and hora_str:
                    try:
                        # Tenta vários formatos de data/hora dependendo do modelo do relógio
                        dt_obj = None
                        for fmt in ('%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M:%S'):
                            try:
                                dt_obj = datetime.strptime(hora_str, fmt)
                                break
                            except ValueError:
                                pass
                        
                        if dt_obj:
                            data_batida = dt_obj.date()
                            hora_batida = dt_obj.time()
                            
                            funcionario = Funcionario.objects.filter(matricula=matricula).first()
                            if not funcionario:
                                funcionario = Funcionario.objects.filter(cpf=matricula).first()
                            
                            if funcionario:
                                registro, created = RegistroPonto.objects.get_or_create(
                                    funcionario=funcionario,
                                    data=data_batida,
                                    defaults={'dia_semana': dias_semana_pt[data_batida.weekday()]}
                                )
                                
                                if not registro.editado_manualmente:
                                    batidas_existentes = []
                                    for campo in ['entrada_1', 'saida_1', 'entrada_2', 'saida_2', 'entrada_3', 'saida_3']:
                                        hora_salva = getattr(registro, campo)
                                        if hora_salva:
                                            batidas_existentes.append(hora_salva)
                                            
                                    if hora_batida not in batidas_existentes and len(batidas_existentes) < 6:
                                        batidas_existentes.append(hora_batida)
                                        batidas_existentes.sort()
                                        
                                        registro.entrada_1 = batidas_existentes[0] if len(batidas_existentes) > 0 else None
                                        registro.saida_1 = batidas_existentes[1] if len(batidas_existentes) > 1 else None
                                        registro.entrada_2 = batidas_existentes[2] if len(batidas_existentes) > 2 else None
                                        registro.saida_2 = batidas_existentes[3] if len(batidas_existentes) > 3 else None
                                        registro.entrada_3 = batidas_existentes[4] if len(batidas_existentes) > 4 else None
                                        registro.saida_3 = batidas_existentes[5] if len(batidas_existentes) > 5 else None
                                        registro.save()
                                        print(f"[Channels] Batida salva: {funcionario.nome_completo} - {data_batida} {hora_batida}")
                    except Exception as e:
                        print(f"Erro ao salvar batida do relógio: {e}")

    def get_current_time(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
