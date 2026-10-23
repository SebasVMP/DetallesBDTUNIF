to de

# Analizador de publicaciones CSV

Aplicación Flask para analizar exportaciones CSV de publicaciones de Facebook e Instagram. La persona que usa la aplicación selecciona desde su equipo un CSV para cada red; cada red se muestra en su propia tabla. No es necesario importar datos a una base de datos ni modificar el archivo SQL anterior.

El analizador reconoce las columnas de las exportaciones de Meta de referencia en `CSV/`: Instagram usa `Descripción` y `Me gusta`, mientras que Facebook usa `Título`/`Descripción` y `Reacciones`. Cada tabla muestra hora de publicación, enlace permanente, alcance y la métrica de interacción correspondiente. Agrupa por el primer hashtag encontrado y permite filtrar cada red por separado, sin distinguir mayúsculas de minúsculas.

## Organización del proyecto

- `models/hashtag_model.py`: lee las filas y columnas del CSV y prepara las métricas.
- `controllers/hashtag_controller.py`: recibe el archivo, filtra resultados y prepara la descarga.
- `vista/index.html`: formularios para seleccionar los CSV y tablas separadas para Instagram y Facebook.
- `vista/style.css`: estilos de la página.
- `app.py`: crea la aplicación Flask y registra el controlador.

Puedes seleccionar un CSV de Instagram, uno de Facebook o ambos en una misma carga. Cada descarga genera un CSV compacto con las columnas `RedSocial`, `TipoHashtag`, `HoraDePublicacion`, `Enlace`, `Alcance` y `MeGustas`. Incluye una fila por publicación que coincide con el hashtag seleccionado; si el filtro está vacío, exporta todas las publicaciones de esa red. El contador que aparece en pantalla indica cuántas publicaciones corresponden a cada hashtag.

Los archivos seleccionados se guardan temporalmente en la carpeta temporal del sistema para permitir filtrar y exportar sin volver a seleccionarlos. Se eliminan al cumplir 24 horas cuando se procesa una nueva carga. El límite de carga es 32 MB. Los totales de alcance suman las métricas reportadas por publicación y no representan personas únicas.

## Ejecutar

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py -m flask --app app run --debug --port 8000
```

Abre http://127.0.0.1:8000 en el navegador, selecciona cada exportación `.csv` en el campo de su red y pulsa **Analizar selección**. Puedes consultar los hashtags de cada archivo, filtrar las tablas independientemente y descargar cada resultado por separado.
