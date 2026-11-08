# Chat P2P Python untuk Pemula

Contoh aplikasi chat sederhana dengan autentikasi pengguna. Pesan dikirim
langsung antar-browser memakai WebRTC DataChannel. Python menangani halaman,
autentikasi, penyimpanan riwayat ciphertext, dan proses awal koneksi WebRTC.

Setiap pesan memiliki visualisasi sinyal Differential Manchester dengan frame:

```text
START | DATA ASCII | PARITY | END
```

Parity menggunakan **even parity**. Nilai START adalah kebalikan bit pertama
data, sedangkan nilai END adalah kebalikan bit terakhir data. Contoh: bit `1`
menghasilkan event `0`, dan bit `0` menghasilkan event `1`. Visualisasi memakai
byte UTF-8 pesan asli, bukan hasil XOR. Jadi pesan `1` memakai HEX `31`,
DATA `00110001`, dan FRAME `10011000110`. Ciphertext XOR tetap dipakai untuk
pengiriman melalui DataChannel.

## 1. Instalasi

Pastikan Python sudah terpasang, lalu jalankan:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows:

```bat
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## 2. Database Laragon

Pastikan MySQL Laragon aktif, lalu jalankan [database.sql](database.sql)
melalui HeidiSQL atau phpMyAdmin. Script tersebut membuat database `whyapp`,
tabel pengguna, room, chat, serta dua akun dummy.

Konfigurasi default:

```text
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=whyapp
```

Jika password MySQL Laragon tidak kosong, isi `MYSQL_PASSWORD` sebelum
menjalankan aplikasi.

Windows PowerShell:

```powershell
$env:MYSQL_PASSWORD = "password-mysql-anda"
```

Data dummy:

| Username | Password |
|---|---|
| `alice` | `password123` |
| `bob` | `password123` |

## 3. Menjalankan

```bash
python app.py
```

Buka <http://localhost:3001> di browser.

## 4. Mencoba chat

1. Buka <http://localhost:3001>.
2. Daftar akun baru atau masuk menggunakan akun dummy.
3. Klik **Buat Room ID**, lalu klik **Masuk ke room**.
4. Buka alamat yang sama di browser kedua atau mode incognito.
5. Masuk dengan akun kedua dan masukkan Room ID tadi.
6. Tunggu status **DataChannel: open**.
7. Kirim pesan.

Riwayat pesan disimpan sebagai ciphertext di tabel `chat` dan dimuat kembali
saat pengguna masuk ke room. Isi pesan tetap dikirim melalui DataChannel P2P.

## 5. Endpoint API

| Method | Endpoint | Keterangan |
|---|---|---|
| `POST` | `/api/register` | Membuat akun baru |
| `POST` | `/api/login` | Login dan membuat session cookie |
| `POST` | `/api/logout` | Menghapus session |
| `GET` | `/api/me` | Memeriksa session aktif |
| `GET` | `/health` | Memeriksa status server |

Endpoint login dan register harus dipanggil menggunakan `POST` dengan body JSON:

```json
{
  "username": "alice",
  "password": "password123"
}
```

Membuka `/api/login` langsung di browser menggunakan `GET` akan menghasilkan
`405 Method Not Allowed`; gunakan halaman login atau request `POST`.

## 6. Penjelasan folder

```text
app.py                 server Python dan signaling Socket.IO
database.sql           schema MySQL dan data dummy
requirements.txt       daftar library Python
static/index.html      halaman HTML awal
static/style.css       tampilan aplikasi
static/app.js          halaman, WebRTC, dan enkripsi XOR
```

## Catatan keamanan

XOR digunakan untuk pembelajaran, bukan untuk aplikasi produksi. XOR dengan
kunci berulang tidak setara dengan enkripsi modern seperti AES.
