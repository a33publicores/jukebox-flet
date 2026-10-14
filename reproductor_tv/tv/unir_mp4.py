"""
Une un video MP4 (sin sonido) y un audio M4A en un solo .mp4, en Python puro (sin ffmpeg).

YouTube entrega video y audio por separado y en "MP4 fragmentado" (DASH): un moov con la
descripción de la pista y luego muchos pares moof+mdat (cada par = unos segundos).
Para unirlos no hay que recodificar nada:
  * moov nuevo = el del video + la pista (trak/trex) del audio con otro número de pista;
  * después se intercalan los fragmentos de video y de audio por tiempo, para que el
    reproductor tenga imagen y sonido a la par.
Los fragmentos se copian tal cual (solo se cambian 2-3 números dentro del moof), así que
es rápido y funciona igual en el PC que en un TV Android.
"""
import os
import struct
from pathlib import Path

_CONTENEDORES = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"mvex", b"moof", b"traf", b"edts", b"dinf"}


class NoFragmentado(ValueError):
    """El archivo no es MP4 fragmentado: no se sabe unir sin ffmpeg."""


def _cajas(f, inicio, fin):
    """Cajas (tipo, posición, tamaño total, tamaño de cabecera) entre inicio y fin del archivo."""
    pos = inicio
    while pos + 8 <= fin:
        f.seek(pos)
        cab = f.read(16)
        tam, tipo = struct.unpack(">I4s", cab[:8])
        cabecera = 8
        if tam == 1:
            tam = struct.unpack(">Q", cab[8:16])[0]
            cabecera = 16
        elif tam == 0:
            tam = fin - pos
        if tam < cabecera:
            break
        yield tipo, pos, tam, cabecera
        pos += tam


def _cajas_bytes(data, inicio=0, fin=None):
    fin = len(data) if fin is None else fin
    pos = inicio
    while pos + 8 <= fin:
        tam, tipo = struct.unpack(">I4s", data[pos:pos + 8])
        cabecera = 8
        if tam == 1:
            tam = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            cabecera = 16
        elif tam == 0:
            tam = fin - pos
        if tam < cabecera:
            break
        yield tipo, pos, tam, cabecera
        pos += tam


def _buscar(data, ruta, inicio=0, fin=None):
    """Primera caja siguiendo la ruta de tipos (ej. [b"mdia", b"mdhd"]). (pos, tam, cab) o None."""
    for tipo, pos, tam, cab in _cajas_bytes(data, inicio, fin):
        if tipo == ruta[0]:
            if len(ruta) == 1:
                return pos, tam, cab
            return _buscar(data, ruta[1:], pos + cab, pos + tam)
    return None


def _caja(tipo, contenido):
    return struct.pack(">I4s", 8 + len(contenido), tipo) + contenido


class _Pista:
    """Lo necesario de un archivo de una sola pista fragmentada."""

    def __init__(self, ruta):
        self.ruta = str(ruta)
        self.ftyp = None
        self.moov = None
        self.fragmentos = []  # (pos_moof, tam_moof, [(pos_mdat, tam_mdat), ...])
        with open(self.ruta, "rb") as f:
            fin = os.fstat(f.fileno()).st_size
            actual = None
            for tipo, pos, tam, cab in _cajas(f, 0, fin):
                if tipo == b"ftyp":
                    f.seek(pos)
                    self.ftyp = f.read(tam)
                elif tipo == b"moov":
                    f.seek(pos)
                    self.moov = f.read(tam)
                elif tipo == b"moof":
                    actual = (pos, tam, [])
                    self.fragmentos.append(actual)
                elif tipo == b"mdat" and actual is not None:
                    actual[2].append((pos, tam))
        if self.moov is None:
            raise NoFragmentado(f"{self.ruta}: no tiene moov")
        if not self.fragmentos or _buscar(self.moov, [b"moov", b"mvex"]) is None:
            raise NoFragmentado(f"{self.ruta}: no es MP4 fragmentado")
        m = _buscar(self.moov, [b"moov", b"trak"])
        if m is None:
            raise NoFragmentado(f"{self.ruta}: sin pista")
        self.trak = self.moov[m[0]:m[0] + m[1]]
        x = _buscar(self.moov, [b"moov", b"mvex", b"trex"])
        self.trex = self.moov[x[0]:x[0] + x[1]] if x else None
        # escala de tiempo de la pista (mdhd) para ordenar fragmentos por segundos
        md = _buscar(self.trak, [b"trak", b"mdia", b"mdhd"])
        p = md[0] + md[2]
        version = self.trak[p]
        self.escala = struct.unpack(">I", self.trak[p + (20 if version == 1 else 12):][:4])[0] or 1

    def tiempos(self):
        """Segundo en que empieza cada fragmento (tfdt). Si falta, se reparte por posición."""
        salida = []
        with open(self.ruta, "rb") as f:
            for i, (pos, tam, _) in enumerate(self.fragmentos):
                f.seek(pos)
                moof = f.read(tam)
                t = _buscar(moof, [b"moof", b"traf", b"tfdt"])
                if t:
                    p = t[0] + t[2]
                    v = moof[p]
                    base = struct.unpack(">Q" if v == 1 else ">I", moof[p + 4:p + (12 if v == 1 else 8)])[0]
                    salida.append(base / self.escala)
                else:
                    salida.append(None)
        if any(s is None for s in salida):
            n = len(salida)
            salida = [i / max(1, n) for i in range(n)]
        return salida


def _cambiar_track_id_tkhd(trak, nuevo):
    trak = bytearray(trak)
    t = _buscar(bytes(trak), [b"trak", b"tkhd"])
    p = t[0] + t[2]
    off = p + (20 if trak[p] == 1 else 12)
    trak[off:off + 4] = struct.pack(">I", nuevo)
    return bytes(trak)


def _cambiar_track_id_trex(trex, nuevo):
    trex = bytearray(trex)
    trex[12:16] = struct.pack(">I", nuevo)  # 8 cabecera + 4 versión/flags
    return bytes(trex)


def _armar_moov(video, audio):
    """moov del video + trak/trex del audio como pista 2."""
    hijos = []
    m = _buscar(video.moov, [b"moov"])
    mehd = None
    for tipo, pos, tam, cab in _cajas_bytes(video.moov, m[0] + m[2], m[0] + m[1]):
        caja = video.moov[pos:pos + tam]
        if tipo == b"mvhd":
            caja = bytearray(caja)
            caja[-4:] = struct.pack(">I", 3)  # next_track_ID
            hijos.append(bytes(caja))
        elif tipo == b"trak":
            hijos.append(_cambiar_track_id_tkhd(caja, 1))
            hijos.append(_cambiar_track_id_tkhd(audio.trak, 2))
        elif tipo == b"mvex":
            mh = _buscar(caja, [b"mvex", b"mehd"])
            if mh:
                mehd = caja[mh[0]:mh[0] + mh[1]]
        elif tipo in (b"udta", b"meta", b"pssh", b"iods"):
            hijos.append(caja)
    trex_v = _cambiar_track_id_trex(video.trex, 1) if video.trex else b""
    trex_a = _cambiar_track_id_trex(audio.trex, 2) if audio.trex else b""
    hijos.append(_caja(b"mvex", (mehd or b"") + trex_v + trex_a))
    return _caja(b"moov", b"".join(hijos))


def _ajustar_moof(moof, track_id, secuencia, desplazamiento):
    """Cambia el número de pista (tfhd), el número de fragmento (mfhd) y, si el moof usa
    posición absoluta en el archivo (base-data-offset), la corre a su nueva posición."""
    moof = bytearray(moof)
    datos = bytes(moof)
    mf = _buscar(datos, [b"moof", b"mfhd"])
    if mf:
        p = mf[0] + mf[2]
        moof[p + 4:p + 8] = struct.pack(">I", secuencia)
    m = _buscar(datos, [b"moof"])
    for tipo, pos, tam, cab in _cajas_bytes(datos, m[0] + m[2], m[0] + m[1]):
        if tipo != b"traf":
            continue
        th = _buscar(datos, [b"tfhd"], pos + cab, pos + tam)
        if not th:
            continue
        p = th[0] + th[2]
        flags = struct.unpack(">I", datos[p:p + 4])[0] & 0xFFFFFF
        moof[p + 4:p + 8] = struct.pack(">I", track_id)
        if flags & 0x000001:  # base-data-offset-present: posición absoluta
            viejo = struct.unpack(">Q", datos[p + 8:p + 16])[0]
            moof[p + 8:p + 16] = struct.pack(">Q", viejo + desplazamiento)
    return bytes(moof)


def unir(video_ruta, audio_ruta, destino):
    """Escribe `destino` (.mp4) con el video y el audio juntos. Lanza NoFragmentado si
    algún archivo no es MP4 fragmentado."""
    video, audio = _Pista(video_ruta), _Pista(audio_ruta)
    orden = sorted(
        [(t, 0, i) for i, t in enumerate(video.tiempos())]
        + [(t, 1, i) for i, t in enumerate(audio.tiempos())],
        key=lambda x: (x[0], x[1]))
    destino = Path(destino)
    tmp = destino.with_name(destino.name + ".uniendo")
    with open(tmp, "wb") as out, open(video.ruta, "rb") as fv, open(audio.ruta, "rb") as fa:
        out.write(video.ftyp or _caja(b"ftyp", b"isom\x00\x00\x02\x00isomiso6mp41"))
        out.write(_armar_moov(video, audio))
        for secuencia, (_, cual, i) in enumerate(orden, start=1):
            pista, f = (video, fv) if cual == 0 else (audio, fa)
            pos_moof, tam_moof, mdats = pista.fragmentos[i]
            f.seek(pos_moof)
            moof = f.read(tam_moof)
            nueva_pos = out.tell()
            out.write(_ajustar_moof(moof, 1 if cual == 0 else 2, secuencia, nueva_pos - pos_moof))
            # el mdat va justo después de su moof (como en el original): los offsets relativos
            # al moof siguen valiendo
            for pos_mdat, tam_mdat in mdats:
                f.seek(pos_mdat)
                faltan = tam_mdat
                while faltan > 0:
                    trozo = f.read(min(faltan, 1024 * 1024))
                    if not trozo:
                        raise IOError("archivo cortado")
                    out.write(trozo)
                    faltan -= len(trozo)
    os.replace(tmp, destino)
    return str(destino)
