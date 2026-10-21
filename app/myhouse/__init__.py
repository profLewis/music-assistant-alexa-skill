"""MyHouse - the house on the Echo Show ("Alexa, open my house"): its own Alexa skill, served by this add-on at
POST /myhouse (Amazon-signed requests only), created at Amazon by POST /myhouse/deploy (app credentials)."""

from flask import Blueprint, current_app, jsonify
from flask_ask_sdk.skill_adapter import SkillAdapter

from . import deploy
from .handlers import build


def register(app):
    bp = Blueprint("myhouse", __name__)
    adapter = SkillAdapter(skill=build(), skill_id="myhouse", app=app)   # (signature + timestamp checked; the skill id by OurSkillOnly)

    @bp.route("/myhouse", methods=["POST"])
    def invoke():
        return adapter.dispatch_request()

    @bp.route("/myhouse/deploy", methods=["POST"])
    def start_deploy():
        deploy.deploy(current_app._get_current_object())
        return jsonify(deploy.status()), 202

    @bp.route("/myhouse/status", methods=["GET"])
    def status():
        return jsonify(deploy.status())

    app.register_blueprint(bp)
