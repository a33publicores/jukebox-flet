"""
Géneros musicales para el RELLENO (lo que suena cuando nadie pide).

YouTube no dice el género de una canción, así que se deduce del título y del canal:
nombre del artista + palabras como "vallenato", "salsa", "corrido"... Pensado para lo que
suena en los bares de Colombia. Lo que no se reconoce queda como "otros".

El administrador del bar escoge en el panel qué géneros quiere de relleno (control.generos)
y el reproductor solo pone canciones de esos géneros. Los PEDIDOS siempre suenan.
"""
import re
import unicodedata
from functools import lru_cache

GENEROS = [  # (clave, nombre en pantalla)
    ("popular", "Popular / Despecho"),
    ("vallenato", "Vallenato"),
    ("salsa", "Salsa"),
    ("merengue", "Merengue"),
    ("bachata", "Bachata"),
    ("urbano", "Reggaetón / Urbano"),
    ("mexicana", "Regional mexicana"),
    ("tropical", "Tropical / Bailable"),
    ("champeta", "Champeta"),
    ("baladas", "Baladas"),
    ("rock_pop", "Rock / Pop"),
    ("otros", "Otros"),
]
NOMBRES = dict(GENEROS)

# Palabras que delatan el género (en título o canal). Peso alto.
_PALABRAS = {
    "vallenato": ["vallenat", "sentir vallenato"],
    "salsa": ["salsa", "salsa power"],
    "merengue": ["merengue", "merengon"],
    "bachata": ["bachata"],
    "urbano": ["reggaeton", "reguetón", "dembow", "trap", "perreo", "urbano"],
    "mexicana": ["corrido", "ranchera", "norteno", "norteña", "mariachi", "banda sinaloense",
                 "del records", "regional mexicano", "grupero", "tumbado"],
    "tropical": ["tropical", "bailable", "cumbia", "porro", "crossover", "orquesta tropical",
                 "musica decembrina", "parranda"],
    "champeta": ["champeta"],
    "popular": ["musica popular", "despecho", "carrilera", "guasca", "popular colombiana"],
    "baladas": ["balada", "romanticas", "baladas"],
    "rock_pop": ["rock", "official music video", "pop"],
}

# Artistas (y canales) conocidos por género.
_ARTISTAS = {
    "popular": [
        "yeison jimenez", "luis alfonso", "paola jara", "jessi uribe", "pipe bueno",
        "uriel henao", "el andariego", "jhon alex castano", "jeison perez", "gency ramirez",
        "andres franco", "sebastian ayala", "argemiro jaramillo", "luisito munoz", "dario dario",
        "ciro quinonez", "yeison maje", "jhonny rivera", "dario gomez", "luis alberto posada",
        "giovanny ayala", "charrito negro", "alzate", "pasabordo", "arelys henao",
        "galy galiano", "osmar perez", "juan duque", "francy", "el jhony", "jhon onofre",
        "nelson velasquez", "el flaco flow", "jorge velosa", "lady yuliana", "fernando burbano",
        "brandon", "emyl rusev", "jhon jairo ramirez", "las hermanitas calle", "luis miguel del amargue",
        "olimpo cardenas", "julio jaramillo", "yohny rivera", "olider montana", "jhonatan luna",
        "luis antonio", "el gerente", "jefferson",
    ],
    "vallenato": [
        "binomio de oro", "diomedes diaz", "rafael orozco", "jean carlos centeno",
        "peter manjarres", "silvestre dangond", "jorge celedon", "los inquietos",
        "combinacion vallenata", "hermanos zuleta", "los zuleta", "poncho zuleta",
        "ivan villazon", "kaleth morales", "martin elias", "otto serge", "los chiches",
        "enaldo barrera", "felipe pelaez", "los diablitos", "gigantes del vallenato",
        "alejo duran", "jorge onate", "ivo diaz", "sergio luis rodriguez", "victor rey reyes",
        "los betos", "los gigantes", "miguel morales", "beto zabaleta", "alfredo gutierrez",
        "farid ortiz", "rafa perez", "patricia teheran", "hebert vargas", "elder dayan",
        "kvrass", "churo diaz", "los k morales", "nicky jam y silvestre", "fabian corrales",
        "codiscos",
    ],
    "salsa": [
        "grupo niche", "adolescent", "eddie santiago", "tony vega", "mariano civico",
        "frankie ruiz", "hector lavoe", "willie colon", "ruben blades", "marc anthony",
        "gilberto santa rosa", "joe arroyo", "fruko", "guayacan", "jerry rivera",
        "victor manuelle", "maelo ruiz", "gran combo", "oscar d leon", "oscar de leon",
        "lalo rodriguez", "grupo gale", "diego y su grupo gale", "galileo y su banda",
        "willie gonzalez", "tito rojas", "luis enrique", "la india", "celia cruz",
        "orquesta la 33", "son de cali", "hansel", "nino segarra", "paquito guzman",
        "tito nieves", "richie ray", "bobby cruz", "cheo feliciano", "ismael rivera",
        "pete el conde", "sonora poncena", "la sonora carruseles", "niche",
    ],
    "merengue": [
        "la patrulla 15", "wilfrido vargas", "los hermanos rosario", "elvis crespo",
        "eddy herrera", "sergio vargas", "fernando villalona", "kinito mendez", "oro solido",
        "omarengue", "toño rosario", "tono rosario", "johnny ventura", "milly quezada",
        "proyecto uno", "los vecinos", "jossie esteban", "rikarena", "olga tanon",
        "juan luis guerra",
    ],
    "bachata": [
        "romeo santos", "aventura", "prince royce", "anthony santos", "frank reyes",
        "raulin rodriguez", "zacarias ferreira", "hector acosta", "luis vargas",
        "joe veras", "yoskar sarante", "elvis martinez", "monchy y alexandra",
    ],
    "urbano": [
        "ryan castro", "blessd", "kris r", "don omar", "daddy yankee", "bad bunny", "karol g",
        "j balvin", "maluma", "feid", "wisin", "yandel", "ozuna", "anuel", "farruko",
        "nicky jam", "arcangel", "de la ghetto", "reykon", "myke towers", "rauw alejandro",
        "sech", "jhay cortez", "jhayco", "tego calderon", "ivy queen", "zion", "lennox",
        "plan b", "manuel turizo", "piso 21", "dalex", "lunay", "beele", "kapo", "dfzm",
        "westcol", "hades66", "el alfa", "chencho", "young miko", "quevedo", "casaparlante",
        "mora", "eladio carrion", "justin quiles",
    ],
    "mexicana": [
        "los tigres del norte", "vicente fernandez", "christian nodal", "natanael cano",
        "lenin ramirez", "calibre 50", "alfredo olivas", "los tucanes", "banda ms",
        "el recodo", "gerardo ortiz", "peso pluma", "fuerza regida", "grupo firme",
        "antonio aguilar", "pepe aguilar", "joan sebastian", "ramon ayala", "los temerarios",
        "marco antonio solis", "los bukis", "alejandro fernandez", "juan gabriel",
        "rocio durcal", "el komander", "los cadetes", "chalino", "valentin elizalde",
        "julion alvarez", "remmy valenzuela", "carin leon", "eslabon armado", "junior h",
        "intocable", "los rieleros", "los invasores", "jenni rivera", "lupillo rivera",
        "ana gabriel", "luis r conriquez", "oscar maydon", "esau ortiz", "victor mendivil",
        "aleman", "los dos carnales", "banda el limon", "la arrolladora", "edwin luna",
    ],
    "tropical": [
        "ivan y sus bam band", "ivan & sus bam band", "bam band", "diablos locos",
        "los melodicos", "los hispanos", "rodolfo aicardi", "pastor lopez", "los graduados",
        "sonora dinamita", "lisandro meza", "combo de las estrellas", "los 50 de joselito",
        "la sonora matancera", "billos", "los corraleros", "anibal velasquez",
        "los black star", "chico cheo", "maquina total", "los tupamaros", "la tropa vallenata",
        "carlos vives", "fruko y sus tesos", "afinaito", "rio band",
    ],
    "champeta": [
        "mr black", "kevin florez", "el afinaito", "dj demoledor", "el jhonky", "charles king",
        "louis towers", "el sayayin", "twister el rey", "kevin flores", "el pupy", "champeta africana",
    ],
    "baladas": [
        "jose jose", "camilo sesto", "roberto carlos", "ricardo arjona", "franco de vita",
        "ricardo montaner", "luis miguel", "chayanne", "cristian castro", "rocio jurado",
        "raphael", "nino bravo", "jose luis perales", "dyango", "ana belen", "emmanuel",
        "yuri", "pandora", "alejandro sanz", "laura pausini", "eros ramazzotti", "manuel mijares",
    ],
    "rock_pop": [
        "maroon 5", "4 non blondes", "queen", "guns n roses", "bon jovi", "soda stereo",
        "mana", "shakira", "enanitos verdes", "hombres g", "los prisioneros", "aterciopelados",
        "coldplay", "the beatles", "michael jackson", "madonna", "ed sheeran", "bruno mars",
        "dua lipa", "taylor swift", "imagine dragons", "linkin park", "metallica", "acdc",
        "ac dc", "nirvana", "red hot chili", "juanes", "morat", "camilo", "sebastian yatra",
        "reik", "jesse & joy", "ha ash", "cafe tacvba", "caifanes", "los fabulosos cadillacs",
        "waka waka", "rihanna", "the weeknd", "adele",
    ],
}


def _norm(texto):
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9&]+", " ", t)
    return f" {t.strip()} "


_NORM_ARTISTAS = {g: [_norm(a) for a in lista] for g, lista in _ARTISTAS.items()}
_NORM_PALABRAS = {g: [_norm(p).strip() for p in lista] for g, lista in _PALABRAS.items()}


@lru_cache(maxsize=20000)
def clasificar(titulo, canal=""):
    """Clave del género (ver GENEROS). "otros" si no se reconoce."""
    texto = _norm(f"{titulo} {canal}")
    puntos = {}
    for g, artistas in _NORM_ARTISTAS.items():
        for a in artistas:
            if a in texto:
                puntos[g] = puntos.get(g, 0) + 3 + len(a) / 100  # el nombre más largo gana
    for g, palabras in _NORM_PALABRAS.items():
        for p in palabras:
            if p and re.search(rf"(^| ){re.escape(p)}", texto):
                # "pop"/"rock"/"official music video" son pistas débiles
                puntos[g] = puntos.get(g, 0) + (1 if g == "rock_pop" else 4)
    if not puntos:
        return "otros"
    return max(puntos.items(), key=lambda x: x[1])[0]


def lista(texto):
    """'vallenato,salsa' -> {'vallenato', 'salsa'} (solo claves válidas)."""
    return {g.strip() for g in str(texto or "").split(",") if g.strip() in NOMBRES}
