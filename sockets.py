"""
Socket.IO setup and signaling events for WebRTC stash sharing.
"""

from flask import request, session
from flask_socketio import SocketIO, join_room, leave_room, emit

from auth_utils import load_session_user

socketio = SocketIO()

MAX_ROOM_LENGTH = 16


def _room_from(data):
    """Return a valid room code from an event payload, or None."""
    if not isinstance(data, dict):
        return None
    room = data.get("room")
    if not isinstance(room, str) or not room or len(room) > MAX_ROOM_LENGTH:
        return None
    return room


def init_socketio(app):
    """Initialize Socket.IO and register signaling handlers."""
    # None = same-origin only; add trusted origins via SOCKETIO_CORS_ORIGINS
    socketio.init_app(app, cors_allowed_origins=app.config.get("SOCKETIO_CORS_ORIGINS") or None)

    @socketio.on("connect")
    def handle_connect(auth=None):
        # Nearby Share is only offered to logged-in users; refuse anyone else
        if load_session_user(session) is None:
            return False

    @socketio.on("join_room")
    def handle_join(data):
        room = _room_from(data)
        if not room:
            return
        join_room(room)
        emit("peer_joined", {"sid": request.sid}, to=room, include_self=False)

    @socketio.on("leave_room")
    def handle_leave(data):
        room = _room_from(data)
        if not room:
            return
        leave_room(room)
        emit("peer_left", {"sid": request.sid}, to=room, include_self=False)

    @socketio.on("signal")
    def handle_signal(data):
        room = _room_from(data)
        payload = data.get("payload") if room else None
        if not room or payload is None:
            return
        emit("signal", payload, to=room, include_self=False)
