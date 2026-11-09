// Semua kode browser ada di file ini agar mudah diikuti.

const app = document.querySelector("#app");
const roomPattern = /^[A-Z0-9-]{4,32}$/;
const roomAlphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const SIGNAL_BIT_WIDTH = 34;

let username = "";
let closeActiveRoom = null;

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[character]));
}

function normalizeRoomId(value) {
  return String(value || "").trim().toUpperCase().replace(/\s+/g, "");
}

function createRoomId() {
  const randomBytes = crypto.getRandomValues(new Uint8Array(8));
  let result = "";

  randomBytes.forEach((value, index) => {
    result += roomAlphabet[value % roomAlphabet.length];
    if (index === 3) result += "-";
  });

  return result;
}

function createMessageId() {
  return `${Date.now()}-${Math.random()}`;
}

// XOR bekerja pada byte UTF-8 sehingga emoji juga dapat diproses.
function xorBytes(bytes, key) {
  const keyBytes = new TextEncoder().encode(key);
  const result = new Uint8Array(bytes.length);

  bytes.forEach((value, index) => {
    result[index] = value ^ keyBytes[index % keyBytes.length];
  });

  return result;
}

function encrypt(text, roomId) {
  return xorBytes(new TextEncoder().encode(text), roomId);
}

function decryptBytes(bytes, roomId) {
  return xorBytes(bytes, roomId);
}

function decrypt(bytes, roomId) {
  return new TextDecoder().decode(decryptBytes(bytes, roomId));
}

function bytesToBase64(bytes) {
  return btoa(String.fromCharCode(...bytes));
}

function base64ToBytes(value) {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

function bytesToBinary(bytes) {
  return [...bytes]
    .map((value) => value.toString(2).padStart(8, "0"))
    .join("");
}

function bytesToHex(bytes) {
  return [...bytes]
    .map((value) => value.toString(16).padStart(2, "0").toUpperCase())
    .join(" ");
}

function createSignalFrame(bytes) {
  const dataBits = bytesToBinary(bytes);
  const byteBits = dataBits.match(/.{8}/g) || [];
  const frames = byteBits.map((byte) => {
    const parityBit = [...byte].filter((bit) => bit === "1").length % 2 === 0 ? "0" : "1";
    const startBit = "1";
    const endBit = byte[7] === "1" ? "0" : "1";

    return {
      bits: `${startBit}${byte}${parityBit}${endBit}`,
      labels: [
        { name: "START", value: startBit, width: SIGNAL_BIT_WIDTH },
        { name: "DATA", value: "8 bit", width: 8 * SIGNAL_BIT_WIDTH },
        { name: "PARITY", value: parityBit, width: SIGNAL_BIT_WIDTH },
        { name: "END", value: endBit, width: SIGNAL_BIT_WIDTH },
      ],
    };
  });
  const bits = frames.map((frame) => frame.bits).join("");

  return {
    bits,
    labels: frames.flatMap((frame) => frame.labels),
    dataBits,
  };
}

function encodeStoredMessage(bytes) {
  const { bits } = createSignalFrame(bytes);
  let level = 0;
  let encoded = "";
  for (const bit of bits) {
    if (bit === "0") level ^= 1;
    encoded += level;
    level ^= 1;
    encoded += level;
  }
  return `dm3:${encoded}`;
}

function decodeStoredMessage(encoded) {
  const fixedStartFrame = encoded.startsWith("dm3:");
  const previousPerByteFrame = encoded.startsWith("dm2:");
  const perByteFrame = fixedStartFrame || previousPerByteFrame;
  const levels = encoded.startsWith("dm1:") || perByteFrame ? encoded.slice(4) : encoded;
  if (!/^(?:01|10)+$/.test(levels)) throw new Error("Encoding tidak valid.");
  let previous = 0;
  let bits = "";
  for (let index = 0; index < levels.length; index += 2) {
    bits += Number(levels[index]) === previous ? "1" : "0";
    previous = Number(levels[index + 1]);
  }
  let bytes;
  if (perByteFrame) {
    if (!bits.length || bits.length % 11 !== 0) throw new Error("Frame tidak valid.");
    bytes = Uint8Array.from(bits.match(/.{11}/g), (frame) => parseInt(frame.slice(1, 9), 2));
    const validBits = fixedStartFrame
      ? createSignalFrame(bytes).bits
      : [...bytes].map((byte) => {
        const data = byte.toString(2).padStart(8, "0");
        const parity = [...data].filter((bit) => bit === "1").length % 2 === 0 ? "0" : "1";
        const start = data[0] === "1" ? "0" : "1";
        const end = data[7] === "1" ? "0" : "1";
        return `${start}${data}${parity}${end}`;
      }).join("");
    if (validBits !== bits) {
      throw new Error("Parity atau batas frame tidak valid.");
    }
  } else {
    const dataBits = bits.slice(1, -2);
    if (!dataBits.length || dataBits.length % 8 !== 0) throw new Error("Frame tidak valid.");
    bytes = Uint8Array.from(dataBits.match(/.{8}/g), (byte) => parseInt(byte, 2));
    const legacyBits = [...bytes].map((byte) => byte.toString(2).padStart(8, "0")).join("");
    const numberOfOnes = [...legacyBits].filter((bit) => bit === "1").length;
    const legacyFrame = `${legacyBits[0] === "1" ? "0" : "1"}${legacyBits}${numberOfOnes % 2 === 0 ? "0" : "1"}${legacyBits[legacyBits.length - 1] === "1" ? "0" : "1"}`;
    if (legacyFrame !== bits) throw new Error("Parity atau batas frame tidak valid.");
  }
  return bytes;
}

function createSignalImage(frameBits) {
  // Satu bit memiliki dua bagian. Setiap bit selalu berganti level di tengah.
  const bitWidth = SIGNAL_BIT_WIDTH;
  const leftMargin = 30;
  const signalWidth = frameBits.length * bitWidth;
  const signalEnd = leftMargin + signalWidth;
  const imageWidth = signalEnd + 1;
  const high = 43;
  const low = 93;
  let level = 0;
  let path = `M ${leftMargin} ${level ? high : low}`;
  let bitLabels = "";

  frameBits.split("").forEach((bit, index) => {
    const left = leftMargin + index * bitWidth;
    const middle = left + bitWidth / 2;
    const right = left + bitWidth;

    // Differential Manchester: bit 0 berubah di awal, bit 1 tidak.
    if (bit === "0") {
      level ^= 1;
      path += ` L ${left} ${level ? high : low}`;
    }

    path += ` L ${middle} ${level ? high : low}`;
    level ^= 1;
    path += ` L ${middle} ${level ? high : low} L ${right} ${level ? high : low}`;

    bitLabels += `
      <text x="${left + bitWidth / 2}" y="18" text-anchor="middle">${bit}</text>
      <line x1="${left}" y1="27" x2="${left}" y2="104" class="grid"/>`;
  });

  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${imageWidth}" height="120"
         viewBox="0 0 ${imageWidth} 120">
      <style>
        text { font: 12px system-ui, sans-serif; fill: #f2c8f5; }
        .level { font-weight: bold; }
        .grid { stroke: #d99ae155; stroke-dasharray: 3 3; }
        .guide { stroke: #d99ae133; stroke-dasharray: 2 4; }
        .signal { stroke: #f8d8fa; stroke-width: 3; stroke-linejoin: round; }
      </style>
      <rect width="100%" height="100%" fill="#61006f"/>
      <text x="8" y="48" class="level">H</text>
      <text x="8" y="98" class="level">L</text>
      <line x1="${leftMargin}" y1="${high}" x2="${imageWidth}" y2="${high}" class="guide"/>
      <line x1="${leftMargin}" y1="${low}" x2="${imageWidth}" y2="${low}" class="guide"/>
      ${bitLabels}
      <line x1="${signalEnd}" y1="27" x2="${signalEnd}" y2="104" class="grid"/>
      <path d="${path}" class="signal" fill="none"/>
    </svg>`;

  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

function navigation(activePage) {
  return `
    <header class="navigation">
      <div class="navigation-inner">
        <a href="#/home">P2P Chat</a>
        <nav>
          <a href="#/home">Beranda</a>
          <a href="#/profile">Profil</a>
        </nav>
      </div>
    </header>`;
}

async function api(path, options = {}) {
  const requestOptions = { credentials: "include", ...options };
  const headers = { ...requestOptions.headers };
  if (requestOptions.body) headers["Content-Type"] = "application/json";

  const response = await fetch(path, {
    ...requestOptions,
    headers,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "Permintaan gagal.");
  return data;
}

function showEntryPage(mode = "login", message = "") {
  const isLogin = mode === "login";
  app.innerHTML = `
    <main class="center">
      <section class="card small-card">
        <div class="logo">P2P</div>
        <h1>${isLogin ? "Masuk" : "Daftar"} ke P2P Chat</h1>
        <p class="muted">Pesan dikirim langsung antar-browser melalui WebRTC.</p>
        <form id="auth-form" class="form">
          <label>
            Username
            <input id="username-input" maxlength="100" required autofocus>
          </label>
          <label>
            Password
            <input id="password-input" type="password" minlength="8" maxlength="72" required>
          </label>
          <div id="auth-error" class="error">${escapeHtml(message)}</div>
          <button type="submit">${isLogin ? "Masuk" : "Daftar"}</button>
        </form>
        <p class="muted">${isLogin ? "Belum punya akun?" : "Sudah punya akun?"}
          <a href="#/${isLogin ? "register" : "login"}">${isLogin ? "Daftar" : "Masuk"}</a>
        </p>
      </section>
    </main>`;

  document.querySelector("#auth-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = document.querySelector("#auth-error");
    try {
      const data = await api(`/api/${isLogin ? "login" : "register"}`, {
        method: "POST",
        body: JSON.stringify({
          username: document.querySelector("#username-input").value.trim(),
          password: document.querySelector("#password-input").value,
        }),
      });
      username = data.username;
      location.hash = "#/home";
    } catch (requestError) {
      error.textContent = requestError.message;
    }
  });
}

function showHomePage() {
  app.innerHTML = `
    ${navigation("home")}
    <main class="content">
      <h1>Selamat datang, ${escapeHtml(username)}!</h1>
      <p class="muted">Satu room dapat digunakan oleh maksimal dua orang.</p>
      <div class="columns">
        <section class="card">
          <h2>Buat room baru</h2>
          <p class="muted">Room ID juga menjadi kunci XOR.</p>
          <button id="generate-room">Buat Room ID</button>
          <div id="new-room"></div>
        </section>
        <section class="card">
          <h2>Gabung ke room</h2>
          <form id="join-form" class="form">
            <input id="room-input" maxlength="32" placeholder="Contoh: ABCD-2345">
            <div id="join-error" class="error"></div>
            <button type="submit">Gabung</button>
          </form>
        </section>
      </div>
    </main>`;

  document.querySelector("#generate-room").addEventListener("click", () => {
    const newRoom = createRoomId();
    document.querySelector("#new-room").innerHTML = `
      <p><code>${newRoom}</code></p>
      <button id="open-room" class="secondary">Masuk ke room</button>`;
    document.querySelector("#open-room").addEventListener("click", () => {
      location.hash = `#/room/${newRoom}`;
    });
  });

  document.querySelector("#join-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const roomId = normalizeRoomId(document.querySelector("#room-input").value);
    const error = document.querySelector("#join-error");

    if (!roomPattern.test(roomId)) {
      error.textContent = "Room ID harus 4-32 karakter.";
      return;
    }

    location.hash = `#/room/${roomId}`;
  });
}

function showProfilePage() {
  app.innerHTML = `
    ${navigation("profile")}
    <main class="content">
      <section class="card small-card">
        <div class="logo">${escapeHtml(username[0].toUpperCase())}</div>
        <p class="muted">USERNAME</p>
        <h1>${escapeHtml(username)}</h1>
        <button id="logout">Reset / Keluar</button>
      </section>
    </main>`;

  document.querySelector("#logout").addEventListener("click", () => {
    localStorage.removeItem("username");
    username = "";
    location.hash = "";
  });
}

function statusLabel(name, value) {
  const goodValues = ["connected", "open", "completed"];
  const badValues = ["failed", "error", "closed", "room-full", "disconnected"];
  const className = goodValues.includes(value) ? "good" : badValues.includes(value) ? "bad" : "";
  return `<span class="${className}">${name}: ${value}</span>`;
}

function showRoomPage(roomId) {
  app.innerHTML = `
    <div class="room">
      <header class="room-header">
        <div class="room-header-inner">
          <a href="#/home" id="back-home">← Beranda</a>
          <h1>Room <code>${roomId}</code></h1>
          <div class="muted">Kamu: ${escapeHtml(username)} · Lawan: <b id="peer-name">menunggu...</b></div>
          <div id="statuses" class="status"></div>
          <div id="room-error" class="error"></div>
        </div>
      </header>
      <main id="messages" class="messages"></main>
      <footer class="composer">
        <form id="message-form">
          <input id="message-input" disabled placeholder="Menunggu koneksi P2P...">
          <button disabled>Kirim</button>
        </form>
      </footer>
    </div>`;

  closeActiveRoom = startWebRTC(roomId);

  document.querySelector("#back-home").addEventListener("click", (event) => {
    event.preventDefault();

    // Putuskan session room sebelum berpindah ke halaman beranda.
    closeActiveRoom?.();
    closeActiveRoom = null;
    location.hash = "#/home";
  });
}

function startWebRTC(roomId) {
  const socket = io();
  const statuses = { signaling: "connecting", peer: "waiting", ice: "new", channel: "closed" };
  const messages = document.querySelector("#messages");
  const input = document.querySelector("#message-input");
  const sendButton = document.querySelector("#message-form button");
  let peerConnection = null;
  let dataChannel = null;
  let remoteSocketId = null;
  let waitingCandidates = [];
  let isClosed = false;

  function updateStatus() {
    document.querySelector("#statuses").innerHTML = [
      statusLabel("Signaling", statuses.signaling),
      statusLabel("Peer", statuses.peer),
      statusLabel("ICE", statuses.ice),
      statusLabel("DataChannel", statuses.channel),
    ].join("");

    const ready = statuses.channel === "open";
    input.disabled = !ready;
    sendButton.disabled = !ready;
  }

  function showSystemMessage(text) {
    messages.insertAdjacentHTML("beforeend", `<div class="system">${escapeHtml(text)}</div>`);
  }

  function showChatMessage(text, dataBytes, sender, outgoing, timestamp) {
    const frames = [...dataBytes].map(createSignalFrame);
    const totalBits = frames.reduce((total, frame) => total + frame.bits.length, 0);
    const signalBits = frames.map((frame) => frame.bits).join("");
    messages.insertAdjacentHTML("beforeend", `
      <article class="message ${outgoing ? "outgoing" : ""}">
        <div class="meta">${escapeHtml(sender)} · ${new Date(timestamp).toLocaleTimeString("id-ID")}</div>
        <div class="bubble">${escapeHtml(text)}</div>
          <div class="signal-card">
            <div class="signal-title">
              DIFFERENTIAL MANCHESTER · EVEN PARITY
              <span>${frames.length} FRAME · ${totalBits} BIT</span>
            </div>
            <div class="signal-scroll">
              <div class="signal-track">
                <div class="signal-frame-headings">
                  ${frames.map((frame, index) => `
                    <span class="signal-frame-heading" style="width:${frame.bits.length * SIGNAL_BIT_WIDTH}px">
                      FRAME ${index + 1} · BYTE ${frame.byte.toString(16).padStart(2, "0").toUpperCase()}
                    </span>`).join("")}
                </div>
                <div class="signal-labels">
                  ${frames.map((frame) => frame.labels.map((label) => `
                    <span class="signal-label ${label.name.toLowerCase()}" style="width:${label.width}px">
                      ${label.name}<b>${label.value}</b>
                    </span>`).join("")).join("")}
                </div>
                <img class="signal-image"
                     src="${createSignalImage(signalBits)}"
                     alt="Sinyal Differential Manchester ${frames.length} frame">
              </div>
            </div>
            <div class="signal-help">
              Setiap byte UTF-8 = START + 8 bit DATA + PARITY genap + END.
              START/END adalah kebalikan bit pertama/terakhir DATA.
              Garis putus-putus menandai akhir sinyal.
            </div>
          </div>
          <details>
            <summary class="muted">Lihat data UTF-8</summary>
            <small>
              HEX: ${bytesToHex(dataBytes)}<br>
              DATA: ${frames.map((frame) => frame.dataBits).join(" ")}<br>
              FRAME:<br>
              ${frames.map((frame, index) => `${index + 1}: ${frame.bits}`).join("<br>")}
            </small>
          </details>
        </article>`);
    messages.scrollTop = messages.scrollHeight;
  }

  function setupDataChannel(channel) {
    dataChannel = channel;
    statuses.channel = channel.readyState;
    updateStatus();

    channel.onopen = () => {
      statuses.channel = "open";
      updateStatus();
      showSystemMessage("DataChannel terbuka. Pesan dikirim langsung.");
      channel.send(JSON.stringify({ type: "hello", username }));
    };

    channel.onclose = () => {
      statuses.channel = "closed";
      updateStatus();
    };

    channel.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "hello") {
        document.querySelector("#peer-name").textContent = message.username;
      }
      if (message.type === "chat") {
        const bytes = base64ToBytes(message.cipher);
        const dataBytes = decryptBytes(bytes, roomId);
        showChatMessage(
          decrypt(bytes, roomId),
          dataBytes,
          message.sender,
          false,
          message.timestamp,
        );
      }
    };
  }

  function createPeerConnection(peerId) {
    peerConnection?.close();
    remoteSocketId = peerId;
    waitingCandidates = [];

    peerConnection = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });

    peerConnection.onicecandidate = (event) => {
      if (event.candidate) {
        socket.emit("ice-candidate", {
          to: peerId,
          candidate: event.candidate.toJSON(),
        });
      }
    };

    peerConnection.onconnectionstatechange = () => {
      statuses.peer = peerConnection.connectionState;
      updateStatus();
    };

    peerConnection.oniceconnectionstatechange = () => {
      statuses.ice = peerConnection.iceConnectionState;
      updateStatus();
    };

    peerConnection.ondatachannel = (event) => setupDataChannel(event.channel);
    statuses.peer = "new";
    updateStatus();
    return peerConnection;
  }

  async function addWaitingCandidates() {
    for (const candidate of waitingCandidates) {
      await peerConnection.addIceCandidate(candidate);
    }
    waitingCandidates = [];
  }

  socket.on("connect", () => {
    statuses.signaling = "connected";
    updateStatus();
    socket.emit("join-room", { roomId, username });
  });

  socket.on("connect_error", () => {
    statuses.signaling = "error";
    document.querySelector("#room-error").textContent = "Gagal terhubung ke server.";
    updateStatus();
  });

  socket.on("room-full", () => {
    statuses.peer = "room-full";
    document.querySelector("#room-error").textContent = "Room sudah penuh.";
    updateStatus();
  });

  socket.on("peer-joined", async ({ socketId, username: peerName }) => {
    document.querySelector("#peer-name").textContent = peerName;
    const connection = createPeerConnection(socketId);
    setupDataChannel(connection.createDataChannel("chat"));
    await connection.setLocalDescription(await connection.createOffer());
    socket.emit("offer", { to: socketId, sdp: connection.localDescription.toJSON() });
  });

  socket.on("offer", async ({ from, sdp, username: peerName }) => {
    document.querySelector("#peer-name").textContent = peerName;
    const connection = createPeerConnection(from);
    await connection.setRemoteDescription(sdp);
    await addWaitingCandidates();
    await connection.setLocalDescription(await connection.createAnswer());
    socket.emit("answer", { to: from, sdp: connection.localDescription.toJSON() });
  });

  socket.on("answer", async ({ from, sdp }) => {
    if (peerConnection && remoteSocketId === from) {
      await peerConnection.setRemoteDescription(sdp);
      await addWaitingCandidates();
    }
  });

  socket.on("ice-candidate", async ({ from, candidate }) => {
    if (!peerConnection || remoteSocketId !== from) return;
    if (!peerConnection.remoteDescription) {
      waitingCandidates.push(candidate);
      return;
    }
    await peerConnection.addIceCandidate(candidate);
  });

  socket.on("peer-left", ({ username: peerName }) => {
    peerConnection?.close();
    statuses.peer = "waiting";
    statuses.channel = "closed";
    document.querySelector("#peer-name").textContent = "menunggu...";
    showSystemMessage(`${peerName || "Lawan bicara"} keluar dari room.`);
    updateStatus();
  });

  function closeRoom() {
    if (isClosed) return;
    isClosed = true;

    // Beri tahu server sebelum memutus Socket.IO.
    socket.emit("leave-room");
    socket.removeAllListeners();
    socket.disconnect();

    dataChannel?.close();
    peerConnection?.close();
    dataChannel = null;
    peerConnection = null;
    remoteSocketId = null;
    waitingCandidates = [];
  }

  document.querySelector("#message-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || !dataChannel || dataChannel.readyState !== "open") return;

    const bytes = encrypt(text, roomId);
    const dataBytes = new TextEncoder().encode(text);
    const message = {
      type: "chat",
      sender: username,
      cipher: bytesToBase64(bytes),
      timestamp: Date.now(),
    };

    dataChannel.send(JSON.stringify(message));
    showChatMessage(text, dataBytes, username, true, message.timestamp);
    input.value = "";
  });

  updateStatus();
  return closeRoom;
}

function routePage() {
  const parts = location.hash.slice(2).split("/");

  // Route lama harus dibersihkan sebelum halaman baru dibuat.
  closeActiveRoom?.();
  closeActiveRoom = null;

  if (!username) {
    showEntryPage();
    return;
  }

  if (parts[0] === "profile") {
    showProfilePage();
  } else if (parts[0] === "room" && roomPattern.test(normalizeRoomId(parts[1]))) {
    showRoomPage(normalizeRoomId(parts[1]));
  } else {
    showHomePage();
  }
}

window.addEventListener("hashchange", routePage);
window.addEventListener("pagehide", () => closeActiveRoom?.());
routePage();
