import asyncio
import flet as ft


async def splash_view(page: ft.Page):
    """
    Splash visual de PlayBar GO.

    Se ejecuta después de la capa de carga/boot de Flet y antes de cargar
    la vista de sesión/código. El efecto reproduce un zoom + fade
    usando el logo real de PlayBar GO.
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
        opacity=0.0,
        scale=0.72,
        animate_opacity=ft.Animation(
            duration=450,
            curve=ft.AnimationCurve.EASE_OUT_CUBIC,
        ),
        animate_scale=ft.Animation(
            duration=650,
            curve=ft.AnimationCurve.EASE_OUT_CUBIC,
        ),
    )

    page.add(
        ft.Container(
            expand=True,
            alignment=ft.Alignment.CENTER,
            content=logo,
        )
    )
    page.update()

    # Entrada: aparece y crece suavemente.
    await asyncio.sleep(0.05)
    logo.opacity = 1.0
    logo.scale = 1.0
    logo.update()

    # Mantener el logo visible un instante.
    await asyncio.sleep(0.80)

    # Salida suave.
    logo.opacity = 0.0
    logo.scale = 0.92
    logo.update()

    await asyncio.sleep(0.35)
