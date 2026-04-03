import os
import threading
import uvicorn
import customtkinter as ctk
import ctypes
import hashlib
import subprocess
import shutil
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# --- 1. 秘匿・システム設定 ---
BASE_SECRET_PATH = os.path.join(os.environ["LOCALAPPDATA"], "SystemNetworkData")
SECRET_DIR = os.path.join(BASE_SECRET_PATH, ".xl_vault_content")
PASS_FILE = os.path.join(BASE_SECRET_PATH, "vault.dat")
TAGS_FILE = os.path.join(BASE_SECRET_PATH, "tags.json")
THUMB_DIR = os.path.join(BASE_SECRET_PATH, ".thumbs")

def setup_secure_env():
    """必要なディレクトリとセキュリティ設定の初期化"""
    for d in [BASE_SECRET_PATH, SECRET_DIR, THUMB_DIR]:
        if not os.path.exists(d):
            os.makedirs(d)
    # 属性付与：隠し(2) + システム(4)
    ctypes.windll.kernel32.SetFileAttributesW(SECRET_DIR, 0x02 | 0x04)

setup_secure_env()

# --- 2. ユーティリティ ---
def load_tags():
    if not os.path.exists(TAGS_FILE): return {}
    try:
        with open(TAGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def save_tags(tags):
    with open(TAGS_FILE, "w", encoding="utf-8") as f:
        json.dump(tags, f, ensure_ascii=False, indent=2)

# --- 3. サーバー設定 (FastAPI) ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.state.unlocked = False

@app.get("/videos")
def list_videos():
    if not app.state.unlocked: return {"videos": []}
    return {"videos": [f for f in os.listdir(SECRET_DIR) if f.endswith(('.mp4', '.mkv', '.mov', '.avi', '.ts'))]}

@app.get("/stream/{video_name}")
async def stream_video(video_name: str, request: Request):
    if not app.state.unlocked: raise HTTPException(status_code=403)
    path = os.path.join(SECRET_DIR, video_name)
    if not os.path.exists(path): raise HTTPException(status_code=404)
    
    file_size = os.stat(path).st_size
    range_header = request.headers.get("range")
    start, end = 0, file_size - 1
    if range_header:
        range_str = range_header.replace("bytes=", "")
        parts = range_str.split("-")
        start = int(parts[0]); end = int(parts[1]) if parts[1] else file_size - 1

    def get_chunk():
        with open(path, "rb") as f:
            f.seek(start)
            yield f.read(end - start + 1)

    return StreamingResponse(get_chunk(), status_code=206, headers={
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Type": "video/mp4",
    })

@app.post("/upload")
async def upload_video(request: Request):
    if not app.state.unlocked: raise HTTPException(status_code=403)
    form = await request.form()
    file = form.get("file")
    if not file: raise HTTPException(status_code=400, detail="No file provided")
    save_path = os.path.join(SECRET_DIR, file.filename)
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"status": "ok", "filename": file.filename}

@app.get("/tags")
def get_tags():
    if not app.state.unlocked: raise HTTPException(status_code=403)
    return load_tags()

@app.post("/tags/{video_name}")
async def set_tags(video_name: str, request: Request):
    if not app.state.unlocked: raise HTTPException(status_code=403)
    body = await request.json()
    tags = load_tags()
    tags[video_name] = body.get("tags", [])
    save_tags(tags)
    return {"status": "ok"}

@app.get("/thumb/{video_name}")
def get_thumbnail(video_name: str):
    if not app.state.unlocked: raise HTTPException(status_code=403)
    thumb_path = os.path.join(THUMB_DIR, video_name + ".jpg")
    
    if not os.path.exists(thumb_path):
        video_path = os.path.join(SECRET_DIR, video_name)
        if not os.path.exists(video_path): raise HTTPException(status_code=404)
        try:
            # ffmpegを使用して1秒時点のフレームを抽出
            subprocess.run([
                "ffmpeg", "-i", video_path,
                "-ss", "00:00:01", "-vframes", "1",
                "-vf", "scale=320:-1", "-q:v", "5",
                thumb_path
            ], capture_output=True, timeout=30)
        except: raise HTTPException(status_code=500)
        
    if not os.path.exists(thumb_path): raise HTTPException(status_code=404)
    return FileResponse(thumb_path, media_type="image/jpeg")

# --- 4. UI (CustomTkinter) ---
ctk.set_appearance_mode("dark")

BG_MAIN, BG_CARD, BG_INPUT = "#080C18", "#0D1929", "#0A1220"
ACCENT, ACCENT_DIM = "#4A9EFF", "#1E3A5F"
TEXT_PRI, TEXT_SEC = "#E8F4FF", "#4A6080"
DANGER, SUCCESS = "#FF4A4A", "#4AFF9E"

class XLPressServer(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("XL Press Server")
        self.geometry("560x780")
        self.configure(fg_color=BG_MAIN)
        self.resizable(False, False)
        self.is_first_time = not os.path.exists(PASS_FILE)
        self._server_running = False
        self._build_ui()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="XL", font=("Arial Black", 28), text_color=TEXT_PRI).place(x=24, y=16)
        ctk.CTkLabel(header, text="Press Server", font=("Arial", 18), text_color=ACCENT).place(x=74, y=24)
        ctk.CTkLabel(header, text="v1.1.0", font=("Arial", 11), text_color=TEXT_SEC).place(x=24, y=52)

        ctk.CTkFrame(self, fg_color=ACCENT_DIM, height=1, corner_radius=0).pack(fill="x")
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=24, pady=20)

        # 認証カード
        auth_card = ctk.CTkFrame(main, fg_color=BG_CARD, corner_radius=12)
        auth_card.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(auth_card, text="AUTHENTICATION", font=("Arial", 11), text_color=TEXT_SEC).pack(anchor="w", padx=20, pady=(16, 4))
        self.guide_label = ctk.CTkLabel(auth_card, text="INITIALIZE" if self.is_first_time else "LOCKED", font=("Arial Black", 14), text_color=ACCENT if self.is_first_time else DANGER)
        self.guide_label.pack(anchor="w", padx=20, pady=(0, 12))
        self.pass_entry = ctk.CTkEntry(auth_card, placeholder_text="Password", show="*", height=44, corner_radius=8, fg_color=BG_INPUT, border_color=ACCENT_DIM, text_color=TEXT_PRI)
        self.pass_entry.pack(fill="x", padx=20, pady=(0, 12))
        self.pass_entry.bind("<Return>", lambda e: self.handle_password())
        self.action_btn = ctk.CTkButton(auth_card, text="INITIALIZE" if self.is_first_time else "UNLOCK", command=self.handle_password, height=44, corner_radius=8, fg_color=ACCENT, text_color="#000000", font=("Arial Black", 14))
        self.action_btn.pack(fill="x", padx=20, pady=(0, 16))

        # ステータス・リスト
        status_card = ctk.CTkFrame(main, fg_color=BG_CARD, corner_radius=12)
        status_card.pack(fill="x", pady=(0, 16))
        self.status_label = ctk.CTkLabel(status_card, text="● STANDBY", font=("Arial Black", 14), text_color=TEXT_SEC)
        self.status_label.pack(anchor="w", padx=20, pady=16)

        list_card = ctk.CTkFrame(main, fg_color=BG_CARD, corner_radius=12)
        list_card.pack(fill="x", pady=(0, 16))
        self.video_list = ctk.CTkTextbox(list_card, height=160, corner_radius=8, fg_color=BG_INPUT, border_color=ACCENT_DIM, font=("Consolas", 13), text_color=TEXT_PRI)
        self.video_list.pack(fill="x", padx=20, pady=16)
        self.video_list.insert("0.0", "  —  LOCKED  —"); self.video_list.configure(state="disabled")

        # 操作ボタン
        btn_row = ctk.CTkFrame(main, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 16))
        self.qr_btn = ctk.CTkButton(
            btn_row, text="Show QR",
            command=self._show_qr, state="disabled",
            height=40, corner_radius=8,
            fg_color=ACCENT_DIM, hover_color="#2A4A6F",
            text_color=TEXT_SEC, font=("Arial", 13)
        )
        self.qr_btn.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.open_btn = ctk.CTkButton(btn_row, text="Open Folder", command=self.open_folder, state="disabled", height=40, corner_radius=8, fg_color=ACCENT_DIM, text_color=TEXT_SEC, font=("Arial", 13))
        self.open_btn.grid(row=0, column=1, padx=3, sticky="ew")
        self.refresh_btn = ctk.CTkButton(btn_row, text="Refresh", command=self.refresh_list, state="disabled", height=40, corner_radius=8, fg_color=ACCENT_DIM, text_color=TEXT_SEC, font=("Arial", 13))
        self.refresh_btn.grid(row=0, column=2, padx=3, sticky="ew")
        self.change_dir_btn = ctk.CTkButton(btn_row, text="Change Dir", command=self.change_vault_dir, state="disabled", height=40, corner_radius=8, fg_color=ACCENT_DIM, text_color=TEXT_SEC, font=("Arial", 13))
        self.change_dir_btn.grid(row=0, column=3, padx=(6, 0), sticky="ew")
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)
        btn_row.columnconfigure(2, weight=1)
        btn_row.columnconfigure(3, weight=1)
        

        self.start_btn = ctk.CTkButton(main, text="START SERVER", command=self.start_server, state="disabled", height=60, corner_radius=10, fg_color=ACCENT_DIM, text_color=TEXT_SEC, font=("Arial Black", 18))
        self.start_btn.pack(fill="x")

        self.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))

    def hash_password(self, pwd): return hashlib.sha256(pwd.encode()).hexdigest()

    def handle_password(self):
        pwd = self.pass_entry.get()
        if not pwd: return
        if self.is_first_time:
            with open(PASS_FILE, "w") as f: f.write(self.hash_password(pwd))
            self.is_first_time = False
            self.guide_label.configure(text="RE-ENTER PASSWORD", text_color=ACCENT); self.action_btn.configure(text="UNLOCK"); self.pass_entry.delete(0, "end")
        else:
            with open(PASS_FILE, "r") as f: saved = f.read()
            if self.hash_password(pwd) == saved: self.unlock_success()
            else: self.status_label.configure(text="● AUTHENTICATION FAILED", text_color=DANGER)

    def unlock_success(self):
        app.state.unlocked = True
        self.guide_label.configure(text="ACCESS GRANTED", text_color=SUCCESS)
        self.status_label.configure(text="● READY", text_color=ACCENT)
        self.pass_entry.configure(state="disabled")
        self.action_btn.configure(state="disabled", fg_color=ACCENT_DIM)
        for b in [self.open_btn, self.refresh_btn, self.change_dir_btn, self.qr_btn]: b.configure(state="normal", text_color=TEXT_PRI)
        self.start_btn.configure(state="normal", fg_color=ACCENT, text_color="#000000")
        self.refresh_list()

    def open_folder(self):
        if app.state.unlocked: subprocess.Popen(f'explorer "{SECRET_DIR}"')

    def change_vault_dir(self):
        from tkinter import filedialog
        new_dir = filedialog.askdirectory()
        if new_dir:
            global SECRET_DIR; SECRET_DIR = new_dir
            self.refresh_list()

    def refresh_list(self):
        if not app.state.unlocked: return
        files = [f for f in os.listdir(SECRET_DIR) if f.endswith(('.mp4', '.mkv', '.mov', '.avi', '.ts'))]
        self.video_list.configure(state="normal"); self.video_list.delete("0.0", "end")
        if not files: self.video_list.insert("end", "  No files")
        else:
            for f in files: self.video_list.insert("end", f"  {f}\n")
        self.video_list.configure(state="disabled")

    def start_server(self):
        self.status_label.configure(text="BROADCASTING AT http://0.0.0.0:8000", text_color="#A6E22E")
        threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error"), daemon=True).start()
        self.start_button.configure(state="disabled", text="ENGINE ACTIVE", fg_color="#444444")
        self._show_qr()

    def _get_local_ip(self):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _show_qr(self):
        import qrcode
        from PIL import Image, ImageTk
        import tkinter as tk

        ip = self._get_local_ip()
        url = f"http://{ip}:8000"

        qr = qrcode.QRCode(version=1, box_size=6, border=3)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#4A9EFF", back_color="#0D1929")
        img = img.resize((200, 200), Image.LANCZOS)

        qr_window = tk.Toplevel(self)
        qr_window.title("QR Code")
        qr_window.configure(bg="#0D1929")
        qr_window.resizable(False, False)

        tk_img = ImageTk.PhotoImage(img)

        tk.Label(qr_window, text="スマホで読み取って接続",
                 font=("Arial", 13, "bold"),
                 fg="#4A9EFF", bg="#0D1929").pack(pady=(16, 4))

        tk.Label(qr_window, image=tk_img, bg="#0D1929").pack(padx=20)
        qr_window.tk_img = tk_img

        tk.Label(qr_window, text=url,
                 font=("Consolas", 13, "bold"),
                 fg="#A6E22E", bg="#0D1929").pack(pady=(8, 4))

        tk.Label(qr_window, text="XL PressのPCタブで読み取れます",
                 font=("Arial", 10),
                 fg="#4A6080", bg="#0D1929").pack(pady=(0, 16))

        tk.Button(qr_window, text="閉じる",
                  command=qr_window.destroy,
                  bg="#333333", fg="white",
                  font=("Arial", 11),
                  relief="flat", padx=20, pady=6).pack(pady=(0, 16))

if __name__ == "__main__":
    gui = XLPressServer()
    gui.mainloop()