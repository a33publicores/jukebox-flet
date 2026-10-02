import os
import re
import subprocess
import sys

# ============================================================
# PLAYBAR GO - FLET - GIT AUTO PUSH
# ============================================================
# Uso:
#   1. Guarda este archivo en la RAÍZ del proyecto.
#   2. Haz doble clic.
#
# El script:
#   - Detecta el repositorio Git.
#   - Repara automáticamente "dubious ownership".
#   - Verifica rama y remote.

#   - Detecta los cambios.
#   - Identifica qué área del sistema fue modificada.
#   - Genera el mensaje de commit.
#   - git add -A
#   - git commit
#   - git push
#
# SEGURIDAD:
#   - NO hace git init.
#   - NO cambia el remote.
#   - NO hace push --force.
#   - NO modifica Railway directamente.
#
# ============================================================

AUTO_PUSH = True
REMOTE = "origin"
PROJECT_NAME = "PlayBar GO — Flet"

EXPECTED_REMOTE = "https://github.com/a33publicores/jukebox-flet.git"
EXPECTED_BRANCH = "main"


# ============================================================
# GIT
# ============================================================

def run_git(*args, check=True):
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )

    if check and result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip())
        sys.exit(result.returncode)

    return result


# ============================================================
# UTILIDADES
# ============================================================

def pause():
    input("\nPresiona ENTER para cerrar...")


def fail(message):
    print("\n" + "=" * 70)
    print(" ERROR")
    print("=" * 70)
    print(message)
    pause()
    sys.exit(1)


# ============================================================
# DETECTAR RAÍZ DEL REPOSITORIO
# ============================================================

def find_repository_root():
    """
    Busca la raíz real del repositorio Git partiendo desde
    la carpeta donde está este archivo.
    """

    current_folder = os.path.abspath(
        os.path.dirname(__file__)
    )

    result = run_git(
        "-C",
        current_folder,
        "rev-parse",
        "--show-toplevel",
        check=False,
    )

    if result.returncode == 0:
        return os.path.normpath(
            result.stdout.strip()
        )

    return current_folder


# ============================================================
# REPARAR DUBIOUS OWNERSHIP
# ============================================================

def ensure_safe_directory(repo):
    """
    Detecta el error:

        fatal: detected dubious ownership in repository

    y registra automáticamente el repositorio como
    safe.directory para el usuario actual de Windows.

    No modifica permisos ni propietarios de Windows.
    """

    print("\n[1/7] Verificando seguridad del repositorio...")

    # Primera prueba.
    result = run_git(
        "-C",
        repo,
        "status",
        check=False,
    )

    if result.returncode == 0:
        print("OK - Git reconoce el repositorio.")
        return True

    output = (
        result.stdout +
        "\n" +
        result.stderr
    ).strip()

    # Si el error no es dubious ownership,
    # no intentamos ocultarlo.
    if "dubious ownership" not in output.lower():

        print("\nGit devolvió este error:")
        print("-" * 70)
        print(output)
        print("-" * 70)

        return False

    print("")
    print("Git detectó que el repositorio pertenece")
    print("a otro usuario/SID de Windows.")
    print("")
    print("Configurando automáticamente:")
    print("")
    print(f"safe.directory = {repo}")
    print("")

    config = run_git(
        "config",
        "--global",
        "--add",
        "safe.directory",
        repo,
        check=False,
    )

    if config.returncode != 0:

        print("No fue posible configurar safe.directory.")

        if config.stderr:
            print(config.stderr)

        return False

    print("OK - safe.directory configurado.")

    # Volvemos a comprobar.
    verify = run_git(
        "-C",
        repo,
        "status",
        check=False,
    )

    if verify.returncode != 0:

        print("\nGit todavía no reconoce el repositorio.")

        if verify.stderr:
            print(verify.stderr)

        return False

    print("OK - Git ya reconoce correctamente el repositorio.")

    return True


# ============================================================
# CLASIFICAR ARCHIVOS
# ============================================================

def classify_file(path):

    p = path.lower().replace("\\", "/")

    if p == "main.py":
        return "aplicación principal"

    if p.startswith("views/"):
        return "vistas Flet"

    if p.startswith("components/"):
        return "componentes Flet"

    if p.startswith("services/"):
        return "servicios"

    if p.startswith("display/"):
        return "display"

    if p.startswith("backend/"):
        if "/services/" in p:
            return "servicios backend"
        return "backend / API"

    if p.startswith("assets/"):
        return "recursos gráficos"

    if p.startswith("data/"):
        return "datos locales"

    if p.endswith(".py"):
        return "Python"

    if p.endswith((".json", ".env", ".yaml", ".yml")):
        return "configuración"

    if "requirements" in p or p.endswith((".toml", ".lock")):
        return "dependencias"

    if p.endswith((".css", ".scss")):
        return "estilos"

    if p.endswith((".html", ".htm")):
        return "interfaz"

    if p.endswith((".bat", ".ps1")):
        return "automatización"

    return "archivos del proyecto"


# ============================================================
# CAMBIOS
# ============================================================

def get_changed_files():

    result = run_git(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        check=False,
    )

    if result.returncode != 0:

        print(result.stderr)

        return []

    files = []

    for line in result.stdout.splitlines():

        if not line.strip():
            continue

        # Formato:
        #
        # XY archivo
        #
        status = line[:2]
        path = line[3:]

        # Detectar renombrados.
        if " -> " in path:

            old, new = path.split(
                " -> ",
                1
            )

            files.append(
                (
                    status,
                    new.strip()
                )
            )

        else:

            files.append(
                (
                    status,
                    path.strip()
                )
            )

    return files


# ============================================================
# RAMA
# ============================================================

def get_branch():

    result = run_git(
        "branch",
        "--show-current",
        check=False,
    )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


# ============================================================
# REMOTE
# ============================================================

def get_remote():

    result = run_git(
        "remote",
        "-v",
        check=False,
    )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


# ============================================================
# ESTADÍSTICAS
# ============================================================

def get_diff_stats():

    result = run_git(
        "diff",
        "--stat",
        "HEAD",
        check=False,
    )

    return result.stdout.strip()


# ============================================================
# DIFF
# ============================================================

def get_diff_text():

    result = run_git(
        "diff",
        "HEAD",
        "--",
        check=False,
    )

    return result.stdout


# ============================================================
# ACCIÓN
# ============================================================

def detect_action(files):

    statuses = "".join(
        status
        for status, _ in files
    )

    if statuses and all(
        "A" in s or "?" in s
        for s in statuses
    ):
        return "Agrega"

    if (
        "D" in statuses
        and "M" not in statuses
    ):
        return "Elimina"

    if (
        "M" in statuses
        or "R" in statuses
    ):
        return "Actualiza"

    return "Modifica"


# ============================================================
# ÁREA
# ============================================================

def detect_area(files):

    areas = []

    for _, path in files:

        area = classify_file(path)

        if area not in areas:
            areas.append(area)

    if not areas:
        return "proyecto"

    if len(areas) == 1:
        return areas[0]

    if len(areas) == 2:
        return (
            f"{areas[0]} y "
            f"{areas[1]}"
        )

    return (
        ", ".join(areas[:3])
        + " y otros"
    )


# ============================================================
# DETALLE
# ============================================================

def detect_detail(
    diff_text,
    files
):

    text = diff_text.lower()

    for _, path in files:
        text += "\n" + path.lower()

    rules = [

        (r"login|autentic|session|sesion|client_storage",
         "sesión / autenticación"),

        (r"jukebox|cancion|canciones|youtube|playlist|videoid",
         "jukebox / YouTube"),

        (r"karaoke",
         "karaoke"),

        (r"codigo|cliente|telefono",
         "acceso de cliente"),

        (r"session_manager|session\.json",
         "persistencia de sesión"),

        (r"display|pantalla",
         "display"),

        (r"flet|page\.|ft\.",
         "interfaz Flet"),

        (r"backend|flask|gunicorn|railway|api",
         "backend / API"),

        (r"google|youtube api|oauth|token|credentials",
         "integraciones Google"),

        (r"logo|imagen|asset",
         "recursos gráficos"),

        (r"requirements|dependenc",
         "dependencias"),

        (r"websocket|socket|broadcast",
         "sincronización"),

        (r"historial|reproduccion|reproducción",
         "historial de reproducciones"),

    ]

    detected = []

    for pattern, label in rules:

        if re.search(pattern, text):

            if label not in detected:
                detected.append(label)

    if detected:
        return ", ".join(detected[:3])

    if files:

        main_file = os.path.basename(
            files[0][1]
        )

        return main_file

    return "cambios del proyecto"


# ============================================================
# MENSAJE DE COMMIT
# ============================================================

def make_commit_message(
    files,
    diff_text
):

    action = detect_action(files)

    area = detect_area(files)

    detail = detect_detail(
        diff_text,
        files
    )

    return (
        f"{action}: "
        f"{area} - "
        f"{detail}"
    )


# ============================================================
# MOSTRAR CAMBIOS
# ============================================================

def print_changes(
    files,
    diff_text
):

    print("\n" + "=" * 70)
    print(" PLAYBAR GO - CAMBIOS DETECTADOS")
    print("=" * 70)

    for status, path in files:

        if "??" in status:

            estado = "NUEVO"

        elif "A" in status:

            estado = "AGREGADO"

        elif "M" in status:

            estado = "MODIFICADO"

        elif "D" in status:

            estado = "ELIMINADO"

        elif "R" in status:

            estado = "RENOMBRADO"

        else:

            estado = status.strip()

        print(
            f"  [{estado:<10}] {path}"
        )

    print("\nÁrea detectada:")

    print(
        f"  {detect_area(files)}"
    )

    print("\nDetalle detectado:")

    print(
        f"  {detect_detail(diff_text, files)}"
    )

    stats = get_diff_stats()

    if stats:

        print("\nResumen Git:")

        print(stats)


# ============================================================
# COMMITS PENDIENTES DE PUSH
# ============================================================

def get_unpushed_commit_count(branch):
    """
    Comprueba si existen commits locales que todavía no están
    en el remote. Esto cubre el caso en que el working tree está
    limpio pero hay un commit pendiente de push.
    """

    # Intentamos comparar contra el remote explícito.
    result = run_git(
        "rev-list",
        "--count",
        f"{REMOTE}/{branch}..HEAD",
        check=False,
    )

    if result.returncode == 0:
        try:
            return int(result.stdout.strip() or "0")
        except ValueError:
            return 0

    # Si todavía no existe la referencia remota de la rama,
    # no asumimos que haya commits pendientes.
    return 0


def push_pending_commits(branch):
    """
    Hace push de commits locales pendientes sin crear un commit
    vacío y sin hacer pull/merge automáticamente.
    """

    print(
        f"\nVerificando commits pendientes "
        f"antes de git push {REMOTE} {branch}"
    )

    pending = get_unpushed_commit_count(branch)

    if pending <= 0:
        print("OK - No hay commits locales pendientes de push.")
        return True

    print(
        f"Se encontraron {pending} commit(s) local(es) "
        "pendiente(s) de subir."
    )

    push = run_git(
        "push",
        REMOTE,
        branch,
        check=False,
    )

    if push.returncode != 0:
        print("\nERROR EN GIT PUSH")
        print(push.stdout)
        print(push.stderr)
        print("\nLos commits locales siguen guardados.")
        return False

    print(push.stdout.strip() or "OK - Push realizado correctamente.")
    return True


# ============================================================
# SEGURIDAD DEL PROYECTO
# ============================================================

PROTECTED_FILES = {
    "backend/credenciales.json",
    "backend/client_secrets.json",
    "backend/token1.json",
    "backend/token2.json",
    "backend/.env",
    ".env",
    "data/session.json",
    "backend/google_credentials.json",
    "backend/service_account.json",
}


def get_staged_files():

    result = run_git(
        "diff",
        "--cached",
        "--name-only",
        check=False,
    )

    if result.returncode != 0:
        return []

    return [
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def validate_staged_files():

    staged = get_staged_files()

    dangerous = []

    for path in staged:

        normalized = path.lower()

        for protected in PROTECTED_FILES:

            if normalized == protected.lower():

                dangerous.append(path)

    if dangerous:

        print("\n" + "=" * 70)
        print(" BLOQUEO DE SEGURIDAD")
        print("=" * 70)

        print(
            "\nSe detectaron archivos que NO deben subirse a GitHub:"
        )

        for path in dangerous:
            print(f"  [BLOQUEADO] {path}")

        print(
            "\nEl commit/push fue cancelado para proteger "
            "credenciales, tokens o sesiones locales."
        )

        # Sacamos solamente esos archivos del staging.
        for path in dangerous:
            run_git("restore", "--staged", "--", path, check=False)

        return False

    return True


# ============================================================
# SINCRONIZACIÓN CON GITHUB
# ============================================================

def fetch_remote(branch):

    print("\n[4/7] Actualizando referencia de GitHub...")

    result = run_git(
        "fetch",
        REMOTE,
        check=False,
    )

    if result.returncode != 0:

        print("\nERROR - No se pudo consultar GitHub.")

        print(result.stderr or result.stdout)

        return False

    print("OK - Referencia remota actualizada.")

    return True


def get_remote_ahead_behind(branch):

    result = run_git(
        "rev-list",
        "--left-right",
        "--count",
        f"{branch}...{REMOTE}/{branch}",
        check=False,
    )

    if result.returncode != 0:
        return 0, 0

    try:

        parts = result.stdout.strip().split()

        if len(parts) != 2:
            return 0, 0

        local_ahead = int(parts[0])
        remote_ahead = int(parts[1])

        return local_ahead, remote_ahead

    except (ValueError, TypeError):

        return 0, 0


def has_working_changes():
    """Devuelve True si hay cambios staged, unstaged o archivos nuevos."""
    result = run_git(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        check=False,
    )
    return bool(result.stdout.strip()) if result.returncode == 0 else False


def stash_working_changes():
    """
    Guarda temporalmente cambios locales antes de hacer pull --rebase.
    No elimina los cambios del usuario.
    """
    print("\nHay cambios locales sin commit.")
    print("Se guardarán temporalmente para sincronizar con GitHub.")

    result = run_git(
        "stash",
        "push",
        "-u",
        "-m",
        "PLAYBAR_GO_AUTO_PUSH_TEMP",
        check=False,
    )

    if result.returncode != 0:
        print("\nERROR - No se pudieron guardar temporalmente los cambios.")
        print(result.stdout)
        print(result.stderr)
        return False

    print("OK - Cambios locales guardados temporalmente.")
    return True


def restore_working_changes():
    """Restaura el último stash creado por este script."""
    print("\nRestaurando los cambios locales...")

    result = run_git(
        "stash",
        "pop",
        check=False,
    )

    if result.returncode != 0:
        print("\nATENCIÓN - Git encontró un conflicto al restaurar los cambios.")
        print(result.stdout)
        print(result.stderr)
        print(
            "\nLos cambios NO se han eliminado. "
            "Revisa el estado de Git antes de continuar."
        )
        return False

    print("OK - Cambios locales restaurados.")
    return True


def abort_rebase():
    """Cancela un rebase incompleto sin forzar nada."""
    run_git(
        "rebase",
        "--abort",
        check=False,
    )


def synchronize_with_github(branch):
    """
    Sincroniza la rama local con GitHub de forma segura.

    Casos:
    1. GitHub no tiene commits nuevos -> continúa normalmente.
    2. GitHub tiene commits nuevos y no hay cambios locales ->
       pull --rebase automático.
    3. GitHub tiene commits nuevos y hay cambios locales ->
       stash -> pull --rebase -> stash pop.
    4. Si hay conflicto durante el rebase -> aborta el rebase y NO hace push.
    """
    if not fetch_remote(branch):
        return False

    local_ahead, remote_ahead = get_remote_ahead_behind(branch)

    if remote_ahead <= 0:
        return True

    print("\n" + "=" * 70)
    print(" GITHUB TIENE CAMBIOS NUEVOS")
    print("=" * 70)

    print(
        f"\nGitHub tiene {remote_ahead} commit(s) "
        "que este PC todavía no tiene."
    )

    if local_ahead > 0:
        print(
            f"Este PC también tiene {local_ahead} commit(s) "
            "local(es) pendientes."
        )
        print("\nSe hará una integración mediante REBASE.")
    else:
        print("\nEste PC está detrás de GitHub.")
        print("Se actualizará automáticamente mediante REBASE.")

    stashed = False

    # Si el usuario tiene trabajo sin commit, lo protegemos primero.
    if has_working_changes():
        if not stash_working_changes():
            return False
        stashed = True

    print(
        f"\nEjecutando: git pull --rebase {REMOTE} {branch}"
    )

    pull = run_git(
        "pull",
        "--rebase",
        REMOTE,
        branch,
        check=False,
    )

    if pull.returncode != 0:
        print("\n" + "=" * 70)
        print(" REBASE NO COMPLETADO")
        print("=" * 70)

        print(pull.stdout)
        print(pull.stderr)

        # Intentamos dejar el repositorio fuera del estado de rebase.
        abort_rebase()

        if stashed:
            print(
                "\nLos cambios locales permanecieron protegidos "
                "en el stash."
            )
            print(
                "No se realizará ningún push hasta resolver el conflicto."
            )
        else:
            print(
                "\nNo se realizará ningún push hasta resolver el conflicto."
            )

        return False

    print("\nOK - GitHub integrado mediante rebase.")

    if stashed:
        if not restore_working_changes():
            print(
                "\nNo se realizará el commit/push porque la restauración "
                "de cambios necesita atención."
            )
            return False

    # Verificación final.
    local_ahead_after, remote_ahead_after = get_remote_ahead_behind(branch)

    if remote_ahead_after > 0:
        print(
            "\nERROR - Después del rebase todavía existen commits remotos "
            "que no están en local."
        )
        print("No se realizará ningún push.")
        return False

    print(
        f"OK - Sincronización completa. "
        f"Local adelante: {local_ahead_after} commit(s)."
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(" PLAYBAR GO - GIT AUTO PUSH")
    print("=" * 70)

    # --------------------------------------------------------
    # DETECTAR REPOSITORIO
    # --------------------------------------------------------

    repo = find_repository_root()

    print("\nProyecto detectado:")

    print(repo)

    # --------------------------------------------------------
    # VERIFICAR .git
    # --------------------------------------------------------

    if not os.path.isdir(
        os.path.join(
            repo,
            ".git"
        )
    ):

        fail(
            "\n"
            "No encuentro la carpeta .git.\n\n"
            "Esta carpeta no parece ser el repositorio "
            "Git de PLAYBAR GO.\n\n"
            "No ejecutaré git init automáticamente."
        )

    os.chdir(repo)

    # --------------------------------------------------------
    # REPARAR SAFE DIRECTORY
    # --------------------------------------------------------

    if not ensure_safe_directory(
        repo
    ):

        fail(
            "Git no pudo reconocer correctamente "
            "el repositorio.\n\n"
            "No se realizará ningún push."
        )

    # --------------------------------------------------------
    # RAMA
    # --------------------------------------------------------

    print("\n[2/7] Verificando rama...")

    branch = get_branch()

    if not branch:

        fail(
            "No pude identificar la rama actual."
        )

    print(
        f"OK - Rama actual: {branch}"
    )

    # --------------------------------------------------------
    # REMOTE
    # --------------------------------------------------------

    print("\n[3/7] Verificando remote...")

    remote_info = get_remote()

    if not remote_info:

        fail(
            "Este repositorio no tiene "
            "un remote configurado.\n\n"
            "No crearé uno automáticamente "
            "para evitar conectar PLAYBAR GO "
            "al repositorio equivocado."
        )

    print(remote_info)

    # --------------------------------------------------------
    # SEGURIDAD: REPOSITORIO Y RAMA ESPERADOS
    # --------------------------------------------------------

    if EXPECTED_REMOTE.lower() not in remote_info.lower():
        fail(
            "\nEste proyecto no está conectado al GitHub esperado.\n\n"
            f"Esperado: {EXPECTED_REMOTE}\n\n"
            "No cambiaré el remote automáticamente y NO haré push."
        )

    if branch != EXPECTED_BRANCH:
        fail(
            "\nLa rama actual no es la rama principal esperada.\n\n"
            f"Esperada: {EXPECTED_BRANCH}\n"
            f"Actual:   {branch}\n\n"
            "No cambiaré la rama automáticamente y NO haré push."
        )

    print("OK - GitHub y rama corresponden al proyecto Flet.")

    # --------------------------------------------------------
    # GITHUB / SINCRONIZACIÓN
    # --------------------------------------------------------

    if not synchronize_with_github(branch):

        pause()
        return

    # --------------------------------------------------------
    # CAMBIOS
    # --------------------------------------------------------

    print("\n[5/7] Detectando cambios...")

    files = get_changed_files()

    if not files:

        print("\nNo hay cambios de archivos pendientes.")

        print(
            f"Rama actual: {branch}"
        )

        # IMPORTANTE:
        # Un working tree limpio NO significa necesariamente que
        # GitHub esté actualizado. Puede existir un commit local
        # pendiente de push.
        pending = get_unpushed_commit_count(branch)

        if pending > 0:

            print(
                f"\nHay {pending} commit(s) local(es) "
                "pendiente(s) de subir a GitHub."
            )

            if not push_pending_commits(branch):

                pause()

                return

            print(
                "\n" + "=" * 70
            )

            print(
                " CAMBIOS PENDIENTES SUBIDOS CORRECTAMENTE"
            )

            print(
                "=" * 70
            )

            print(
                f"Rama: {branch}"
            )

            print(
                "\nFlujo:"
            )

            print(
                "PC → GitHub → Railway Flet"
            )

            pause()

            return

        print(
            "\nGit y GitHub están sincronizados "
            "según la referencia remota local."
        )

        pause()

        return

    diff_text = get_diff_text()

    print_changes(
        files,
        diff_text
    )

    # --------------------------------------------------------
    # COMMIT
    # --------------------------------------------------------

    commit_message = make_commit_message(
        files,
        diff_text
    )

    print(
        "\n" + "-" * 70
    )

    print(
        "COMMIT AUTOMÁTICO:"
    )

    print(
        f'  "{commit_message}"'
    )

    print(
        f"\nRama: {branch}"
    )

    print(
        f"Remote: {REMOTE}"
    )

    # --------------------------------------------------------
    # CONFIRMACIÓN
    # --------------------------------------------------------

    if not AUTO_PUSH:

        answer = input(
            "\n¿Deseas hacer "
            "add + commit + push? [S/N]: "
        ).strip().lower()

        if answer not in (
            "s",
            "si",
            "sí",
            "y",
            "yes",
        ):

            print(
                "\nOperación cancelada."
            )

            pause()

            return

    # --------------------------------------------------------
    # ADD
    # --------------------------------------------------------

    print(
        "\n[5/7] git add -A"
    )

    add = run_git(
        "add",
        "-A",
        check=False,
    )

    if add.returncode != 0:

        print(
            add.stderr
            or add.stdout
        )

        fail(
            "git add falló.\n"
            "No se realizará el commit ni el push."
        )

    print(
        "OK - archivos preparados."
    )

    if not validate_staged_files():

        pause()
        return

    # --------------------------------------------------------
    # COMMIT
    # --------------------------------------------------------

    print(
        "\n[6/7] git commit"
    )

    commit = run_git(
        "commit",
        "-m",
        commit_message,
        check=False,
    )

    if commit.returncode != 0:

        print(
            "\nNo se pudo crear el commit."
        )

        print(
            commit.stdout
        )

        print(
            commit.stderr
        )

        print(
            "\nNo se realizará push."
        )

        pause()

        return

    print(
        commit.stdout.strip()
    )

    # --------------------------------------------------------
    # PUSH
    # --------------------------------------------------------

    print(
        f"\n[8/8] git push "
        f"{REMOTE} {branch}"
    )

    push = run_git(
        "push",
        REMOTE,
        branch,
        check=False,
    )

    if push.returncode != 0:

        print(
            "\nERROR EN GIT PUSH"
        )

        print(
            push.stdout
        )

        print(
            push.stderr
        )

        print(
            "\nEl commit local YA quedó guardado."
        )

        print(
            "Puedes corregir el problema "
            "y volver a ejecutar este archivo."
        )

        pause()

        return

    print(
        push.stdout.strip() or
        "OK - Push realizado correctamente."
    )

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    print(
        "\n" + "=" * 70
    )

    print(
        " CAMBIOS SUBIDOS CORRECTAMENTE"
    )

    print(
        "=" * 70
    )

    print(
        f"Commit: {commit_message}"
    )

    print(
        f"Rama:   {branch}"
    )

    print(
        "\nFlujo:"
    )

    print(
        "PC → GitHub → Railway Flet"
    )

    print(
        "\nRailway podrá iniciar el despliegue "
        "si está conectado a esta rama."
    )

    pause()


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\n\nOperación cancelada "
            "por el usuario."
        )

        pause()

    except Exception as error:

        print(
            "\nERROR NO CONTROLADO:"
        )

        print(
            error
        )


        pause()
        
