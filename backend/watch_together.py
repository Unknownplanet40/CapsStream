"""
backend/watch_together.py -- Watch Together LAN sync rooms.

Rooms are ephemeral (memory-only, destroyed on last disconnect).
Transport: WebSocket via Flask-SocketIO (threading mode, no eventlet).
"""

import time
import random
import string
import logging

log = logging.getLogger(__name__)

_rooms: dict = {}   # { room_code: room_dict }
_sid_room: dict = {}  # { socket_sid: room_code }


def _gen_code() -> str:
    chars = string.ascii_uppercase + string.digits
    for _ in range(100):
        code = "".join(random.choices(chars, k=6))
        if code not in _rooms:
            return code
    raise RuntimeError("Could not generate unique room code")


def init_socketio(app):
    """
    Create SocketIO instance, register Watch Together event handlers,
    and return the socketio object so app.py can call socketio.run(app, ...).
    """
    try:
        from flask_socketio import SocketIO, emit, join_room, leave_room
    except ImportError:
        log.warning(
            "[WatchTogether] flask-socketio not installed -- Watch Together disabled. "
            "Run: pip install flask-socketio simple-websocket"
        )
        return None

    from flask import request, session

    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )

    def _member_info(sid, data=None):
        data = data or {}
        profile = session.get("profile", {}) or {}
        name = data.get("user_name") or profile.get("name") or profile.get("username") or "Guest"
        color = data.get("user_color") or profile.get("color") or profile.get("theme") or "#8b5cf6"
        avatar = data.get("user_avatar") or profile.get("avatar") or profile.get("custom_avatar_url") or "👤"
        return {"sid": sid, "name": name, "color": color, "avatar": avatar}

    def _room_public(room):
        pos = room["position"]
        if room.get("is_playing") and "last_sync_time" in room:
            pos += max(0.0, time.time() - room["last_sync_time"])
        return {
            "code": room["code"],
            "media_id": room.get("media_id"),
            "media_type": room.get("media_type"),
            "media_title": room.get("media_title"),
            "position": round(pos, 2),
            "is_playing": room["is_playing"],
            "leader_sid": room.get("leader_sid"),
            "members": room["members"],
            "chat": room.get("chat", [])[-50:],
        }

    def _remove_member(sid):
        code = _sid_room.pop(sid, None)
        if not code or code not in _rooms:
            return None, None
        room = _rooms[code]
        room["members"] = [m for m in room["members"] if m["sid"] != sid]
        if room["leader_sid"] == sid and room["members"]:
            room["leader_sid"] = room["members"][0]["sid"]
        if not room["members"]:
            del _rooms[code]
            log.debug("[WatchTogether] Room %s destroyed (empty)", code)
            return code, None
        return code, room

    @socketio.on("connect", namespace="/wt")
    def on_connect():
        log.debug("[WatchTogether] Client connected: %s", request.sid)

    @socketio.on("disconnect", namespace="/wt")
    def on_disconnect():
        sid = request.sid
        code, room = _remove_member(sid)
        if code and room:
            emit(
                "member_left",
                {"sid": sid, "members": room["members"], "leader_sid": room.get("leader_sid")},
                to=code,
                namespace="/wt",
            )

    @socketio.on("create_room", namespace="/wt")
    def on_create_room(data):
        sid = request.sid
        try:
            code = _gen_code()
        except RuntimeError as exc:
            emit("error", {"message": str(exc)}, namespace="/wt")
            return
        now = time.time()
        room = {
            "code": code,
            "media_id": data.get("media_id"),
            "media_type": data.get("media_type"),
            "media_title": data.get("media_title"),
            "position": float(data.get("position", 0)),
            "is_playing": bool(data.get("is_playing", False)),
            "last_sync_time": now,
            "leader_sid": sid,
            "members": [_member_info(sid, data)],
            "chat": [],
        }
        _rooms[code] = room
        _sid_room[sid] = code
        join_room(code, namespace="/wt")
        emit("room_joined", {**_room_public(room), "your_sid": sid}, namespace="/wt")
        log.info("[WatchTogether] Room %s created by %s", code, sid)

    @socketio.on("join_room", namespace="/wt")
    def on_join_room(data):
        sid = request.sid
        code = (data.get("code") or "").strip().upper()
        if code not in _rooms:
            emit("error", {"message": "Room not found."}, namespace="/wt")
            return
        _remove_member(sid)
        room = _rooms[code]
        member = _member_info(sid, data)
        room["members"].append(member)
        _sid_room[sid] = code
        join_room(code, namespace="/wt")
        emit("room_joined", {**_room_public(room), "your_sid": sid}, namespace="/wt")
        emit(
            "member_joined",
            {"member": member, "members": room["members"]},
            to=code,
            include_self=False,
            namespace="/wt",
        )
        log.info("[WatchTogether] %s joined room %s (%d members)", sid, code, len(room["members"]))

    @socketio.on("sync", namespace="/wt")
    def on_sync(data):
        sid = request.sid
        code = _sid_room.get(sid)
        if not code or code not in _rooms:
            return
        room = _rooms[code]
        pos = float(data.get("position", room["position"]))
        playing = bool(data.get("is_playing", room["is_playing"]))
        room["position"] = pos
        room["is_playing"] = playing
        room["last_sync_time"] = time.time()
        sent_at = data.get("sent_at")
        log.debug("[WatchTogether] sync in %s from %s: pos=%.2f play=%s", code, sid, pos, playing)
        emit(
            "sync",
            {"position": pos, "is_playing": playing, "from_sid": sid, "sent_at": sent_at},
            to=code,
            include_self=False,
            namespace="/wt",
        )

    @socketio.on("reaction", namespace="/wt")
    def on_reaction(data):
        sid = request.sid
        code = _sid_room.get(sid)
        if not code or code not in _rooms:
            return
        room = _rooms[code]
        member = next((m for m in room["members"] if m["sid"] == sid), {})
        emit(
            "reaction",
            {"emoji": data.get("emoji", "X"), "sender": member.get("name", "?"), "color": member.get("color", "#8b5cf6")},
            to=code,
            namespace="/wt",
        )

    @socketio.on("chat_msg", namespace="/wt")
    def on_chat_msg(data):
        sid = request.sid
        code = _sid_room.get(sid)
        if not code or code not in _rooms:
            return
        text = (data.get("text") or "").strip()[:500]
        if not text:
            return
        room = _rooms[code]
        member = next((m for m in room["members"] if m["sid"] == sid), {})
        msg = {
            "sender": member.get("name", "?"),
            "color": member.get("color", "#8b5cf6"),
            "avatar": member.get("avatar"),
            "text": text,
            "ts": time.time(),
        }
        room["chat"].append(msg)
        if len(room["chat"]) > 200:
            room["chat"] = room["chat"][-200:]
        emit("chat_msg", msg, to=code, namespace="/wt")

    @socketio.on("leave_room", namespace="/wt")
    def on_leave_room():
        sid = request.sid
        code, room = _remove_member(sid)
        if code:
            leave_room(code, namespace="/wt")
        if code and room:
            emit(
                "member_left",
                {"sid": sid, "members": room["members"], "leader_sid": room.get("leader_sid")},
                to=code,
                namespace="/wt",
            )

    @app.route("/api/watch-together/rooms", methods=["GET"])
    def wt_rooms():
        from flask import jsonify
        return jsonify({"rooms": len(_rooms), "codes": list(_rooms.keys())})

    @app.route("/api/watch-together/room/<code>", methods=["GET"])
    def wt_room_details(code):
        from flask import jsonify
        c = (code or "").strip().upper()
        room = _rooms.get(c)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        return jsonify({
            "code": room["code"],
            "media_id": room.get("media_id"),
            "media_type": room.get("media_type"),
            "media_title": room.get("media_title"),
            "position": room["position"],
            "is_playing": room["is_playing"],
            "member_count": len(room.get("members", [])),
        })

    return socketio
