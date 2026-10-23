import tempfile
from pathlib import Path

from flask import Flask, send_from_directory

from controllers.hashtag_controller import hashtag_blueprint

MAX_UPLOAD_SIZE = 32 * 1024 * 1024


def create_app() -> Flask:
    """Configura Flask, registra las rutas y devuelve la aplicación."""
    app = Flask(__name__, template_folder="vista", static_folder=None)
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_UPLOAD_SIZE,
        UPLOAD_FOLDER=str(Path(tempfile.gettempdir()) / "btanalisis_csv_uploads"),
    )
    app.register_blueprint(hashtag_blueprint)

    @app.get("/vista/style.css", endpoint="stylesheet")
    def stylesheet():
        """Entrega al navegador la hoja de estilos del dashboard."""
        return send_from_directory(
            app.root_path,
            "vista/style.css",
            mimetype="text/css",
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(port=8000)
