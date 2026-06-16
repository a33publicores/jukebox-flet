import requests

BASE_URL = "https://jukebox-bot-production.up.railway.app"


class APIClient:

    @staticmethod
    def validar_cliente(codigo):

        response = requests.get(
            f"{BASE_URL}/validar_cliente",
            params={"codigo": codigo},
            timeout=15
        )

        return response.json()

    @staticmethod
    def buscar(query):

        response = requests.get(
            f"{BASE_URL}/buscar",
            params={"q": query},
            timeout=15
        )

        return response.json()

    @staticmethod
    def agregar_cancion(
        cliente,
        telefono,
        titulo,
        canal,
        video_id
    ):

        payload = {
            "tipo": "cancion",
            "cliente": cliente,
            "telefono": telefono,
            "titulo": titulo,
            "canal": canal,
            "videoId": video_id
            
        }

        response = requests.post(
            f"{BASE_URL}/",
            json=payload,
            timeout=20
        )
        
        print("STATUS:", response.status_code)
        print("RESPUESTA:", response.text)

        return response.text
    
    @staticmethod
    def estado_usuario(
        cliente,
        telefono
    ):

        response = requests.get(
            f"{BASE_URL}/estado_usuario",
            params={
                "cliente": cliente,
                "telefono": telefono
            },
            timeout=15
        )

        return response.json()
    
    @staticmethod
    def estado_cola(cliente):

        response = requests.get(
            f"{BASE_URL}/estado_cola",
            params={
                "cliente": cliente
            },
            timeout=15
        )

        return response.json()
    
    @staticmethod
    def obtener_mis_canciones(
        cliente,
        telefono
    ):

        response = requests.get(
            f"{BASE_URL}/mis_canciones",
            params={
                "cliente": cliente,
                "telefono": telefono
            },
            timeout=15
        )

        return response.json()
