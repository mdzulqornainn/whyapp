"""Server sederhana untuk aplikasi chat P2P.

Server ini hanya membantu dua browser bertukar informasi WebRTC.
Isi pesan tidak disimpan atau diteruskan oleh server.
"""

from pathlib import Path
import os
import re

from aiohttp import web
import socketio


# ---------------------------------------------------------------------------
# Pengaturan dasar
# ---------------------------------------------------------------------------

PROJECT_FOLDER = Path(__file__).parent
PORT = int(os.getenv("PORT", "3001"))
MAX_USERS_IN_ROOM = 2
VALID_ROOM_ID = re.compile(r"^[A-Z0-9-]{4,32}$")


# Socket.IO dipakai untuk "signaling", yaitu mengirim offer, answer, dan ICE.
socket_server = socketio.AsyncServer(
    async_mode="aiohttp",
    cors_allowed_origins="*",
)

web_app = web.Application()
socket_server.attach(web_app)


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
            {"room_id": None, "username": user_data.get("username", "Anonymous")},
        )


# ---------------------------------------------------------------------------
# Koneksi dan room
# ---------------------------------------------------------------------------

@socket_server.event
async def connect(socket_id: str, environ: dict) -> None:
    """Dipanggil saat browser tersambung."""
    await socket_server.save_session(
        socket_id,
        {"room_id": None, "username": "Anonymous"},
    )
    print(f"Terhubung: {socket_id}")


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
    username = str(data.get("username", "")).strip()[:24] or "Anonymous"

    if not VALID_ROOM_ID.fullmatch(room_id):
        await socket_server.emit(
            "join-error",
            {"message": "Room ID harus 4-32 karakter A-Z, 0-9, atau -."},
            to=socket_id,
        )
        return

    old_data = await get_user_data(socket_id)
    if old_data.get("room_id") and old_data["room_id"] != room_id:
        await leave_room(socket_id)

    existing_users = users_in_room(room_id)
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

    await socket_server.enter_room(socket_id, room_id)
    await socket_server.save_session(
        socket_id,
        {"room_id": room_id, "username": username},
    )

    await socket_server.emit(
        "room-joined",
        {"roomId": room_id, "peers": peers},
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


if __name__ == "__main__":
    print(f"Server berjalan di http://localhost:{PORT}")
    web.run_app(web_app, host="0.0.0.0", port=PORT)
