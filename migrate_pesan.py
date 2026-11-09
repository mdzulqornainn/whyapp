"""Ubah isi kolom `chat.pesan` format lama (level Differential Manchester,
awalan dm1:/dm2:/dm3:) menjadi frame bit (START + DATA + PARITY + END).

Jalankan sekali:  python migrate_pesan.py
Baris yang sudah berupa frame bit dibiarkan. Baris yang tidak bisa dibaca
hanya dilaporkan, tidak diubah.
"""

import asyncio
import os

import aiomysql

from app import bytes_to_frame_bits, decode_stored_message, frame_bits_to_bytes


async def main() -> None:
    connection = await aiomysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        db=os.getenv("MYSQL_DATABASE", "whyapp"),
        charset="utf8mb4",
        autocommit=False,
    )
    converted = skipped = failed = 0
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT id_chat, pesan FROM chat")
            rows = await cursor.fetchall()
            for id_chat, pesan in rows:
                if frame_bits_to_bytes(pesan) is not None:
                    skipped += 1
                    continue
                data_bytes = decode_stored_message(pesan)
                if data_bytes is None:
                    failed += 1
                    print(f"Tidak bisa dibaca, dilewati: id_chat={id_chat}")
                    continue
                await cursor.execute(
                    "UPDATE chat SET pesan = %s WHERE id_chat = %s",
                    (bytes_to_frame_bits(data_bytes), id_chat),
                )
                converted += 1
        await connection.commit()
    finally:
        connection.close()
    print(f"Selesai: {converted} diubah, {skipped} sudah frame bit, {failed} gagal.")


if __name__ == "__main__":
    asyncio.run(main())
