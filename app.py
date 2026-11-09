"""Server sederhana untuk aplikasi chat P2P.

Server ini membantu dua browser bertukar informasi WebRTC dan menyimpan
frame bit pesan (START + DATA + PARITY + END per byte) di kolom `pesan`
tabel `chat` untuk riwayat room.
Riwayat dibaca dari database dan dikirim ke browser saat pengguna masuk room.
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
    await ensure_chat_schema(app["db_pool"])
    yield
    app["db_pool"].close()
    await app["db_pool"].wait_closed()


async def ensure_chat_schema(pool: aiomysql.Pool) -> None:
    """Tambahkan kolom chat.penerima_id pada database lama jika belum ada."""
    async with pool.acquire() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'chat' "
                "AND COLUMN_NAME = 'penerima_id'"
            )
            (exists,) = await cursor.fetchone()
            if exists:
                return
            await cursor.execute(
                "ALTER TABLE chat "
                "ADD COLUMN penerima_id CHAR(36) NULL AFTER user_id, "
                "ADD CONSTRAINT fk_chat_penerima FOREIGN KEY (penerima_id) "
                "REFERENCES pengguna(user_id) ON DELETE SET NULL ON UPDATE CASCADE"
            )
            print("Kolom chat.penerima_id ditambahkan.", flush=True)


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


ROOM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
ROOM_ID_ATTEMPTS = 10


def random_room_id() -> str:
    """Buat Room ID acak berformat XXXX-XXXX."""
    part = lambda: "".join(secrets.choice(ROOM_ALPHABET) for _ in range(4))
    return f"{part()}-{part()}"


async def create_room(request: web.Request) -> web.Response:
    """Buat Room ID baru yang dijamin belum ada di tabel `room`.

    ID langsung disimpan dengan INSERT. Jika ternyata sudah ada (duplicate
    key), dibuat ID lain. Cara ini aman walaupun dua orang menekan tombol
    bersamaan, karena pengecekan dan penyimpanan terjadi dalam satu query.
    """
    if not session_from_request(request):
        return web.json_response({"message": "Silakan login terlebih dahulu."}, status=401)

    async with web_app["db_pool"].acquire() as connection:
        async with connection.cursor() as cursor:
            for _ in range(ROOM_ID_ATTEMPTS):
                room_id = random_room_id()
                await cursor.execute(
                    "INSERT IGNORE INTO room (room_id) VALUES (%s)",
                    (room_id,),
                )
                if cursor.rowcount == 1:
                    return web.json_response({"roomId": room_id}, status=201)

    return web.json_response(
        {"message": "Gagal membuat Room ID unik, coba lagi."},
        status=503,
    )


web_app.router.add_post("/api/rooms", create_room)
web_app.router.add_post("/api/register", register_user)
web_app.router.add_post("/api/login", login_user)
web_app.router.add_post("/api/logout", logout_user)
web_app.router.add_get("/api/me", current_user)

FRAME_SIZE = 11  # START + DATA 8 bit + PARITY + END


def bytes_to_frame_bits(data_bytes: list[int]) -> str:
    """Ubah byte menjadi frame bit, sama seperti createSignalFrame di app.js."""
    frames = []
    for value in data_bytes:
        data_bits = f"{value:08b}"
        parity = str(data_bits.count("1") % 2)
        end = "0" if data_bits[-1] == "1" else "1"
        frames.append(f"1{data_bits}{parity}{end}")
    return "".join(frames)


def frame_bits_to_bytes(bits: str) -> list[int] | None:
    """Validasi frame bit lalu kembalikan byte DATA, atau None jika tidak valid."""
    if not bits or len(bits) % FRAME_SIZE or not re.fullmatch(r"[01]+", bits):
        return None
    data_bytes = []
    for index in range(0, len(bits), FRAME_SIZE):
        byte_frame = bits[index:index + FRAME_SIZE]
        data_bits = byte_frame[1:9]
        if (
            byte_frame[0] != "1"
            or byte_frame[-1] == data_bits[-1]
            or (data_bits.count("1") + int(byte_frame[-2])) % 2
        ):
            return None
        data_bytes.append(int(data_bits, 2))
    return data_bytes


def decode_stored_message(value: str) -> list[int] | None:
    # Format sekarang: kolom `pesan` berisi frame bit langsung.
    data_bytes = frame_bits_to_bytes(value)
    if data_bytes is not None:
        return data_bytes

    # Format lama: level Differential Manchester (awalan dm1:/dm2:/dm3:).
    frame_version = value[:4] if value.startswith(("dm2:", "dm3:")) else ""
    levels = value[4:] if frame_version or value.startswith("dm1:") else value
    if not levels or len(levels) % 2 or not re.fullmatch(r"(?:01|10)+", levels):
        return None

    previous = "0"
    frame = []
    for index in range(0, len(levels), 2):
        frame.append("1" if levels[index] == previous else "0")
        previous = levels[index + 1]
    bits = "".join(frame)

    if frame_version:
        if len(bits) % 11:
            return None
        data_bits = "".join(bits[i + 1:i + 9] for i in range(0, len(bits), 11))
    else:
        data_bits = bits[1:-2]
    if not data_bits or len(data_bits) % 8:
        return None
    return [int(data_bits[i:i + 8], 2) for i in range(0, len(data_bits), 8)]

async def load_room_history(room_id: str, user_id: str) -> list[dict]:
    """Ambil riwayat room yang hanya melibatkan pengguna ini.

    Pesan hanya dikembalikan jika pengguna adalah pengirim atau penerimanya,
    sehingga orang yang baru masuk room tidak bisa membaca percakapan lama
    milik pengguna lain.
    """
    async with web_app["db_pool"].acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT c.id_chat, c.user_id, c.pesan, "
                "UNIX_TIMESTAMP(c.waktu_kirim) * 1000 AS timestamp, "
                "p.nama_pengguna AS sender "
                "FROM chat c JOIN pengguna p ON p.user_id = c.user_id "
                "WHERE c.room_id = %s AND (c.user_id = %s OR c.penerima_id = %s) "
                "ORDER BY c.id_chat DESC LIMIT 100",
                (room_id, user_id, user_id),
            )
            rows = await cursor.fetchall()

    history = []
    for row in reversed(rows):
        data_bytes = decode_stored_message(row["pesan"])
        if data_bytes is None:
            continue
        history.append(
            {
                "sender": row["sender"],
                "bytes": data_bytes,
                "timestamp": int(row["timestamp"]),
                "outgoing": row["user_id"] == user_id,
            }
        )
    return history

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

    # Kirim riwayat chat room dari database ke pengguna yang baru masuk.
    history = await load_room_history(room_id, user_data["user_id"])
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
    frame = data.get("frame")
    # Kolom `pesan` menyimpan frame bit apa adanya:
    # START 1 + DATA 8 bit + PARITY genap + END per byte.
    if (
        not room_id
        or not isinstance(frame, str)
        or len(frame) > 65535
        or frame_bits_to_bytes(frame) is None
    ):
        return
    # Penerima ditentukan server dari peer yang sedang ada di room yang sama,
    # bukan dari data yang dikirim browser.
    receiver_id = None
    for peer_id in users_in_room(room_id) - {socket_id}:
        try:
            peer_data = await get_user_data(peer_id)
        except KeyError:
            continue
        if peer_data.get("room_id") == room_id:
            receiver_id = peer_data.get("user_id")
            break

    async with web_app["db_pool"].acquire() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO chat (room_id, user_id, penerima_id, pesan) "
                "VALUES (%s, %s, %s, %s)",
                (room_id, user_data["user_id"], receiver_id, frame),
            )


if __name__ == "__main__":
    print(f"Server berjalan di http://localhost:{PORT}")
    web.run_app(web_app, host="0.0.0.0", port=PORT)