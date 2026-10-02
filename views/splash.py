import asyncio
import flet as ft


async def splash_view(page: ft.Page):
    """
    Splash visual de PlayBar GO.

    El logo ya se muestra desde el primer instante mediante la capa HTML
    generada por web_boot.py (mismo logo, mismo tamaño, mismo fondo). Aquí
    se muestra igual, ya en su estado final, para que el relevo sea
    imperceptible; luego se desvanece y arranca la aplicación.

    La imagen pbgo_ready.png es la señal para que la capa HTML se retire.
    """
    page.clean()
    page.bgcolor = "#020617"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    logo = ft.Image(
        src="/logo.png",
        width=300,
        height=220,
        fit=ft.BoxFit.CONTAIN,
        opacity=1.0,
        scale=1.0,
        animate_opacity=ft.Animation(
            duration=450,
            curve=ft.AnimationCurve.EASE_OUT_CUBIC,
        ),
        animate_scale=ft.Animation(
            duration=650,
            curve=ft.AnimationCurve.EASE_OUT_CUBIC,
        ),
    )

    # Imagen transparente de 1x1: el navegador la pide y la capa HTML
    # sabe que este splash ya está pintado.
    ready = ft.Image(src="/pbgo_ready.png", width=1, height=1, opacity=0.01)

    page.add(
        ft.Container(
            expand=True,
            alignment=ft.Alignment.CENTER,
            content=logo,
        ),
        ready,
    )
    page.update()

    # Mantener el logo visible un instante.
    await asyncio.sleep(0.90)

    # Salida suave.
    logo.opacity = 0.0
    logo.scale = 0.92
    logo.update()

    await asyncio.sleep(0.35)
