CREATE DATABASE IF NOT EXISTS whyapp
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE whyapp;

CREATE TABLE IF NOT EXISTS pengguna (
    user_id CHAR(36) PRIMARY KEY,
    nama_pengguna VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(60) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS room (
    room_id VARCHAR(32) PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat (
    id_chat BIGINT AUTO_INCREMENT PRIMARY KEY,
    room_id VARCHAR(32) NOT NULL,
    user_id CHAR(36) NOT NULL,
    pesan TEXT NOT NULL,
    waktu_kirim TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_chat_room
        FOREIGN KEY (room_id) REFERENCES room(room_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_chat_pengguna
        FOREIGN KEY (user_id) REFERENCES pengguna(user_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    INDEX idx_chat_room_time (room_id, waktu_kirim)
);

-- Password dummy berikut menggunakan format bcrypt.
INSERT INTO pengguna (user_id, nama_pengguna, password) VALUES
    ('11111111-1111-1111-1111-111111111111', 'alice', '$2b$12$4hLz27wsKIzcv99ro4adhuBXrC9RV9ciL5Zi/OywI71vdNHrDVkha'),
    ('22222222-2222-2222-2222-222222222222', 'bob', '$2b$12$4hLz27wsKIzcv99ro4adhuBXrC9RV9ciL5Zi/OywI71vdNHrDVkha')
ON DUPLICATE KEY UPDATE nama_pengguna = VALUES(nama_pengguna);

INSERT INTO room (room_id) VALUES ('DEMO')
ON DUPLICATE KEY UPDATE room_id = VALUES(room_id);
