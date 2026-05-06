from flask import Flask, render_template
from config import PORT
from db import init_db
from routes.market_check import bp as market_check_bp
from routes.research import bp as research_bp
from routes.valuation import bp as valuation_bp
from routes.trades import bp as trades_bp
from routes.smart_money import bp as smart_money_bp
from routes.settings import bp as settings_bp


def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.register_blueprint(market_check_bp, url_prefix="/api/market-check")
    app.register_blueprint(research_bp, url_prefix="/api/research")
    app.register_blueprint(valuation_bp, url_prefix="/api/valuation")
    app.register_blueprint(trades_bp, url_prefix="/api/trades")
    app.register_blueprint(smart_money_bp, url_prefix="/api/smart-money")
    app.register_blueprint(settings_bp, url_prefix="/api/settings")

    @app.route("/")
    @app.route("/<path:path>")
    def index(path=""):
        return render_template("index.html")

    return app


if __name__ == "__main__":
    init_db()
    app = create_app()
    app.run(host="0.0.0.0", port=PORT, debug=True)
