"""
Socket.IO setup and signaling events for WebRTC stash sharing.
"""

import threading
import time
from collections import defaultdict, deque

from flask import request, session
from flask_socketio import SocketIO, join_room, leave_room, emit, rooms

from auth_utils import load_session_user

socketio = SocketIO()

MAX_ROOM_LENGTH = 16
# A share is one sender and one receiver; a third peer is refused
MAX_ROOM_SIZE = 2
# Join attempts per connection per minute (stops guessing share codes)
MAX_JOINS_PER_MINUTE = 10

_join_times = defaultdict(deque)
_join_lock = threading.Lock()


def _room_from(data):
    """Return a valid room code from an event payload, or None."""
    if not isinstance(data, dict):
        return None
    room = data.get("room")
    if not isinstance(room, str) or not room or len(room) > MAX_ROOM_LENGTH:
        return None
    return room


def _join_allowed(sid) -> bool:
    """Sliding-window limit on join attempts for one connection."""
    now = time.monotonic()
    with _join_lock:
        attempts = _join_times[sid]
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= MAX_JOINS_PER_MINUTE:
            return False
        attempts.append(now)
        return True


def _room_size(room) -> int:
    return sum(1 for _ in socketio.server.manager.get_participants("/", room))


def init_socketio(app):
    """Initialize Socket.IO and register signaling handlers."""
    # None = same-origin only; add trusted origins via SOCKETIO_CORS_ORIGINS
    socketio.init_app(
        app,
        cors_allowed_origins=app.config.get("SOCKETIO_CORS_ORIGINS") or None,
        # Shared queue when running more than one process (rooms span them)
        message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE"),
    )

    @socketio.on("connect")
    def handle_connect(auth=None):
        # Nearby Share is only offered to logged-in users; refuse anyone else
        if load_session_user(session) is None:
            return False

    @socketio.on("disconnect")
    def handle_disconnect(*args):
        with _join_lock:
            _join_times.pop(request.sid, None)

    @socketio.on("join_room")
    def handle_join(data):
        room = _room_from(data)
        if not room:
            return
        if not _join_allowed(request.sid):
            emit("join_refused", {"reason": "too_many_attempts"})
            return
        if room not in rooms() and _room_size(room) >= MAX_ROOM_SIZE:
            emit("join_refused", {"reason": "room_full"})
            return
        join_room(room)
        emit("peer_joined", {"sid": request.sid}, to=room, include_self=False)

    @socketio.on("leave_room")
    def handle_leave(data):
        room = _room_from(data)
        if not room or room not in rooms():
            return
        leave_room(room)
        emit("peer_left", {"sid": request.sid}, to=room, include_self=False)

    @socketio.on("signal")
    def handle_signal(data):
        room = _room_from(data)
        payload = data.get("payload") if room else None
        # Only members of a room may signal into it (no injecting offers
        # into someone else's share)
        if not room or payload is None or room not in rooms():
            return
        emit("signal", payload, to=room, include_self=False)
