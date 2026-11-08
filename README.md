# Chat P2P Python untuk Pemula

Contoh aplikasi chat sederhana. Pesan dikirim langsung antar-browser memakai
WebRTC DataChannel. Python hanya membantu proses awal koneksi.

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

## 2. Menjalankan

```bash
python app.py
```

Buka <http://localhost:3001> di browser.

## 3. Mencoba chat

1. Masukkan nama.
2. Klik **Buat Room ID**.
3. Buka alamat yang sama di browser kedua atau mode incognito.
4. Masukkan Room ID tadi.
5. Tunggu status **DataChannel: open**.
6. Kirim pesan.

Gunakan dua browser berbeda karena nama disimpan di `localStorage` browser.

## 4. Penjelasan folder

```text
app.py                 server Python dan signaling Socket.IO
requirements.txt       daftar library Python
static/index.html      halaman HTML awal
static/style.css       tampilan aplikasi
static/app.js          halaman, WebRTC, dan enkripsi XOR
```

## Catatan keamanan

XOR digunakan untuk pembelajaran, bukan untuk aplikasi produksi. XOR dengan
kunci berulang tidak setara dengan enkripsi modern seperti AES.
