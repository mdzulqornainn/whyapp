# Chat P2P Python untuk Pemula
#ngetes
Contoh aplikasi chat sederhana dengan autentikasi pengguna. Pesan dikirim
langsung antar-browser memakai WebRTC DataChannel. Python menangani halaman,
autentikasi, penyimpanan riwayat ke database, dan proses awal koneksi WebRTC
(signaling).

## Cara kerja singkat

Pesan diubah menjadi byte **Extended ASCII** (tabel Windows-1252, kode 0-255),
satu karakter menjadi satu byte. Huruf seperti `é`, `€`, dan `©` didukung,
tetapi emoji tidak.

Setiap byte dibungkus menjadi satu frame 11 bit:

```text
START | DATA 8 bit | PARITY | END
```

- **START** selalu `1`.
- **PARITY** memakai *even parity* (jumlah bit `1` pada DATA + PARITY genap).
- **END** adalah kebalikan bit terakhir DATA.

Satu byte menghasilkan 11 bit frame, tiga byte menghasilkan 33 bit. Contohnya,
pesan `1` memakai HEX `31`, DATA `00110001`, dan FRAME `10011000110`.

Frame bit tersebut digambar sebagai sinyal **Differential Manchester** di
room, dan juga disimpan apa adanya di kolom `pesan` tabel `chat`.

Untuk pengiriman langsung antar-browser, pesan dienkripsi XOR memakai Room ID
sebagai kunci, lalu dikirim melalui DataChannel.

Tampilan room menampilkan gambar sinyal, HEX, DATA, dan FRAME. Teks asli
tersembunyi sampai pengguna menekan **Terjemahkan** dan memasukkan password
akunnya.

## Tutorial setup

### Langkah 1 — Siapkan software

| Software | Keterangan |
|---|---|
| [Python 3.10+](https://www.python.org/downloads/) | Saat instalasi di Windows, centang **Add python.exe to PATH** |
| [Laragon](https://laragon.org/) | Menyediakan MySQL, HeidiSQL, dan phpMyAdmin |
| Browser modern | Chrome, Edge, atau Firefox (mendukung WebRTC) |

Cek Python dari terminal:

```bash
python --version
```

### Langkah 2 — Ambil source code

```bash
git clone <url-repository> whyapp
cd whyapp
```

Atau salin folder proyek, lalu buka terminal di folder tersebut.

### Langkah 3 — Buat virtual environment dan install library

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Jika PowerShell menolak menjalankan script aktivasi, jalankan sekali:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Windows (Command Prompt):

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Library yang terpasang: `aiohttp`, `python-socketio`, `aiomysql`, dan `bcrypt`.

### Langkah 4 — Siapkan database MySQL

1. Buka Laragon, lalu klik **Start All** sampai MySQL berjalan.
2. Klik **Database** untuk membuka HeidiSQL (atau buka phpMyAdmin).
3. Buka file [database.sql](database.sql), lalu jalankan seluruh isinya
   (HeidiSQL: **File → Run SQL file...**, phpMyAdmin: tab **Import** atau **SQL**).

Script tersebut membuat database `whyapp`, tabel `pengguna`, `room`, dan
`chat`, dua akun dummy, serta room `DEMO`.

### Langkah 5 — Atur koneksi database (jika perlu)

Konfigurasi default:

```text
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=whyapp
PORT=3001
```

Default ini cocok dengan Laragon standar (user `root` tanpa password). Jika
berbeda, isi environment variable di terminal yang sama sebelum menjalankan
aplikasi.

Windows PowerShell:

```powershell
$env:MYSQL_PASSWORD = "password-mysql-anda"
```

Linux / macOS:

```bash
export MYSQL_PASSWORD="password-mysql-anda"
```

### Langkah 6 — Jalankan aplikasi

```bash
python app.py
```

Jika berhasil, muncul tulisan:

```text
Server berjalan di http://localhost:3001
```

Buka <http://localhost:3001> di browser. Cek status server di
<http://localhost:3001/health>.

### Langkah 7 — Coba chat

1. Buka <http://localhost:3001>.
2. Daftar akun baru atau masuk menggunakan akun dummy:

   | Username | Password |
   |---|---|
   | `alice` | `password123` |
   | `bob` | `password123` |

3. Klik **Buat Room ID**, lalu klik **Masuk ke room**.
4. Buka alamat yang sama di browser kedua atau jendela incognito.
5. Masuk dengan akun kedua dan masukkan Room ID tadi.
6. Tunggu sampai status **DataChannel: open**.
7. Kirim pesan.

Satu room maksimal berisi dua orang.

### Langkah 8 (opsional) — Migrasi data lama

Versi sebelumnya menyimpan kolom `pesan` sebagai level sinyal Differential
Manchester dengan awalan `dm1:`, `dm2:`, atau `dm3:`. Untuk mengubah data lama
tersebut menjadi frame bit, jalankan sekali:

```bash
python migrate_pesan.py
```

Baris yang sudah berupa frame bit dibiarkan. Riwayat tetap bisa dibaca
walaupun migrasi tidak dijalankan.

## Riwayat chat

Setiap pesan disimpan di tabel `chat`. Kolom `pesan` berisi frame bit,
misalnya:

```text
10011000110
```

Kolom `penerima_id` mencatat lawan bicara yang ada di room saat pesan
dikirim. Penerima ditentukan oleh server, bukan oleh browser.

Saat pengguna masuk room, server mengirim maksimal 100 pesan terakhir yang
**dikirim atau diterima oleh pengguna itu sendiri**, lalu browser
menampilkannya sebagai gambar sinyal. Contohnya, jika Alice dan Bob
mengobrol, lalu Bob keluar dan Nain masuk ke room yang sama, Nain tidak
melihat percakapan Alice dan Bob. Alice tetap melihat riwayat percakapannya
dengan Bob dan dengan Nain.

Pada database lama, kolom `penerima_id` ditambahkan otomatis saat server
dijalankan. Pesan lama belum memiliki penerima, sehingga hanya terlihat oleh
pengirimnya.

Riwayat juga dapat dilihat langsung melalui HeidiSQL atau phpMyAdmin.

Setiap kartu pesan memiliki tombol **Terjemahkan**. Browser sudah menerima
byte DATA untuk menggambar sinyal; setelah password akun diverifikasi oleh
server menggunakan hash bcrypt yang tersimpan, browser mengubah byte menjadi
teks Windows-1252 dan menampilkannya. Password tidak disimpan ulang oleh fitur
ini. Ini hanya gerbang tampilan, bukan enkripsi: pengguna yang dapat membaca
data aplikasi atau database tetap dapat menerjemahkan frame tanpa password.

## Room ID

Tombol **Buat Room ID** meminta Room ID ke server (`POST /api/rooms`). Server
membuat ID acak berformat `XXXX-XXXX` dan langsung menyimpannya ke tabel
`room`. Jika ID tersebut sudah ada di database, server membuat ID lain,
sehingga Room ID baru tidak pernah duplikat.

Panjang pesan maksimal 5957 karakter (11 bit per karakter, batas kolom `TEXT`
65535 byte).

## Endpoint API

| Method | Endpoint | Keterangan |
|---|---|---|
| `POST` | `/api/register` | Membuat akun baru |
| `POST` | `/api/login` | Login dan membuat session cookie |
| `POST` | `/api/logout` | Menghapus session |
| `GET` | `/api/me` | Memeriksa session aktif |
| `POST` | `/api/verify-password` | Memeriksa password akun untuk membuka teks pesan (perlu login) |
| `POST` | `/api/rooms` | Membuat Room ID baru yang belum ada di database (perlu login) |
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

## Struktur folder

```text
app.py                 server Python, autentikasi, signaling Socket.IO, riwayat
migrate_pesan.py       migrasi kolom pesan format lama ke frame bit
database.sql           schema MySQL dan data dummy
requirements.txt       daftar library Python
static/index.html      halaman HTML awal
static/style.css       tampilan aplikasi
static/app.js          halaman, WebRTC, enkripsi XOR, frame bit, gambar sinyal
```

## Masalah umum

| Gejala | Penyebab dan solusi |
|---|---|
| `Can't connect to MySQL server` | MySQL Laragon belum jalan. Klik **Start All** |
| `Access denied for user 'root'` | Password MySQL tidak kosong. Isi `MYSQL_PASSWORD` (Langkah 5) |
| `Unknown database 'whyapp'` | [database.sql](database.sql) belum dijalankan (Langkah 4) |
| `ModuleNotFoundError` | Virtual environment belum aktif atau library belum terpasang (Langkah 3) |
| Port 3001 sudah dipakai | Jalankan dengan port lain, misalnya `$env:PORT = "3002"` |
| Status DataChannel tidak pernah `open` | Kedua browser berada di jaringan yang memblokir koneksi P2P. Coba di satu komputer atau satu jaringan yang sama |
| Room sudah penuh | Room sudah berisi dua orang. Buat Room ID baru |

## Catatan keamanan

Aplikasi ini untuk pembelajaran, bukan untuk produksi.

- XOR dengan kunci berulang tidak setara dengan enkripsi modern seperti AES.
  Kuncinya adalah Room ID, yang juga terlihat di URL.
- Kolom `pesan` berisi frame bit dari pesan asli. Teks pesan dapat dibaca
  kembali dengan mengambil 8 bit DATA dari setiap frame.
- Siapa pun yang mengetahui Room ID dapat masuk ke room, tetapi hanya melihat
  riwayat pesan yang ia kirim atau terima sendiri.
- Session login disimpan di memori server dan hilang saat server dimatikan.
