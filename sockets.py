"""
Socket.IO setup and signaling events for WebRTC stash sharing.
"""

from flask import request
from flask_socketio import SocketIO, join_room, leave_room, emit

socketio = SocketIO(cors_allowed_origins="*")


def init_socketio(app):
    """Initialize Socket.IO and register signaling handlers."""
    socketio.init_app(app, cors_allowed_origins="*")

    @socketio.on("join_room")
    def handle_join(data):
        room = data.get("room")
        if not room:
            return
        join_room(room)
        emit("peer_joined", {"sid": request.sid}, to=room, include_self=False)

    @socketio.on("leave_room")
    def handle_leave(data):
        room = data.get("room")
        if not room:
            return
        leave_room(room)
        emit("peer_left", {"sid": request.sid}, to=room, include_self=False)

    @socketio.on("signal")
    def handle_signal(data):
        room = data.get("room")
        payload = data.get("payload")
        if not room or payload is None:
            return
        emit("signal", payload, to=room, include_self=False)
