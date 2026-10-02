import unicodedata


class KaraokeSearch:

    @staticmethod
    def normalizar(texto):

        texto = texto.lower()

        texto = unicodedata.normalize(
            "NFD",
            texto
        )

        texto = "".join(

            c for c in texto

            if unicodedata.category(c) != "Mn"

        )

        return texto


    @classmethod
    def buscar(cls, canciones, texto):

        if not texto:

            return canciones

        texto = cls.normalizar(texto)

        resultado = []

        for cancion in canciones:

            titulo = cls.normalizar(
                cancion["titulo"]
            )

            artista = cls.normalizar(
                cancion["artista"]
            )

            if (

                texto in titulo

                or

                texto in artista

            ):

                resultado.append(cancion)

        return resultado