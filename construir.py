#!/usr/bin/env python3
"""
construir.py  ·  empaquetar FocusMedia en un .exe de Windows

    pip install pyinstaller
    python construir.py

Deja `dist/FocusMedia.exe`, que funciona sin tener Python instalado.

NO SE HA PROBADO AQUÍ, y conviene decirlo
-----------------------------------------
Esto se escribió sin poder ejecutarlo: hace falta Windows y PyInstaller.
Lo que sí está cuidado es lo que suele fallar, que son cuatro cosas
concretas y están comentadas abajo. Si algo no sale, el error de
PyInstaller es bastante literal.

Las cuatro trampas conocidas
----------------------------
1. **customtkinter se carga por rutas, no por imports.** PyInstaller no lo
   ve mirando el código, así que su carpeta de datos se añade a mano. Sin
   esto, el .exe abre y revienta al crear el primer widget.

2. **Sin consola no se ve ningún error.** `--windowed` quita la ventana
   negra, que es lo que se quiere, y con ella cualquier rastro. Por eso el
   punto de entrada es `FocusMedia.pyw`, que ya recoge los fallos de
   arranque y los enseña en un cuadro.

3. **Los datos NO van dentro.** `salida/` y `sesiones/` se quedan al lado
   del .exe, porque un ejecutable se sustituye al actualizar y lo que
   lleve dentro se va con él.

4. **Windows enseñará un aviso de SmartScreen** la primera vez, porque el
   .exe no está firmado. Firmar cuesta dinero de verdad (un certificado
   al año) y no hay forma de evitarlo desde aquí. Se avisa al terminar en
   vez de dejar que sorprenda.
"""

import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
NOMBRE = "FocusMedia"


def main() -> None:
    try:
        import PyInstaller                      # noqa: F401
    except ImportError:
        sys.exit("Falta PyInstaller:\n    pip install pyinstaller")

    try:
        import customtkinter
    except ImportError:
        sys.exit("Falta customtkinter:\n    pip install customtkinter")

    # customtkinter carga sus temas y fuentes por ruta, no por import.
    datos = Path(customtkinter.__file__).parent
    separador = ";" if sys.platform == "win32" else ":"

    orden = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", NOMBRE,
        "--onefile",
        "--windowed",                      # sin consola: ver la trampa 2
        f"--add-data={datos}{separador}customtkinter",
        # Los módulos que solo se importan desde ordenes.py por nombre.
        "--hidden-import=browser_cookie3",
        "--collect-submodules=browser_cookie3",
    ]
    icono = AQUI / "marca" / "focusmedia.ico"
    if icono.exists():
        orden += [f"--icon={icono}"]
    orden.append(str(AQUI / "FocusMedia.pyw"))

    print("Construyendo...\n  " + " ".join(orden) + "\n")
    if subprocess.run(orden, cwd=AQUI).returncode != 0:
        sys.exit("\nPyInstaller ha fallado. El error de arriba suele ser "
                 "bastante literal.")

    destino = AQUI / "dist" / f"{NOMBRE}.exe"
    print(f"\nListo: {destino}")
    print("\n  Ponlo en su propia carpeta: al lado se crearán salida/ y")
    print("  sesiones/, que NO van dentro del .exe — un ejecutable se")
    print("  sustituye al actualizar y se llevaría los datos con él.")
    print("\n  La primera vez Windows enseñará un aviso de SmartScreen,")
    print("  porque no está firmado. «Más información» -> «Ejecutar de")
    print("  todas formas». Firmarlo necesita un certificado de pago.")
    if not (AQUI / "README.md").exists():
        return
    shutil.copy(AQUI / "README.md", AQUI / "dist" / "README.md")
    print("\n  Se ha copiado el README al lado del .exe.")


if __name__ == "__main__":
    main()
