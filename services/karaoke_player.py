import time
import vlc


class KaraokePlayer:

    def __init__(self):

        self.instance = vlc.Instance(

            "--no-video-title-show",
            "--file-caching=1000",
            "--network-caching=1000",
            "--live-caching=1000"

        )

        self.player = self.instance.media_player_new()

        self.media = None

    def cargar(self, ruta):

        self.media = self.instance.media_new(ruta)

        self.player.set_media(self.media)

    def play(self):

        self.player.play()

        # Espera a que VLC empiece realmente la reproducción
        for _ in range(20):

            estado = self.player.get_state()

            if estado == vlc.State.Playing:
                break

            time.sleep(0.1)

        self.player.set_fullscreen(True)

    def pause(self):

        self.player.pause()

    def stop(self):

        self.player.stop()

        # Esperar a que realmente se detenga
        for _ in range(20):

            estado = self.player.get_state()

            if estado in (

                vlc.State.Stopped,
                vlc.State.NothingSpecial,
                vlc.State.Ended

            ):
                break

            time.sleep(0.05)

    def volumen(self, valor):

        self.player.audio_set_volume(valor)

    def tiempo(self):

        return self.player.get_time()

    def duracion(self):

        return self.player.get_length()

    def fullscreen(self):

        self.player.set_fullscreen(True)

    def salir_fullscreen(self):

        self.player.set_fullscreen(False)