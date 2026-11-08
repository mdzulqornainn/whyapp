"""Server sederhana untuk aplikasi chat P2P.

Server ini membantu dua browser bertukar informasi WebRTC dan menyimpan
pesan berformat Differential Manchester untuk riwayat room.
Pesan langsung antar-browser tetap menggunakan ciphertext XOR.
"""

from pathlib import Path
from http.cookies import SimpleCookie
import os
import re
import secrets
import time
import uuid

import aiomysql
import bcrypt
from aiohttp import web
import socketio


# ---------------------------------------------------------------------------
# Pengaturan dasar
# ---------------------------------------------------------------------------

PROJECT_FOLDER = Path(__file__).parent
PORT = int(os.getenv("PORT", "3001"))
MAX_USERS_IN_ROOM = 2
VALID_ROOM_ID = re.compile(r"^[A-Z0-9-]{4,32}$")
VALID_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,100}$")
SESSION_COOKIE = "whyapp_session"
SESSION_TTL = 60 * 60 * 24 * 7
sessions: dict[str, dict] = {}


# Socket.IO dipakai untuk "signaling", yaitu mengirim offer, answer, dan ICE.
socket_server = socketio.AsyncServer(
    async_mode="aiohttp",
    cors_allowed_origins="*",
)

@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        response = await handler(request)

    origin = request.headers.get("Origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Vary"] = "Origin"
    return response


web_app = web.Application(middlewares=[cors_middleware])
socket_server.attach(web_app)


async def init_database(app: web.Application) -> None:
    app["db_pool"] = await aiomysql.create_pool(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        db=os.getenv("MYSQL_DATABASE", "whyapp"),
        autocommit=True,
        charset="utf8mb4",
        minsize=1,
        maxsize=10,
    )
    yield
    app["db_pool"].close()
    await app["db_pool"].wait_closed()


web_app.cleanup_ctx.append(init_database)


# ---------------------------------------------------------------------------
# Halaman web dan endpoint pemeriksaan
# ---------------------------------------------------------------------------

async def show_homepage(request: web.Request) -> web.FileResponse:
    """Kirim halaman utama ke browser."""
    return web.FileResponse(PROJECT_FOLDER / "static" / "index.html")


async def show_health(request: web.Request) -> web.Response:
    """Endpoint kecil untuk memastikan server sedang berjalan."""
    connected_users = socket_server.manager.rooms.get("/", {}).get("", set())
    return web.json_response(
        {
            "status": "ok",
            "connected_users": len(connected_users),
        }
    )


web_app.router.add_get("/", show_homepage)
web_app.router.add_get("/health", show_health)
web_app.router.add_static("/static", PROJECT_FOLDER / "static")


# ---------------------------------------------------------------------------
# Fungsi bantuan room
# ---------------------------------------------------------------------------

def users_in_room(room_id: str) -> set[str]:
    """Kembalikan semua socket ID yang berada di room tertentu."""
    rooms = socket_server.manager.rooms.get("/", {})
    return set(rooms.get(room_id, set()))


def json_body(request: web.Request) -> dict:
    return request.get("json", {})


def session_from_request(request: web.Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = sessions.get(token)
    if session and session["expires_at"] > time.time():
        return session
    if token in sessions:
        del sessions[token]
    return None


def set_session(response: web.Response, user: dict) -> None:
    token = secrets.token_urlsafe(32)
    sessions[token] = {
        **user,
        "expires_at": time.time() + SESSION_TTL,
    }
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="Lax",
    )


async def fetch_user_by_name(name: str) -> dict | None:
    async with web_app["db_pool"].acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT user_id, nama_pengguna, password FROM pengguna "
                "WHERE nama_pengguna = %s",
                (name,),
            )
            return await cursor.fetchone()


async def register_user(request: web.Request) -> web.Response:
    data = await request.json()
    name = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not VALID_USERNAME.fullmatch(name) or not 8 <= len(password) <= 72:
        return web.json_response(
            {"message": "Username 3-100 karakter (huruf, angka, _, ., -) dan password 8-72 karakter."},
            status=400,
        )
    if await fetch_user_by_name(name):
        return web.json_response({"message": "Username sudah digunakan."}, status=409)
    user_id = str(uuid.uuid4())
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    async with web_app["db_pool"].acquire() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO pengguna (user_id, nama_pengguna, password) VALUES (%s, %s, %s)",
                (user_id, name, password_hash),
            )
    response = web.json_response({"user_id": user_id, "username": name}, status=201)
    set_session(response, {"user_id": user_id, "username": name})
    return response


async def login_user(request: web.Request) -> web.Response:
    data = await request.json()
    name = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    user = await fetch_user_by_name(name)
    if not user or not bcrypt.checkpw(password.encode(), user["password"].encode()):
        return web.json_response({"message": "Username atau password salah."}, status=401)
    response = web.json_response(
        {"user_id": user["user_id"], "username": user["nama_pengguna"]}
    )
    set_session(response, {"user_id": user["user_id"], "username": user["nama_pengguna"]})
    return response


async def logout_user(request: web.Request) -> web.Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        sessions.pop(token, None)
    response = web.json_response({"status": "ok"})
    response.del_cookie(SESSION_COOKIE)
    return response


async def current_user(request: web.Request) -> web.Response:
    session = session_from_request(request)
    if not session:
        return web.json_response({"authenticated": False})
    return web.json_response(
        {"authenticated": True, "user_id": session["user_id"], "username": session["username"]}
    )


web_app.router.add_post("/api/register", register_user)
web_app.router.add_post("/api/login", login_user)
web_app.router.add_post("/api/logout", logout_user)
web_app.router.add_get("/api/me", current_user)


async def get_user_data(socket_id: str) -> dict:
    """Ambil username dan room milik sebuah koneksi."""
    return await socket_server.get_session(socket_id)


async def leave_room(socket_id: str) -> None:
    """Keluarkan pengguna dari room dan beri tahu lawan bicaranya."""
    try:
        user_data = await get_user_data(socket_id)
    except KeyError:
        # Session mungkin sudah dibuang oleh Socket.IO saat disconnect.
        return

    room_id = user_data.get("room_id")

    if not room_id:
        return

    await socket_server.emit(
        "peer-left",
        {
            "socketId": socket_id,
            "username": user_data.get("username", "Anonymous"),
        },
        room=room_id,
        skip_sid=socket_id,
    )
    await socket_server.leave_room(socket_id, room_id)
    # Saat disconnect, session tidak perlu disimpan kembali.
    if socket_id in socket_server.manager.rooms.get("/", {}).get("", set()):
        await socket_server.save_session(
            socket_id,
            {
                "room_id": None,
                "user_id": user_data.get("user_id"),
                "username": user_data.get("username", "Anonymous"),
            },
        )


# ---------------------------------------------------------------------------
# Koneksi dan room
# ---------------------------------------------------------------------------

@socket_server.event
async def connect(socket_id: str, environ: dict) -> bool:
    """Dipanggil saat browser tersambung."""
    cookies = SimpleCookie()
    cookies.load(environ.get("HTTP_COOKIE", ""))
    token = cookies.get(SESSION_COOKIE)
    session = sessions.get(token.value) if token else None
    if not session or session["expires_at"] <= time.time():
        return False
    await socket_server.save_session(
        socket_id,
        {
            "room_id": None,
            "user_id": session["user_id"],
            "username": session["username"],
        },
    )
    print(f"Terhubung: {socket_id}")
    return True


@socket_server.event
async def disconnect(socket_id: str) -> None:
    """Dipanggil saat browser menutup koneksi."""
    try:
        await leave_room(socket_id)
    except Exception as error:
        # Cleanup tidak boleh menghentikan log disconnect.
        print(f"Gagal membersihkan room {socket_id}: {error}", flush=True)
    finally:
        print(f"Terputus: {socket_id}", flush=True)


@socket_server.on("join-room")
async def join_room(socket_id: str, data: dict | None = None) -> None:
    """Masukkan pengguna ke room jika ID valid dan room belum penuh."""
    data = data or {}
    room_id = str(data.get("roomId", "")).strip().upper()
    user_data = await get_user_data(socket_id)
    username = user_data["username"]

    if not VALID_ROOM_ID.fullmatch(room_id):
        await socket_server.emit(
            "join-error",
            {"message": "Room ID harus 4-32 karakter A-Z, 0-9, atau -."},
            to=socket_id,
        )
        return

    existing_users = users_in_room(room_id)
    old_room_id = user_data.get("room_id")
    if old_room_id == room_id:
        existing_users.discard(socket_id)
    elif len(existing_users) >= MAX_USERS_IN_ROOM:
        await socket_server.emit("room-full", {"roomId": room_id}, to=socket_id)
        return
    elif old_room_id:
        await leave_room(socket_id)

    if len(existing_users) >= MAX_USERS_IN_ROOM:
        await socket_server.emit("room-full", {"roomId": room_id}, to=socket_id)
        return

    peers = []
    for peer_id in existing_users:
        peer_data = await get_user_data(peer_id)
        peers.append(
            {
                "socketId": peer_id,
                "username": peer_data.get("username", "Anonymous"),
            }
        )

    async with web_app["db_pool"].acquire() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO room (room_id) VALUES (%s)",
                (room_id,),
            )

    await socket_server.enter_room(socket_id, room_id)
    await socket_server.save_session(
        socket_id,
        {
            "room_id": room_id,
            "user_id": user_data["user_id"],
            "username": username,
        },
    )

    async with web_app["db_pool"].acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT c.pesan AS cipher, UNIX_TIMESTAMP(c.waktu_kirim) * 1000 "
                "AS timestamp, "
                "p.nama_pengguna AS sender FROM chat c "
                "JOIN pengguna p ON p.user_id = c.user_id "
                "WHERE c.room_id = %s ORDER BY c.waktu_kirim ASC LIMIT 100",
                (room_id,),
            )
            history = await cursor.fetchall()

    for message in history:
        if message["cipher"].startswith(("dm2:", "dm3:")):
            message["encoded"] = message.pop("cipher")
        elif message["cipher"].startswith("dm1:"):
            message["encoded"] = message.pop("cipher")[4:]
        elif (
            len(message["cipher"]) % 16 == 6
            and re.fullmatch(r"(?:01|10)+", message["cipher"])
        ):
            # Frame 8n+3 bit menjadi 16n+6 level; Base64 panjangnya kelipatan 4.
            message["encoded"] = message.pop("cipher")

    await socket_server.emit(
        "room-joined",
        {"roomId": room_id, "peers": peers, "history": history},
        to=socket_id,
    )
    await socket_server.emit(
        "peer-joined",
        {"socketId": socket_id, "username": username},
        room=room_id,
        skip_sid=socket_id,
    )


@socket_server.on("leave-room")
async def handle_leave_room(socket_id: str) -> None:
    """Dipanggil saat pengguna meninggalkan halaman room."""
    await leave_room(socket_id)


# ---------------------------------------------------------------------------
# Pengiriman data signaling
# ---------------------------------------------------------------------------

async def forward_to_peer(
    socket_id: str,
    data: dict | None,
    event_name: str,
) -> None:
    """Teruskan data hanya ke peer yang satu room."""
    data = data or {}
    target_id = data.get("to")
    sender_data = await get_user_data(socket_id)
    room_id = sender_data.get("room_id")

    if not target_id or not room_id:
        return
    if target_id not in users_in_room(room_id):
        return

    target_data = await get_user_data(target_id)
    if target_data.get("room_id") != room_id:
        return

    message = {key: value for key, value in data.items() if key != "to"}
    message["from"] = socket_id
    message["username"] = sender_data.get("username", "Anonymous")
    await socket_server.emit(event_name, message, to=target_id)


@socket_server.on("offer")
async def forward_offer(socket_id: str, data: dict | None = None) -> None:
    await forward_to_peer(socket_id, data, "offer")


@socket_server.on("answer")
async def forward_answer(socket_id: str, data: dict | None = None) -> None:
    await forward_to_peer(socket_id, data, "answer")


@socket_server.on("ice-candidate")
async def forward_ice_candidate(
    socket_id: str,
    data: dict | None = None,
) -> None:
    await forward_to_peer(socket_id, data, "ice-candidate")


@socket_server.on("save-chat")
async def save_chat(socket_id: str, data: dict | None = None) -> None:
    data = data or {}
    user_data = await get_user_data(socket_id)
    room_id = user_data.get("room_id")
    encoded = data.get("encoded")
    frame_version = encoded[:4] if isinstance(encoded, str) and encoded.startswith(("dm2:", "dm3:")) else ""
    is_per_byte_frame = bool(frame_version)
    if is_per_byte_frame:
        encoded = encoded[4:]
    if isinstance(encoded, str) and encoded.startswith("dm1:"):
        encoded = encoded[4:]
    if (
        not room_id
        or not isinstance(encoded, str)
        or len(encoded) > 65535
        or not re.fullmatch(r"(?:01|10)+", encoded)
    ):
        return
    # Frame per-byte berisi START + DATA + PARITY + END.
    levels = encoded
    previous = "0"
    frame = []
    for index in range(0, len(levels), 2):
        frame.append("1" if levels[index] == previous else "0")
        previous = levels[index + 1]
    bits = "".join(frame)
    if is_per_byte_frame:
        if not bits or len(bits) % 11:
            return
        for index in range(0, len(bits), 11):
            byte_frame = bits[index:index + 11]
            data_bits = byte_frame[1:9]
            start_is_invalid = (
                byte_frame[0] != "1"
                if frame_version == "dm3:"
                else byte_frame[0] == data_bits[0]
            )
            if (
                start_is_invalid
                or byte_frame[-1] == data_bits[-1]
                or (data_bits.count("1") + int(byte_frame[-2])) % 2
            ):
                return
        stored_value = f"{frame_version}{encoded}"
    else:
        data_bits = bits[1:-2]
        if (
            not data_bits
            or len(data_bits) % 8
            or bits[0] == data_bits[0]
            or bits[-1] == data_bits[-1]
            or (data_bits.count("1") + int(bits[-2])) % 2
        ):
            return
        stored_value = encoded
    async with web_app["db_pool"].acquire() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO chat (room_id, user_id, pesan) VALUES (%s, %s, %s)",
                (room_id, user_data["user_id"], stored_value),
            )


if __name__ == "__main__":
    print(f"Server berjalan di http://localhost:{PORT}")
    web.run_app(web_app, host="0.0.0.0", port=PORT)
