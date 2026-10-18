import os
import sys
import re
import json
import uuid
import shutil
import platform
import subprocess
import threading
import urllib.request
import ctypes
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from google import genai
from google.genai import types

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ================= ПУТИ, ИКОНКА И ПАПКА ПРОЕКТА =================
def get_base_dir() -> str:
    """Папка рядом со скриптом (.py) или с .exe (PyInstaller)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

SCRIPT_DIR = get_base_dir()
ICON_PATH = os.path.join(SCRIPT_DIR, "PyCodex.ico")
DATA_FILE = os.path.join(SCRIPT_DIR, "pycodex_data.json")

# Все относительные пути инструментов ИИ будут считаться от папки проекта
try:
    os.chdir(SCRIPT_DIR)
except Exception:
    pass

# ================= 1. ВШИТЫЙ БАЗОВЫЙ СИСТЕМНЫЙ ПРОМПТ =================
CORE_SYSTEM_PROMPT = (
    "Ты PyCodex — автономный ИИ-разработчик нового поколения с доступом к системе.\n"
    "У тебя есть 12 системных инструментов:\n"
    "1. run_shell_command — запуск команд терминала.\n"
    "2. write_file — создание/перезапись файлов.\n"
    "3. read_file — чтение файлов с пагинацией.\n"
    "4. replace_in_file — точечная замена участков кода.\n"
    "5. list_directory — просмотр структуры директорий.\n"
    "6. search_in_files — поиск кода/текста внутри проекта.\n"
    "7. file_exists — проверка наличия путей.\n"
    "8. delete_path — удаление файлов/каталогов.\n"
    "9. copy_move_path — копирование/перемещение файлов.\n"
    "10. get_system_info — информация об ОС, Python и ресурсах.\n"
    "11. download_url — скачивание файлов из сети.\n"
    "12. fetch_web_page — получение текста из веб-страниц/документации.\n\n"
    "ПРАВИЛА ОФОРМЛЕНИЯ ТЕКСТА:\n"
    "- НЕ используй спецсимволы Markdown в обычном тексте: ЗАПРЕЩЕНЫ двойные звёздочки **, решётки ### для заголовков, косые кавычки ` для выделения слов.\n"
    "- Пиши чистым, аккуратным человеческим текстом.\n"
    "- Списки оформляй простым дефисом (- Пункт), а не звёздочками (* Пункт).\n"
    "- Блоки кода оформляй только если действительно передаешь код.\n"
    "- Для точечных правок используй replace_in_file вместо перезаписи файлов целиком."
)

DEFAULT_CUSTOM_PROMPT = "Отвечай на русском языке. Пиши понятно и кратко."

MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite"
]

# ================= ОЧИСТКА И ФОРМАТИРОВАНИЕ ТЕКСТА =================

def clean_markdown(text: str) -> str:
    if not text:
        return ""
    parts = text.split("```")
    for i in range(0, len(parts), 2):
        s = parts[i]
        s = re.sub(r'\*\*(.*?)\*\*', r'\1', s)
        s = re.sub(r'__(.*?)__', r'\1', s)
        s = re.sub(r'(?m)^#{1,6}\s*', '', s)
        s = re.sub(r'(?m)^\s*\*\s+', '• ', s)
        s = re.sub(r'`(.*?)`', r'\1', s)
        s = s.replace("**", "").replace("*", "")
        parts[i] = s
    return "```".join(parts)

# ================= 12 ИНСТРУМЕНТОВ =================

def run_shell_command(command: str) -> str:
    try:
        res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
        return f"[Код выхода: {res.returncode}]\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}".strip()
    except Exception as e:
        return f"Ошибка команды: {str(e)}"

def write_file(filepath: str, content: str) -> str:
    try:
        dir_name = os.path.dirname(filepath)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Файл '{filepath}' успешно сохранен ({len(content)} символов)."
    except Exception as e:
        return f"Ошибка записи: {str(e)}"

def read_file(filepath: str, offset_lines: int = 0, limit_lines: int = 200) -> str:
    try:
        if not os.path.exists(filepath):
            return f"Ошибка: файл '{filepath}' не найден."
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        selected = lines[offset_lines : offset_lines + limit_lines]
        total = len(lines)
        body = "".join(selected)
        return f"[Строки {offset_lines+1}-{min(offset_lines+limit_lines, total)} из {total}]\n{body}"
    except Exception as e:
        return f"Ошибка чтения: {str(e)}"

def replace_in_file(filepath: str, target_block: str, replacement_block: str) -> str:
    try:
        if not os.path.exists(filepath):
            return f"Ошибка: файл '{filepath}' не существует."
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if target_block not in content:
            return "Ошибка: target_block не найден в содержимом файла."
        updated = content.replace(target_block, replacement_block, 1)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(updated)
        return f"Файл '{filepath}' успешно обновлен."
    except Exception as e:
        return f"Ошибка модификации: {str(e)}"

def list_directory(dirpath: str = ".") -> str:
    try:
        if not os.path.exists(dirpath):
            return f"Ошибка: директория '{dirpath}' не существует."
        items = os.listdir(dirpath)
        out = []
        for it in sorted(items):
            p = os.path.join(dirpath, it)
            if os.path.isdir(p):
                out.append(f"[DIR]  {it}/")
            else:
                sz = os.path.getsize(p)
                out.append(f"[FILE] {it} ({sz} bytes)")
        return "\n".join(out) if out else "(директория пуста)"
    except Exception as e:
        return f"Ошибка обзора директории: {str(e)}"

def search_in_files(query: str, root_dir: str = ".", max_results: int = 15) -> str:
    try:
        matches = []
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv", "__pycache__", "build", "dist")]
            for file in files:
                p = os.path.join(root, file)
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            if query.lower() in line.lower():
                                matches.append(f"{p}:{line_num}: {line.strip()[:150]}")
                                if len(matches) >= max_results:
                                    return "\n".join(matches) + f"\n... (показаны первые {max_results} совпадений)"
                except Exception:
                    continue
        return "\n".join(matches) if matches else f"Совпадений для '{query}' не найдено."
    except Exception as e:
        return f"Ошибка поиска: {str(e)}"

def file_exists(path: str) -> str:
    if os.path.exists(path):
        t = "Папка (DIR)" if os.path.isdir(path) else "Файл (FILE)"
        return f"Существует. Тип: {t}, Путь: {os.path.abspath(path)}"
    return f"Путь '{path}' НЕ существует."

def delete_path(path: str) -> str:
    try:
        if not os.path.exists(path):
            return f"Ошибка: '{path}' не существует."
        if os.path.isdir(path):
            shutil.rmtree(path)
            return f"Директория '{path}' со всем содержимым успешно удалена."
        else:
            os.remove(path)
            return f"Файл '{path}' успешно удален."
    except Exception as e:
        return f"Ошибка удаления: {str(e)}"

def copy_move_path(src: str, dst: str, operation: str = "copy") -> str:
    try:
        if not os.path.exists(src):
            return f"Ошибка: источник '{src}' не существует."
        if operation == "move":
            shutil.move(src, dst)
            return f"Успешно перемещено из '{src}' в '{dst}'."
        else:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            return f"Успешно скопировано из '{src}' в '{dst}'."
    except Exception as e:
        return f"Ошибка операции: {str(e)}"

def get_system_info() -> str:
    try:
        return (
            f"OS: {platform.system()} {platform.release()} ({platform.architecture()[0]})\n"
            f"Python: {sys.version.split()[0]}\n"
            f"Current Workdir: {os.getcwd()}\n"
            f"User: {os.getlogin() if hasattr(os, 'getlogin') else 'unknown'}"
        )
    except Exception as e:
        return f"Ошибка инфо: {str(e)}"

def download_url(url: str, save_path: str) -> str:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (PyCodex-Agent)'})
        with urllib.request.urlopen(req, timeout=30) as resp, open(save_path, 'wb') as out_f:
            shutil.copyfileobj(resp, out_f)
        return f"Файл успешно скачан из {url} и сохранен в '{save_path}'."
    except Exception as e:
        return f"Ошибка скачивания: {str(e)}"

def fetch_web_page(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (PyCodex-Agent)'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode('utf-8', errors='ignore')
        return raw[:4000] + ("\n... [Обрезано]" if len(raw) > 4000 else "")
    except Exception as e:
        return f"Ошибка загрузки веб-страницы: {str(e)}"

ALL_TOOLS = [
    run_shell_command, write_file, read_file, replace_in_file,
    list_directory, search_in_files, file_exists, delete_path,
    copy_move_path, get_system_info, download_url, fetch_web_page
]
TOOLS_DICT = {fn.__name__: fn for fn in ALL_TOOLS}

# ================= ХРАНИЛИЩЕ ДАННЫХ =================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "settings": {
                "api_key": "",
                "model": "gemini-3.8-flash",
                "custom_prompt": DEFAULT_CUSTOM_PROMPT,
                "mode": "Default"
            },
            "chats": []
        }
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "system_prompt" in data.get("settings", {}):
                data["settings"]["custom_prompt"] = data["settings"].pop("system_prompt")
            if data.get("settings", {}).get("model") not in MODELS:
                data["settings"]["model"] = "gemini-3.8-flash"
            if "custom_prompt" not in data.get("settings", {}):
                data["settings"]["custom_prompt"] = DEFAULT_CUSTOM_PROMPT
            return data
    except Exception:
        return {
            "settings": {
                "api_key": "",
                "model": "gemini-3.8-flash",
                "custom_prompt": DEFAULT_CUSTOM_PROMPT,
                "mode": "Default"
            },
            "chats": []
        }

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ================= ГРАФИЧЕСКИЙ ИНТЕРФЕЙС =================

class PyCodex(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PyCodex")
        self.geometry("1100x750")
        self.minsize(900, 600)
        self.configure(fg_color="#2b2b2b")

        self.data = load_data()
        self.current_chat_id = None
        self.attached_file_path = None
        self.is_generating = False

        self._set_icon()
        self._build_ui()
        self._load_chats_to_sidebar()

    def _set_icon(self):
        # 1. Windows: свой AppUserModelID, иначе панель задач покажет иконку python.exe
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PyCodex.App.1.0")
        except Exception:
            pass

        if not os.path.exists(ICON_PATH):
            print(f"Внимание: иконка не найдена по пути {ICON_PATH}")
            return

        # 2. Иконка заголовка окна и Alt-Tab
        try:
            self.iconbitmap(ICON_PATH)
        except Exception as e:
            print(f"iconbitmap: {e}")

        # 3. Иконка на панели задач Windows — нужен именно PhotoImage из .ico через PIL
        try:
            from PIL import Image, ImageTk
            pil_img = Image.open(ICON_PATH).convert("RGBA")
            photo = ImageTk.PhotoImage(pil_img)
            self.iconphoto(True, photo)
            self._taskbar_icon = photo  # обязательно сохранить ссылку, иначе Tkinter её удалит
        except Exception as e:
            print(f"iconphoto: {e} (поставь pillow: pip install pillow)")

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=240)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Левая колонка
        self.left_panel = ctk.CTkFrame(self, fg_color="#212121", corner_radius=0, width=240)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
        self.left_panel.grid_rowconfigure(2, weight=1)

        self.btn_settings = ctk.CTkButton(
            self.left_panel, text="⚙  настройки", font=("Segoe UI", 14, "bold"),
            fg_color="#333333", hover_color="#444444", text_color="#e0e0e0",
            corner_radius=12, height=45, command=self.open_settings
        )
        self.btn_settings.grid(row=0, column=0, padx=15, pady=(20, 10), sticky="ew")

        self.btn_new_chat = ctk.CTkButton(
            self.left_panel, text="+ новый чат", font=("Segoe UI", 12),
            fg_color="#2b2b2b", hover_color="#383838", text_color="#aaaaaa",
            corner_radius=10, height=35, command=self.create_new_chat
        )
        self.btn_new_chat.grid(row=1, column=0, padx=15, pady=(0, 10), sticky="ew")

        self.chat_scroll = ctk.CTkScrollableFrame(self.left_panel, fg_color="transparent")
        self.chat_scroll.grid(row=2, column=0, padx=5, pady=5, sticky="nsew")

        # Правая панель
        self.right_panel = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=0)
        self.right_panel.grid(row=0, column=1, sticky="nsew")
        self.right_panel.grid_rowconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(1, weight=0)
        self.right_panel.grid_rowconfigure(2, weight=0)
        self.right_panel.grid_columnconfigure(0, weight=1)

        self.messages_scroll = ctk.CTkScrollableFrame(self.right_panel, fg_color="#2b2b2b")
        self.messages_scroll.grid(row=0, column=0, sticky="nsew", padx=20, pady=15)
        self.messages_scroll.grid_columnconfigure(0, weight=1)

        self.lbl_file_attached = ctk.CTkLabel(self.right_panel, text="", font=("Segoe UI", 11), text_color="#4CAF50")
        self.lbl_file_attached.grid(row=1, column=0, padx=30, sticky="w")

        # Нижняя плашка ввода
        self.input_card = ctk.CTkFrame(self.right_panel, fg_color="#4a4a4a", corner_radius=20)
        self.input_card.grid(row=2, column=0, padx=25, pady=(5, 5), sticky="ew")
        self.input_card.grid_columnconfigure(0, weight=1)

        self.txt_input = ctk.CTkTextbox(
            self.input_card, height=45,
            font=("Segoe UI", 13), fg_color="transparent",
            text_color="#ffffff", wrap="word"
        )
        self.txt_input.grid(row=0, column=0, padx=(15, 10), pady=6, sticky="ew")

        self.txt_input.bind("<Control-Return>", self._handle_ctrl_enter)
        self.txt_input.bind("<Control-KP_Enter>", self._handle_ctrl_enter)

        self.btn_attach = ctk.CTkButton(
            self.input_card, text="📎", width=35, height=35,
            font=("Segoe UI", 16), fg_color="transparent", hover_color="#555555",
            corner_radius=18, command=self.attach_file
        )
        self.btn_attach.grid(row=0, column=1, padx=(0, 5), pady=6)

        self.btn_send = ctk.CTkButton(
            self.input_card, text="➤", width=35, height=35,
            font=("Segoe UI", 16, "bold"), fg_color="#1f1f1f", hover_color="#000000",
            corner_radius=18, text_color="#ffffff", command=self.send_message
        )
        self.btn_send.grid(row=0, column=2, padx=(0, 10), pady=6)

        self.bottom_bar = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.bottom_bar.grid(row=3, column=0, pady=(0, 10))

        self.badge_model = ctk.CTkButton(
            self.bottom_bar, text="", font=("Segoe UI", 11),
            fg_color="#3a3a3a", hover_color="#4a4a4a", text_color="#cccccc",
            corner_radius=15, height=25, command=self.open_settings
        )
        self.badge_model.pack()
        self._update_badge()

    def _handle_ctrl_enter(self, event):
        self.send_message()
        return "break"

    def _update_badge(self):
        m = self.data["settings"].get("model", "gemini-3.8-flash")
        mode = self.data["settings"].get("mode", "Default")
        prefix = "🛡️" if mode == "Default" else "⚡"
        self.badge_model.configure(text=f"{prefix}  {m}")

    def _load_chats_to_sidebar(self):
        for widget in self.chat_scroll.winfo_children():
            widget.destroy()

        if not self.data["chats"]:
            self.create_new_chat()
            return

        for chat in self.data["chats"]:
            is_active = (chat["id"] == self.current_chat_id)
            btn = ctk.CTkButton(
                self.chat_scroll, text=f"💬  {chat['title']}", anchor="w",
                font=("Segoe UI", 12),
                fg_color="#383838" if is_active else "transparent",
                hover_color="#333333",
                text_color="#ffffff" if is_active else "#aaaaaa",
                corner_radius=10, height=40,
                command=lambda cid=chat["id"]: self.select_chat(cid)
            )
            btn.bind("<Button-3>", lambda e, cid=chat["id"]: self._show_chat_context_menu(e, cid))
            btn.pack(fill="x", pady=2)

        if not self.current_chat_id and self.data["chats"]:
            self.select_chat(self.data["chats"][0]["id"])

    def _show_chat_context_menu(self, event, chat_id):
        menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="#ffffff", activebackground="#444444")
        menu.add_command(label="Переименовать", command=lambda: self.rename_chat(chat_id))
        menu.add_command(label="Удалить", command=lambda: self.delete_chat(chat_id))
        menu.tk_popup(event.x_root, event.y_root)

    def create_new_chat(self):
        cid = str(uuid.uuid4())
        num = len(self.data["chats"]) + 1
        new_c = {"id": cid, "title": f"чат {num}", "messages": []}
        self.data["chats"].append(new_c)
        save_data(self.data)
        self.select_chat(cid)

    def select_chat(self, chat_id):
        self.current_chat_id = chat_id
        self._load_chats_to_sidebar()
        self._render_current_messages()

    def rename_chat(self, chat_id):
        chat = next((c for c in self.data["chats"] if c["id"] == chat_id), None)
        if not chat:
            return
        dialog = ctk.CTkInputDialog(text="Новое название чата:", title="Переименование")
        new_title = dialog.get_input()
        if new_title:
            chat["title"] = new_title.strip()
            save_data(self.data)
            self._load_chats_to_sidebar()

    def delete_chat(self, chat_id):
        if len(self.data["chats"]) <= 1:
            messagebox.showinfo("PyCodex", "Нельзя удалить единственный чат!")
            return
        self.data["chats"] = [c for c in self.data["chats"] if c["id"] != chat_id]
        save_data(self.data)
        self.current_chat_id = self.data["chats"][0]["id"]
        self.select_chat(self.current_chat_id)

    def _render_current_messages(self):
        for widget in self.messages_scroll.winfo_children():
            widget.destroy()

        chat = next((c for c in self.data["chats"] if c["id"] == self.current_chat_id), None)
        if not chat:
            return

        for msg in chat["messages"]:
            role = msg["role"]
            text = msg["content"]
            self._add_bubble(role, text)

    def _add_bubble(self, role, text):
        frame = ctk.CTkFrame(self.messages_scroll, fg_color="transparent")
        frame.pack(fill="x", pady=8, padx=10)

        clean_text = clean_markdown(text) if role in ("agent", "user") else text

        if role == "user":
            bubble = ctk.CTkLabel(
                frame, text=clean_text, font=("Segoe UI", 13),
                fg_color="#5a5a5a", text_color="#ffffff",
                corner_radius=18, padx=16, pady=10,
                wraplength=550, justify="left"
            )
            bubble.pack(side="right", anchor="e")
        elif role == "agent":
            bubble = ctk.CTkLabel(
                frame, text=clean_text, font=("Segoe UI", 13),
                fg_color="#3a3a3a", text_color="#e0e0e0",
                corner_radius=18, padx=16, pady=10,
                wraplength=550, justify="left"
            )
            bubble.pack(side="left", anchor="w")
        elif role == "system":
            bubble = ctk.CTkLabel(
                frame, text=clean_text, font=("Segoe UI", 11, "italic"),
                fg_color="#2b2b2b", text_color="#888888",
                corner_radius=10, padx=10, pady=4,
                wraplength=600, justify="center"
            )
            bubble.pack(anchor="center")

        self.messages_scroll._parent_canvas.yview_moveto(1.0)
        return bubble

    def _create_streaming_bubble(self):
        frame = ctk.CTkFrame(self.messages_scroll, fg_color="transparent")
        frame.pack(fill="x", pady=8, padx=10)

        bubble = ctk.CTkLabel(
            frame, text="", font=("Segoe UI", 13),
            fg_color="#3a3a3a", text_color="#e0e0e0",
            corner_radius=18, padx=16, pady=10,
            wraplength=550, justify="left"
        )
        bubble.pack(side="left", anchor="w")
        self.messages_scroll._parent_canvas.yview_moveto(1.0)
        return bubble

    def _update_streaming_bubble(self, bubble, text):
        clean_text = clean_markdown(text)
        bubble.configure(text=clean_text)
        self.messages_scroll._parent_canvas.yview_moveto(1.0)

    def attach_file(self):
        f = filedialog.askopenfilename()
        if f:
            self.attached_file_path = f
            filename = os.path.basename(f)
            self.lbl_file_attached.configure(text=f"📎 Прикреплён: {filename} (нажмите, чтобы убрать)")
            self.lbl_file_attached.bind("<Button-1>", lambda e: self._detach_file())

    def _detach_file(self):
        self.attached_file_path = None
        self.lbl_file_attached.configure(text="")

    def send_message(self):
        if self.is_generating or not self.current_chat_id:
            return

        api_key = self.data["settings"].get("api_key")
        if not api_key:
            messagebox.showwarning("Настройки", "Задайте Google AI Studio API ключ в Настройках!")
            self.open_settings()
            return

        text = self.txt_input.get("1.0", "end").strip()
        if not text and not self.attached_file_path:
            return

        if self.attached_file_path:
            try:
                with open(self.attached_file_path, "r", encoding="utf-8") as f:
                    file_body = f.read()
                text += f"\n\n[Прикреплён файл {os.path.basename(self.attached_file_path)}]:\n```\n{file_body}\n```"
            except Exception as e:
                text += f"\n\n[Ошибка чтения файла: {e}]"
            self._detach_file()

        self.txt_input.delete("1.0", "end")
        self._append_message("user", text)

        self.is_generating = True
        self.btn_send.configure(state="disabled")

        threading.Thread(target=self._run_agent, daemon=True).start()

    def _append_message(self, role, content):
        chat = next(c for c in self.data["chats"] if c["id"] == self.current_chat_id)
        chat["messages"].append({"role": role, "content": content})
        save_data(self.data)
        self._add_bubble(role, content)

    def _run_agent(self):
        try:
            client = genai.Client(api_key=self.data["settings"]["api_key"])
            model_name = self.data["settings"].get("model", "gemini-3.8-flash")
            chat_obj = next(c for c in self.data["chats"] if c["id"] == self.current_chat_id)

            user_custom_prompt = self.data["settings"].get("custom_prompt", "")
            combined_prompt = f"{CORE_SYSTEM_PROMPT}\n\n[Пользовательские инструкции]:\n{user_custom_prompt}"

            config = types.GenerateContentConfig(
                system_instruction=combined_prompt,
                tools=ALL_TOOLS
            )

            history = []
            for m in chat_obj["messages"]:
                if m["role"] == "user":
                    history.append(types.Content(role="user", parts=[types.Part.from_text(text=m["content"])]))
                elif m["role"] == "agent":
                    history.append(types.Content(role="model", parts=[types.Part.from_text(text=m["content"])]))

            session = client.chats.create(
                model=model_name,
                config=config,
                history=history[:-1]
            )

            current_input = history[-1].parts[0].text

            while True:
                stream = session.send_message_stream(current_input)

                accumulated_text = ""
                pending_function_calls = []
                stream_bubble = None

                for chunk in stream:
                    if chunk.function_calls:
                        pending_function_calls.extend(chunk.function_calls)

                    if chunk.text:
                        accumulated_text += chunk.text
                        if not stream_bubble:
                            stream_bubble = self._create_streaming_bubble()
                        self._update_streaming_bubble(stream_bubble, accumulated_text)

                if pending_function_calls:
                    for call in pending_function_calls:
                        fn_name = call.name
                        fn_args = dict(call.args)

                        allowed = self._check_tool_allowed(fn_name, fn_args)
                        if allowed:
                            self._append_message("system", f"🛠️ Вызов {fn_name}: {fn_args}")
                            func = TOOLS_DICT.get(fn_name)
                            try:
                                tool_res = func(**fn_args) if func else "Функция не найдена"
                            except Exception as ex:
                                tool_res = f"Ошибка вызова {fn_name}: {str(ex)}"
                        else:
                            tool_res = "Действие отменено пользователем."
                            self._append_message("system", f"⛔ Отклонено пользователем: {fn_name}")

                        current_input = types.Part.from_function_response(
                            name=fn_name,
                            response={"result": str(tool_res)}
                        )
                else:
                    if accumulated_text:
                        chat_obj["messages"].append({"role": "agent", "content": accumulated_text})
                        save_data(self.data)
                    break

        except Exception as e:
            self._append_message("system", f"❌ Ошибка: {str(e)}")
        finally:
            self.is_generating = False
            self.btn_send.configure(state="normal")

    def _check_tool_allowed(self, fn_name, fn_args):
        mode = self.data["settings"].get("mode", "Default")
        if mode == "Turbo":
            return True

        evt = threading.Event()
        allowed = [False]

        def ask():
            args_str = json.dumps(fn_args, ensure_ascii=False, indent=2)
            msg = f"ИИ запрашивает действие:\n\nИнструмент: {fn_name}\nАргументы:\n{args_str}\n\nРазрешить?"
            allowed[0] = messagebox.askyesno("Default Mode: Подтверждение", msg, parent=self)
            evt.set()

        self.after(0, ask)
        evt.wait()
        return allowed[0]

    def open_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Настройки")
        win.geometry("540x570")
        win.configure(fg_color="#212121")
        win.grab_set()

        # Иконка и для окна настроек
        try:
            if os.path.exists(ICON_PATH):
                win.iconbitmap(ICON_PATH)
        except Exception:
            pass

        ctk.CTkLabel(win, text="Google AI Studio API Key:", font=("Segoe UI", 12)).pack(anchor="w", padx=25, pady=(15, 2))
        entry_api = ctk.CTkEntry(win, show="*", fg_color="#2b2b2b", border_color="#444444")
        entry_api.insert(0, self.data["settings"].get("api_key", ""))
        entry_api.pack(fill="x", padx=25)

        ctk.CTkLabel(win, text="Бесплатная модель Gemini:", font=("Segoe UI", 12)).pack(anchor="w", padx=25, pady=(10, 2))
        cmb_model = ctk.CTkComboBox(win, values=MODELS, fg_color="#2b2b2b", border_color="#444444", dropdown_fg_color="#2b2b2b")
        cmb_model.set(self.data["settings"].get("model", "gemini-3.8-flash"))
        cmb_model.pack(fill="x", padx=25)

        ctk.CTkLabel(win, text="Режим работы:", font=("Segoe UI", 12)).pack(anchor="w", padx=25, pady=(10, 2))
        mode_var = ctk.StringVar(value=self.data["settings"].get("mode", "Default"))
        rb1 = ctk.CTkRadioButton(win, text="Default Mode (подтверждение каждого действия)", variable=mode_var, value="Default")
        rb1.pack(anchor="w", padx=30, pady=2)
        rb2 = ctk.CTkRadioButton(win, text="Turbo Mode (полная автономность)", variable=mode_var, value="Turbo")
        rb2.pack(anchor="w", padx=30, pady=2)

        ctk.CTkLabel(win, text="Пользовательский системный промпт (дополнительный):", font=("Segoe UI", 12)).pack(anchor="w", padx=25, pady=(10, 2))
        txt_prompt = ctk.CTkTextbox(win, height=110, fg_color="#2b2b2b", border_color="#444444", border_width=1)
        txt_prompt.insert("1.0", self.data["settings"].get("custom_prompt", DEFAULT_CUSTOM_PROMPT))
        txt_prompt.pack(fill="x", padx=25)

        def save_settings():
            self.data["settings"]["api_key"] = entry_api.get().strip()
            self.data["settings"]["model"] = cmb_model.get()
            self.data["settings"]["mode"] = mode_var.get()
            self.data["settings"]["custom_prompt"] = txt_prompt.get("1.0", "end").strip()
            save_data(self.data)
            self._update_badge()
            win.destroy()

        btn_save = ctk.CTkButton(win, text="Сохранить", fg_color="#3a3a3a", hover_color="#4a4a4a", command=save_settings)
        btn_save.pack(pady=15)


if __name__ == "__main__":
    app = PyCodex()
    app.mainloop()
