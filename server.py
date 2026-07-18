import asyncio
import websockets
import json
import sqlite3
import hashlib
import http.server
import socketserver
import threading
import os

DB_PATH = "grim.db"
HTTP_PORT = int(os.environ.get("PORT", 10000))
WS_PORT = 8765

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, creator_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER, username TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

clients = {}

async def handler(websocket):
    user_id = None
    username = None
    try:
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            if action == "register":
                u, p = data["username"], hash_password(data["password"])
                try:
                    c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (u, p))
                    conn.commit()
                    await websocket.send(json.dumps({"status": "ok", "message": "Registered"}))
                except sqlite3.IntegrityError:
                    await websocket.send(json.dumps({"status": "error", "message": "Username taken"}))
            elif action == "login":
                u, p = data["username"], hash_password(data["password"])
                c.execute("SELECT id, username FROM users WHERE username=? AND password_hash=?", (u, p))
                row = c.fetchone()
                if row:
                    user_id, username = row[0], row[1]
                    clients[user_id] = websocket
                    await websocket.send(json.dumps({"status": "ok", "message": "Logged in", "user_id": user_id, "username": username}))
                else:
                    await websocket.send(json.dumps({"status": "error", "message": "Wrong credentials"}))
            elif action == "create_chat":
                c.execute("INSERT INTO chats (name, creator_id) VALUES (?, ?)", (data["name"], user_id))
                conn.commit()
                await websocket.send(json.dumps({"status": "ok", "chat_id": c.lastrowid, "name": data["name"]}))
            elif action == "get_chats":
                c.execute("SELECT id, name FROM chats")
                await websocket.send(json.dumps({"status": "ok", "chats": [{"id": r[0], "name": r[1]} for r in c.fetchall()]}))
            elif action == "send_message":
                c.execute("INSERT INTO messages (chat_id, user_id, username, content) VALUES (?, ?, ?, ?)", (data["chat_id"], user_id, username, data["content"]))
                conn.commit()
                msg = {"status": "ok", "action": "new_message", "chat_id": data["chat_id"], "username": username, "content": data["content"]}
                for uid, ws in clients.items():
                    if uid != user_id:
                        try: await ws.send(json.dumps(msg))
                        except: pass
                await websocket.send(json.dumps({"status": "ok"}))
            elif action == "get_history":
                c.execute("SELECT username, content, timestamp FROM messages WHERE chat_id=? ORDER BY timestamp ASC LIMIT 100", (data["chat_id"],))
                await websocket.send(json.dumps({"status": "ok", "messages": [{"username": r[0], "content": r[1], "timestamp": r[2]} for r in c.fetchall()]}))
            conn.close()
    except:
        pass
    finally:
        if user_id and user_id in clients:
            del clients[user_id]

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

def run_http():
    with socketserver.TCPServer(("0.0.0.0", HTTP_PORT), Handler) as httpd:
        httpd.serve_forever()

async def main():
    init_db()
    async with websockets.serve(handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()

threading.Thread(target=run_http, daemon=True).start()
asyncio.run(main())
