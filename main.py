import customtkinter as ctk
import tkinter as tk
import socket
import threading
import json
import os
import tkinter.messagebox as messagebox
import socket
import threading
 
import sys # sysのインポートが必要です
import platform
import webbrowser

VERSION = "0.75a"

# 1. 実行環境に応じたベースディレクトリの取得
if getattr(sys, 'frozen', False):
    # EXE化（PyInstaller）されている場合
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 通常のPythonスクリプトとして実行されている場合
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. 変数名の差し替え（BASE_DIRを結合する）
CONFIG_FILE = os.path.join(BASE_DIR, "projectors.json")
PRESETS_FILE = os.path.join(BASE_DIR, "presets.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

# --- プラットフォーム判定 ---
# Linux(X11) では ButtonRelease-3 でメニューが即閉じるため Button-3 を使う
_RIGHT_CLICK = "<Button-3>" if platform.system() == "Linux" else "<ButtonRelease-3>"

# --- 多言語化グローバルシステム ---
_translations = {}
_current_lang = "ja"

def t_text(key, default=""):
    """どこからでも呼び出せる文字取得関数"""
    data = _translations.get(key, default if default else key)
    if isinstance(data, dict):
        return data.get("text", key)
    return data

def t_size(key, default_size=12):
    """どこからでも呼び出せるサイズ取得関数"""
    data = _translations.get(key)
    if isinstance(data, dict) and "size" in data:
        return data["size"]
    return default_size

def resource_path(relative_path):
    """ PyInstallerの展開先（一時フォルダ）、または通常のパスを返す """
    try:
        # PyInstallerでビルドされたEXE実行時
        base_path = sys._MEIPASS
    except Exception:
        # VS Codeなどでの通常のPython実行時
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

from pypjlink import Projector
from PIL import Image, ImageDraw

# GUIのテーマ設定 (デフォルトをライトモードに変更)
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

def load_or_create_dummy_image(filename, size=(120, 90)):
    # ▼ 追加：PyInstaller対応のパスに変換
    target_path = resource_path(filename)
    
    try:
        # filename ではなく target_path を開く
        img = Image.open(target_path)
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        img = Image.new('RGBA', size, (80, 80, 80, 150))
        d = ImageDraw.Draw(img)
        # エラー表示用にパスも出しておくとデバッグが楽です
        d.text((5, size[1]//2 - 10), f"Missing:\n{filename}", fill="white")
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)

def load_raw_image(filename, fallback_size=(120, 90)):
    """PIL Image をそのまま返す（CTkImage に変換しない）"""
    target_path = resource_path(filename)
    try:
        return Image.open(target_path).convert("RGBA")
    except Exception:
        img = Image.new('RGBA', fallback_size, (80, 80, 80, 150))
        d = ImageDraw.Draw(img)
        d.text((5, fallback_size[1]//2 - 10), f"Missing:\n{filename}", fill="white")
        return img

class RenameDialog(ctk.CTkToplevel):
    """名前変更用のカスタムダイアログ"""
    def __init__(self, parent, current_name, title_text=t_text("menu_rename")):
        super().__init__(parent)
        self.title(t_text("title_rename_dialog"))
        self.result = None
        
        parent.update_idletasks()
        dialog_w = 300
        dialog_h = 150
        pos_x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (dialog_w // 2)
        pos_y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (dialog_h // 2)
        self.geometry(f"{dialog_w}x{dialog_h}+{pos_x}+{pos_y}")
        
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(self, text=t_text("prompt_new_name")).pack(pady=(15, 5))
        
        self.entry = ctk.CTkEntry(self, width=200)
        self.entry.pack(pady=5)
        self.entry.insert(0, current_name)
        self.entry.select_range(0, 'end')
        self.entry.focus_set()

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text=t_text("btn_cancel"), width=80, fg_color="gray", command=self.destroy).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text=t_text("btn_ok"), width=80, command=self.on_ok).pack(side="left", padx=5)

        self.bind("<Return>", lambda event: self.on_ok())
        self.wait_window()

    def on_ok(self):
        self.result = self.entry.get()
        self.destroy()


class SpacerCard(ctk.CTkFrame):
    """グリッドに空白を作るためのダミーカード"""
    def __init__(self, master, delete_cb=None):
        super().__init__(master, fg_color="transparent", border_width=0)
        self.ip = "spacer" 
        self.name = t_text("label_spacer")
        self.delete_cb = delete_cb
        
        # サイズだけ確保
        self.configure(width=120, height=120) 
        
        # 右クリックで削除できるように
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label=t_text("menu_delete_spacer"), command=lambda: self.delete_cb(self))
        self.bind(_RIGHT_CLICK, lambda e: self.menu.tk_popup(e.x_root, e.y_root))



class ProjectorCard(ctk.CTkFrame):
    """プロジェクター1台分の操作パネル"""
    # すべての新しい引数（data, width, height, font_size）にデフォルト値を設定して配置
    def __init__(self, master, ip, name=None, icons=None, password=None, rename_cb=None, delete_cb=None, 
                 data=None, width=300, height=180, font_size=12, btn_height=55, **kwargs):
        
        # 1. 親クラス（Frame）に動的なサイズを渡す
        super().__init__(master, width=width, height=height, **kwargs)
        
        self.ip = ip
        self.name = data["name"] if data else name
        self.password = password
        self.icons = icons 
        self.rename_cb = rename_cb
        self.delete_cb = delete_cb
        self.is_muted = False
        self.power_state = "off"
        self.is_offline = True 

        # 勝手に枠が縮まないように固定する設定
        self.grid_propagate(False)
        self.pack_propagate(False)

        # --- UI配置 ---
        self.is_targeted = ctk.BooleanVar(value=True)
        self.target_chk = ctk.CTkCheckBox(self, text="Target", variable=self.is_targeted, width=20, font=("Arial", 11))
        self.target_chk.pack(pady=(2, 0))

        # アイコンボタン (ここでの右クリックは「電源・管理」)
        self.icon_btn = ctk.CTkButton(self, text="", image=self.icons["offline"], width=80, height=btn_height,
                                      fg_color="transparent", hover_color="#37474F")
        self.icon_btn.pack(pady=1, padx=10)
        
        # 左クリック（離した瞬間）でミュート切り替え
        self.icon_btn.bind("<ButtonRelease-1>", lambda e: self.toggle_mute())

        # 情報ラベル (受け取った font_size を適用)
        self.label = ctk.CTkLabel(self, text=f"{self.name}\n({self.ip})", 
                                  font=("Arial", font_size, "bold"), justify="center", cursor="hand2")
        self.label.pack(pady=(0, 2))

        # --- 1. 管理メニュー (アイコン右クリック用) ---
        self.context_menu = tk.Menu(self, tearoff=0, font=("Arial", 14))
        self.context_menu.add_command(label=t_text("menu_web_access"), command=self.open_web_control)
        self.context_menu.add_separator()
        
        self.context_menu.add_command(label=t_text("menu_power_on"), command=lambda: self.control_power("Power ON"))
        self.context_menu.add_command(label=t_text("menu_power_off"), command=lambda: self.control_power("Power OFF"))
        self.context_menu.add_separator()
        
        self.context_menu.add_command(label=t_text("menu_rename"), command=self.rename_device)
        self.context_menu.add_command(label=t_text("menu_delete"), command=self.delete_device)

        # --- 2. 入力切替メニュー (ラベル右クリック用) ---
        self.input_menu = tk.Menu(self, tearoff=0, font=("Arial", 12))
        self.input_menu.add_command(label="DIGITAL 1", command=lambda: self.set_input_source("DIGITAL", 1))
        self.input_menu.add_command(label="DIGITAL 2", command=lambda: self.set_input_source("DIGITAL", 2))
        self.input_menu.add_command(label="DIGITAL 3", command=lambda: self.set_input_source("DIGITAL", 3))
        self.input_menu.add_separator()
        self.input_menu.add_command(label="RGB", command=lambda: self.set_input_source("RGB", 1))
        self.input_menu.add_separator()
        self.input_menu.add_command(label="NETWORK", command=lambda: self.set_input_source("NETWORK", 1))

        # --- ★マウスバインドの再設定★ ---
        # アイコンを右クリックした時だけ「電源管理メニュー」を出す
        self.icon_btn.bind(_RIGHT_CLICK, self.show_context_menu)
        
        # ラベルを右クリックした時は「入力切替メニュー」を出す
        self.label.bind(_RIGHT_CLICK, self.show_input_menu)
        
        # ラベルを左クリックしても入力切替が出るようにしておく
        self.label.bind("<ButtonRelease-1>", self.show_input_menu)



    def show_context_menu(self, event):
        """電源・管理メニューを表示"""
        self.context_menu.tk_popup(event.x_root, event.y_root)
        
    def open_web_control(self):
        """デフォルトブラウザでプロジェクターのWeb設定画面を開く"""
        url = f"http://{self.ip}"
        print(f"🔗 Opening Web Control: {url}")
        webbrowser.open(url)

    def show_input_menu(self, event):
        """入力切替メニューを表示"""
        # ※実機がないテスト中は if not self.is_offline: を消すとメニュー確認が楽です
        self.input_menu.tk_popup(event.x_root, event.y_root)

    def set_input_source(self, source_type, source_num):
        """指定した入力ソースへ切り替える（個別）"""
        if not self.is_offline:
            threading.Thread(target=self._send_pjlink_input, args=(source_type, source_num), daemon=True).start()

    def _send_pjlink_input(self, source_type, source_num):
        try:
            pj = Projector.from_address(self.ip)
            pj.authenticate(self.password)
            pj.set_input(source_type, source_num)
        except Exception as e:
            print(f"⚠️ [{self.ip}] 入力切替エラー: {e}")


    def rename_device(self):
        dialog = RenameDialog(self, self.name)
        if dialog.result:
            self.name = dialog.result.strip()
            self.label.configure(text=f"{self.name}\n({self.ip})")
            if self.rename_cb: self.rename_cb()

    def delete_device(self):
        # 変更後 (.format を使ってJSONの {name} に名前を流し込む)
        msg = t_text("msg_delete_confirm").format(name=self.name)
        if messagebox.askyesno(t_text("title_delete"), msg):
            if self.delete_cb: self.delete_cb(self)

    def _update_ui_states(self):
        if not self.winfo_exists():  # 破棄済みのカードへの更新を防ぐ
            return
        if self.is_offline: self.icon_btn.configure(image=self.icons["offline"])
        elif self.power_state == "off": self.icon_btn.configure(image=self.icons["power_off"])
        elif self.is_muted: self.icon_btn.configure(image=self.icons["power_on_muted"])
        else: self.icon_btn.configure(image=self.icons["power_on_projecting"])

    def fetch_status(self):
        try:
            pj = Projector.from_address(self.ip)
            pj.authenticate(self.password)
            pwr = pj.get_power()
            self.power_state = "on" if pwr in ["on", "warm-up"] else "off"
            if self.power_state == "on":
                try:
                    mute_states = pj.get_mute()
                    self.is_muted = any(mute_states)
                except: pass
            else: self.is_muted = False
            self.is_offline = False 
            self.after(0, self._update_ui_states)
        except:
            self.is_offline = True
            self.after(0, self._update_ui_states)

    def _send_pjlink_command(self, action_type, value):
        try:
            pj = Projector.from_address(self.ip)
            pj.authenticate(self.password)
            if action_type == "mute": pj.set_mute(3, value)
            elif action_type == "power": pj.set_power(value)
            self.is_offline = False 
            self.after(0, self._update_ui_states)
        except:
            self.is_offline = True
            self.after(0, self._update_ui_states)

    def set_mute_state(self, is_muted):
        self.is_muted = is_muted
        self._update_ui_states()
        threading.Thread(target=self._send_pjlink_command, args=("mute", self.is_muted), daemon=True).start()

    def set_power_state(self, state):
        self.power_state = state
        self._update_ui_states()
        threading.Thread(target=self._send_pjlink_command, args=("power", state), daemon=True).start()

    def toggle_mute(self):
        if not self.is_offline and self.power_state == "on":
            self.set_mute_state(not self.is_muted)

    def control_power(self, choice):
        self.set_power_state("on" if choice == "Power ON" else "off")


class ManualSortDialog(ctk.CTkToplevel):
    def __init__(self, parent, cards):
        super().__init__(parent)
        self.title(t_text("title_manual_sort"))
        # self.geometry("450x600")
        
        
        parent.update_idletasks() # 親のサイズを確定させる
        dialog_w = 450
        dialog_h = 600
        pos_x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (dialog_w // 2)
        pos_y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (dialog_h // 2)
        self.geometry(f"{dialog_w}x{dialog_h}+{pos_x}+{pos_y}")
        
        
        # ウインドウを最前面に持ってくる
        self.after(100, self.lift)
        self.after(100, self.focus_force)
        
        self.temp_list = list(cards)
        self.applied = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_propagate(False) 
        self.pack_propagate(False)

        ctk.CTkLabel(self, text=t_text("prompt_sort"), font=("Arial", 11)).grid(row=0, column=0, pady=5)

        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        
        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.grid(row=2, column=0, pady=10)
        
        ctk.CTkButton(self.btn_frame, text=t_text("btn_add_spacer"), font=("Arial", t_size("btn_add_spacer", 12)), fg_color="#2E7D32", command=self.add_spacer).pack(side="left", padx=5)
        ctk.CTkButton(self.btn_frame, text=t_text("btn_cancel"), font=("Arial", t_size("btn_cancel", 12)), fg_color="gray", command=self.destroy).pack(side="left", padx=5)
        ctk.CTkButton(self.btn_frame, text=t_text("btn_apply_save"), font=("Arial", t_size("btn_apply_save", 12)), command=self.apply).pack(side="left", padx=5)

        self.refresh_list()
        self.grab_set() # 他の操作を無効化

    def refresh_list(self):
        for child in self.scroll_frame.winfo_children():
            child.destroy()
        
        for i, card in enumerate(self.temp_list):
            item_f = ctk.CTkFrame(self.scroll_frame)
            item_f.pack(fill="x", pady=2, padx=5)
            
            label_text = f"{i+1}: {card.name}"
            if card.ip != "spacer": label_text += f" ({card.ip})"
            
            ctk.CTkLabel(item_f, text=label_text, anchor="w").pack(side="left", padx=10, fill="x", expand=True)
            
            # 操作ボタン
            ctk.CTkButton(item_f, text="↑", width=30, command=lambda idx=i: self.move(-1, idx)).pack(side="left", padx=2)
            ctk.CTkButton(item_f, text="↓", width=30, command=lambda idx=i: self.move(1, idx)).pack(side="left", padx=2)
            ctk.CTkButton(item_f, text="×", width=30, fg_color="#C62828", command=lambda idx=i: self.delete_item(idx)).pack(side="left", padx=2)

    def move(self, direction, index):
        new_index = index + direction
        if 0 <= new_index < len(self.temp_list):
            self.temp_list[index], self.temp_list[new_index] = self.temp_list[new_index], self.temp_list[index]
            self.refresh_list()

    def delete_item(self, index):
        self.temp_list.pop(index)
        self.refresh_list()

    def add_spacer(self):
        # 仮のSpacerオブジェクト（保存時に実体化させるのでここでは最小限）
        new_spacer = type('obj', (object,), {'ip': 'spacer', 'name': t_text("label_spacer")})
        self.temp_list.append(new_spacer)
        self.refresh_list()

    def apply(self):
        self.applied = True
        self.result_list = self.temp_list
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 1. 現在の言語を設定（初期値はOS判定にするか、とりあえず"ja"で固定）
        self.preload_language()

        self.title(f"{t_text('app_title')} {VERSION} - PJLink Multi-Controller -")
        self.geometry("640x500")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        
        # --- リモート制御設定 ---
        self.udp_port = 5000
        self.tcp_port = 5001
        self.start_remote_listeners()

        # PJアイコン（サイズ別に動的生成するため、Raw PIL Imageとして保持）
        _icon_files = {
            "offline":             "image/icon_offline.png",
            "power_off":           "image/icon_power_off.png",
            "power_on_muted":      "image/icon_power_on_muted.png",
            "power_on_projecting": "image/icon_power_on_projecting.png",
        }
        self._raw_images = {key: load_raw_image(path) for key, path in _icon_files.items()}




        # --- UI作成の前に、グリッドサイズの設定を追加 ---
        self.grid_configs = {
            #                height = checkbox + btn + label + margin
            "small":  {"width": 80,  "height": 110, "font_size": 12, "padding": 10, "col_width": 100, "icon_size": (40, 30), "btn_height": 40},
            "medium": {"width": 150, "height": 130, "font_size": 12, "padding": 10, "col_width": 170, "icon_size": (60, 45), "btn_height": 55},
            "large":  {"width": 200, "height": 155, "font_size": 12, "padding": 10, "col_width": 220, "icon_size": (90, 68), "btn_height": 80},
        }
        self.current_size = "small"




        # -----------------------------------
        # 1. サイドバー
        # -----------------------------------
        # 0: 管理Label / 1: 操作ロック / 2: IP Entry / 3: btn_frame(追加/探査) / 4: 更新Button / 5: StatusLabel
        # 6: 一括Label / 7: PowerLabel / 8: MuteON / 9: MuteOFF / 10: InputSelect
        # 11: 整列Label / 12: SortMenu
        # 14: 特別Label / 15: DataMenu / 16: ThemeMenu / 17: LanguageMenu

        # サイドバーのボタンの高さを統一するための変数
        sa_h = 24
        sb_h = 20 
        
        self.sidebar = ctk.CTkFrame(self, width=110, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_rowconfigure(13, weight=1)
                
        # ctk.CTkLabel(self.sidebar, text=self.t_text("title_manage"), font=("Arial", 14, "bold")).grid(row=0, column=0, padx=5, pady=(8, 2))
        ctk.CTkLabel(self.sidebar, text=t_text("title_manage"), font=("Arial", 14, "bold")).grid(row=0, column=0, padx=5, pady=(8, 2))
        
        # ▼ 操作ロック用のスイッチを追加 (初期値はオフ=操作可能)
        self.lock_switch = ctk.CTkSwitch(self.sidebar, text=t_text("lock_switch"), command=self.toggle_manual_lock)
        self.lock_switch.grid(row=1, column=0, padx=10, pady=2)
                
        # IP Entry（作成部分）
        self.ip_entry = ctk.CTkEntry(self.sidebar, placeholder_text=t_text("placeholder_ip"))
        self.ip_entry.grid(row=2, column=0, padx=10, pady=2, sticky="ew")
        self.ip_entry.bind("<Return>", lambda event: self.add_manual_ip())
        # ▼ これを Entry 作成直後に配置してください
        initial_prefix = self.get_local_prefix()
        self.ip_entry.insert(0, initial_prefix)
                
        # ▼ Escキーで入力欄からフォーカスを外す
        self.ip_entry.bind("<Escape>", lambda event: self.focus_set())
        
        # ▼ 自動取得したサブネットを初期入力
        current_prefix = self.get_local_prefix()
        self.ip_entry.insert(0, current_prefix)
        
        # 追加・探査
        btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        btn_frame.grid(row=3, column=0, padx=5, pady=8, sticky="ew")
        btn_frame.grid_columnconfigure((0,1), weight=1)
        ctk.CTkButton(btn_frame, text=t_text("btn_add"),height=sa_h, command=self.add_manual_ip, width=40).grid(row=3, column=0, padx=(0,2))
        self.scan_btn = ctk.CTkButton(btn_frame, text=t_text("btn_scan"), fg_color="#2E7D32",height=sa_h, command=self.start_scan, width=40)
        self.scan_btn.grid(row=3, column=1, padx=(2,0))

        # 更新
        self.refresh_all_btn = ctk.CTkButton(self.sidebar, text=t_text("btn_refresh"), fg_color="#546E7A", height=sa_h, command=self.refresh_all_status)
        self.refresh_all_btn.grid(row=4, column=0, padx=10, pady=2, sticky="ew")
        
        # ステータスラベル
        self.status_label = ctk.CTkLabel(self.sidebar, text=t_text("status_idle"), text_color="gray", font=("Arial", 11))
        self.status_label.grid(row=5, column=0, padx=5, pady=0)

        # 一括操作セクション
        ctk.CTkLabel(self.sidebar, text=t_text("title_bulk"), height=sb_h, font=("Arial", 14, "bold")).grid(row=6, column=0, padx=5, pady=(5, 2))

        # 電源
        self.power_label = ctk.CTkLabel(self.sidebar, text=t_text("label_power"), 
                                        fg_color="#1f538d", corner_radius=6, height=sb_h,
                                        font=("Arial", 13, "bold"), cursor="hand2")
        self.power_label.grid(row=7, column=0, padx=10, pady=2, sticky="ew")
        
        self.all_power_menu = tk.Menu(self, tearoff=0, font=("Arial", 12))
        self.all_power_menu.add_command(label=t_text("all_menu_power_on"), command=lambda: self.control_all_power("Power ON"))
        self.all_power_menu.add_command(label=t_text("all_menu_power_off"), command=lambda: self.control_all_power("Power OFF"))
        # self.power_label.bind("<ButtonRelease-1>", lambda e: self.all_power_menu.tk_popup(e.x_root, e.y_root))
        # self.power_label.bind("<ButtonRelease-1>", lambda e: (self.focus_set(), self.all_power_menu.tk_popup(e.x_root, e.y_root)))

        self.power_label.bind("<ButtonRelease-1>", self.show_all_power_menu)

        # ミュート            
        # Mute ONボタン
        self.btn_mute_on = ctk.CTkButton(
            self.sidebar, 
            text=t_text("btn_mute_on"), 
            fg_color="#C62828", 
            height=sb_h,
            command=lambda: self.control_all_mute(True)  # bindではなくcommandを使う
        )
        self.btn_mute_on.grid(row=8, column=0, padx=10, pady=2, sticky="ew")

        # Mute OFFボタン
        self.btn_mute_off = ctk.CTkButton(
            self.sidebar, 
            text=t_text("btn_mute_off"), 
            fg_color="gray", 
            height=sb_h,
            command=lambda: self.control_all_mute(False) # commandを使う
        )
        self.btn_mute_off.grid(row=9, column=0, padx=10, pady=2, sticky="ew")
        
       
        
        # インプットセレクト
        self.all_input_menu = ctk.CTkOptionMenu(self.sidebar, 
            values=["DIGITAL 1", "DIGITAL 2", "DIGITAL 3", "RGB", "NETWORK"], 
            height=sb_h,
            command=self.control_all_input)
        self.all_input_menu.set(t_text("menu_input_select"))
        self.all_input_menu.grid(row=10, column=0, padx=10, pady=2, sticky="ew")

        # 整列セクション
        ctk.CTkLabel(self.sidebar, text=t_text("title_sort"), font=("Arial", 14, "bold")).grid(row=11, column=0, padx=5, pady=(5, 0))
        self.sort_menu = ctk.CTkOptionMenu(
        self.sidebar, 
        values=_translations.get("sort_options", ["IP Order", "Name Order", "Manual..."]), 
        height=sb_h,
        command=self.handle_sort_menu
)
        self.sort_menu.set(t_text("menu_sort"))
        self.sort_menu.grid(row=12, column=0, padx=10, pady=2, sticky="ew")

        # データ・設定セクション
        ctk.CTkLabel(self.sidebar, text=t_text("title_special"), font=("Arial", 14, "bold")).grid(row=14, column=0, padx=5, pady=(5, 0))
        self.manage_menu = ctk.CTkOptionMenu(
            self.sidebar, 
            values=_translations.get("data_options", ["Save Manually", "Initialize Data…"]), 
            height=sb_h,
            command=self.handle_manage_menu
        )
        self.manage_menu.set(t_text("menu_data"))
        self.manage_menu.grid(row=15, column=0, padx=10, pady=(0, 2), sticky="ew")

        self.theme_menu = ctk.CTkOptionMenu(
            self.sidebar, 
            values=_translations.get("theme_options", ["Light Mode", "Dark Mode"]), 
            height=sb_h,
            command=self.change_theme
        )
        self.theme_menu.set(t_text("menu_theme"))
        self.theme_menu.grid(row=16, column=0, padx=10, pady=(0, 10), sticky="ew")

        # 言語切り替えメニュー
        self.lang_menu = ctk.CTkOptionMenu(self.sidebar, values=["日本語", "English"], 
            height=sb_h,
            command=self.change_language_setting)
        self.lang_menu.set(t_text("menu_lang"))
        self.lang_menu.grid(row=17, column=0, padx=10, pady=(0, 10), sticky="ew")

        # -----------------------------------
        # 2. メインエリア
        # -----------------------------------
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        # ▼ 変更点: 固定の4列設定を削除し、初期列数とリサイズ検知を追加
        self.current_columns = 4 
        self.scroll_frame.bind("<Configure>", self.on_frame_resize)

        # -----------------------------------
        # 3. プリセットエリア (下部 5x2配置)
        # -----------------------------------
        self.preset_frame = ctk.CTkFrame(self) # height指定を外して内容に合わせる
        self.preset_frame.grid(row=1, column=1, sticky="ew", padx=10, pady=(0, 10))
        # 5列分を均等割り
        for i in range(5):
            self.preset_frame.grid_columnconfigure(i, weight=1)
        
        ctk.CTkLabel(self.preset_frame, text=t_text("label_presets"), font=("Arial", 12, "bold")).grid(row=0, column=0, columnspan=5, pady=2)

        self.preset_buttons = {}
        self.presets_data = {} 

        for i in range(1, 11):
            row_idx = (i - 1) // 5 + 1
            col_idx = (i - 1) % 5
            
            p_menu = tk.Menu(self, tearoff=0, font=("Arial", 14))
            p_menu.add_command(label=t_text("menu_rename"), command=lambda num=i: self.rename_preset(num))
            p_menu.add_command(label=t_text("menu_delete"), command=lambda num=i: self.clear_preset(num))
            
            # ボタン作成は1回だけ！
            btn = ctk.CTkButton(self.preset_frame, text=f"Preset {i}", height=35, fg_color="transparent", border_width=1)
            btn.grid(row=row_idx, column=col_idx, padx=5, pady=2, sticky="ew")
            
            btn.bind("<ButtonRelease-1>", lambda event, num=i: self.execute_preset(num))
            btn.bind("<Shift-ButtonRelease-1>", lambda event, num=i: self.save_preset(num))
            btn.bind(_RIGHT_CLICK, lambda e, menu=p_menu: menu.tk_popup(e.x_root, e.y_root))
            
            self.preset_buttons[str(i)] = btn

        self.registered_ips = []
        self.projector_cards = []
        self.global_mute_state = False

        self.load_settings() # 起動時にテーマ設定を読み込む
        self.load_devices()
        self.load_presets()

        # 3秒後にステータスを更新
        self.after(1000, self.refresh_all_status)

        # キーボード操作を有効化
        self.bind("<Key>", self.handle_keypress)
        
        
        # ウィンドウを閉じるボタンが押された時の動作を指定
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # ロック対象のウィジェット
        self.sidebar_elements = [
            self.ip_entry, self.scan_btn, self.refresh_all_btn,
            self.btn_mute_on, self.btn_mute_off,
            self.all_input_menu, self.sort_menu, self.manage_menu, self.theme_menu
        ]
        
        for element in self.sidebar_elements:
            try:
                # これが「クリックされた時にフォーカスを奪う」という魔法の言葉です
                element.configure(takefocus=True)
            except:
                pass

    

        # --- スキャンキャンセルのためのフラグ ---
        self.is_scanning = False
        self.cancel_scan = False


        
        # --- 右クリックメニューの設定 (__init__内) ---
        self.context_menu = tk.Menu(self, tearoff=0, font=("Arial", 12))
        self.context_menu.add_command(label=t_text("menu_size_small"), command=lambda: self.change_grid_size("small"))
        self.context_menu.add_command(label=t_text("menu_size_medium"), command=lambda: self.change_grid_size("medium"))
        self.context_menu.add_command(label=t_text("menu_size_large"), command=lambda: self.change_grid_size("large"))

        # 【最終修正】エラーを完全に防ぎつつ、背景の全レイヤーに「ボタンを離した時」のイベントを張る
        bg_widgets = [
            self.scroll_frame, 
            getattr(self.scroll_frame, "_parent_canvas", None), 
            getattr(self.scroll_frame, "_parent_frame", None)
        ]
        
        for w in bg_widgets:
            if w:  # 存在するパーツにだけバインドする（これでAttributeErrorは絶対に出ません）
                w.bind(_RIGHT_CLICK, self.show_context_menu)         # Windows/macOS/Linux対応
                w.bind("<ButtonRelease-2>", self.show_context_menu)  # Mac用（中ボタン）



    def _get_icons(self, size):
        """指定サイズの CTkImage アイコンセットを返す"""
        return {
            key: ctk.CTkImage(light_image=img, dark_image=img, size=size)
            for key, img in self._raw_images.items()
        }

    def show_all_power_menu(self, event):
        # フォーカス移動はメニューを閉じてしまう原因になるため外します
        self.all_power_menu.tk_popup(event.x_root, event.y_root)

    

    def change_grid_size(self, size_key):
        # サイズを更新して、メインエリアを再描画する
        self.current_size = size_key
        self.render_projectors()


    
    def render_projectors(self):
        """2. カードを現在のサイズ設定で生成し直す"""
        if not self.projector_cards:
            return

        # 1. 現在画面にあるカードから、(ip, name) データを一時退避
        old_devices = []
        for c in self.projector_cards:
            old_devices.append({"ip": c.ip, "name": c.name})

        # 2. 【重要修正】土台（キャンバス）を巻き添えにしないよう、管理リストのカードだけを削除
        for card in self.projector_cards:
            if card.winfo_exists():
                card.destroy()
        
        # 3. 管理リストを一度空にする
        self.projector_cards = []
        self.registered_ips = []

        # 現在のサイズ設定を取得
        config = self.grid_configs[self.current_size]

        # 4. 退避したデータから、新しいサイズでカードを再生成
        for dev in old_devices:
            if dev["ip"] == "spacer":
                card = SpacerCard(self.scroll_frame, delete_cb=self.remove_projector)
                card.configure(width=config["width"], height=config["height"])
                self.projector_cards.append(card)
            else:
                self.add_projector(dev["ip"], dev["name"], save=False)
        
        # 5. 現在のウィンドウ幅に合わせて列数を再計算
        current_width = self.scroll_frame.winfo_width()
        self.current_columns = max(1, current_width // config["col_width"])
        
        # 列数のグリッドウェイトをリセットして再設定
        for i in range(20):
            self.scroll_frame.grid_columnconfigure(i, weight=0)
        for i in range(self.current_columns):
            self.scroll_frame.grid_columnconfigure(i, weight=1)

        # 再配置を実行
        self.rearrange_grid()



    def show_context_menu(self, event):
        # 【修正】post()ではなく、他のカードと同じ tk_popup() を使います
        self.context_menu.tk_popup(event.x_root, event.y_root)



    def get_local_prefix(self):
        """自身のIPアドレスを取得してサブネットプレフィックスを返す"""
        try:
            # 実際にパケットは飛ばさずに、ルートを確認する手法
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            # 最後のドットまでを抽出 (例: 192.168.1.15 -> 192.168.1.)
            return ".".join(local_ip.split(".")[:-1]) + "."
        except:
            # ネットワーク未接続などの場合はデフォルト値を返す
            return "192.168.0."


    def control_all_input(self, choice):
        """全台の入力を一斉に切り替える"""
        self.focus_set()
        mapping = {
            "HDMI 1": ("DIGITAL", 1),
            "HDMI 2": ("DIGITAL", 2),
            "SDI (Digi 3)": ("DIGITAL", 3),
            "VGA (RGB 1)": ("RGB", 1),
            "NETWORK": ("NETWORK", 1),
        }
        if choice in mapping:
            source_type, source_num = mapping[choice]
            for card in self.projector_cards:
                # if card.is_targeted.get(): ← これを削除！
                card.set_input_source(source_type, source_num)
        
        # 選択後に表示をリセット
        self.all_input_menu.set("Input Select")
        
    def handle_sort_menu(self, choice):
        self.focus_set()
        if not self.projector_cards: return

        # 追加: JSONから選択肢を取得
        options = _translations.get("sort_options", [])

        if choice == options[0]: # IPアドレス順
            self.projector_cards.sort(key=lambda x: [int(part) for part in x.ip.split('.') if part.isdigit()] if x.ip != "spacer" else [999, 999, 999, 999])
            self.rearrange_grid()
            self.save_devices()
        elif choice == options[1]: # 名前順
            self.projector_cards.sort(key=lambda x: x.name.lower() if x.ip != "spacer" else "zzzzzz")
            self.rearrange_grid()
            self.save_devices()
        elif choice == options[2]: # 手動設定
            self.open_manual_sort_dialog()
        
        self.sort_menu.set(t_text("menu_sort"))

    def load_settings(self):
        theme = "Light"  # デフォルト値
        last_prefix = self.get_local_prefix()
        
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    s = json.load(f)
                    theme = s.get("theme", "Light") # "Dark" または "Light" を取得
                    last_prefix = s.get("last_prefix", last_prefix)
                    geo = s.get("geometry")
                    if geo: self.geometry(geo)
            except: pass
        
        # 保存されていたテーマコードを直接適応
        ctk.set_appearance_mode(theme)
        self.theme_menu.set(t_text("menu_theme"))
        
        self.ip_entry.delete(0, 'end')
        self.ip_entry.insert(0, last_prefix)

    def save_current_settings(self, theme_choice=None):
        if theme_choice is None:
            # アプリを閉じる時は、CustomTkinterの現在の状態（"Dark" または "Light"）をそのまま使う
            theme_choice = ctk.get_appearance_mode()
        
        current_ip_text = self.ip_entry.get().strip()
        prefix = "192.168.0."

        if "." in current_ip_text:
            prefix = ".".join(current_ip_text.split(".")[:-1]) + "."

        settings = {
            "theme": theme_choice,     # ここに "Dark" または "Light" が綺麗に入ります
            "geometry": self.geometry(),
            "last_prefix": prefix,
            "lang": _current_lang      # 前回のグローバル変数化もここに適用！
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
        except: pass

    def change_theme(self, choice, save=True):
        self.focus_set()
        
        # JSONから現在の言語の選択肢（["ライトモード", "ダークモード"] など）を取得
        options = _translations.get("theme_options", ["Light Mode", "Dark Mode"])
        
        # 配列の1番目（ダークモード / Dark Mode）が選ばれたかどうかでカチッと判定
        if choice == options[1]:
            mode = "Dark"
        else:
            mode = "Light"
            
        ctk.set_appearance_mode(mode)
        
        if save:
            # 設定ファイルには表示文字ではなく、共通コード "Dark" / "Light" を保存する
            self.save_current_settings(mode)
            
        # メニューのタイトルを「テーマ / Theme」に戻す（ここも多言語化）
        self.theme_menu.set(t_text("menu_theme"))

    def rename_preset(self, num):
        num_str = str(num)
        current_name = self.presets_data.get(num_str, {}).get("name", f"Preset {num}")
        dialog = RenameDialog(self, current_name, title_text=f"Preset {num} の名前変更")
        if dialog.result:
            if num_str not in self.presets_data: self.presets_data[num_str] = {"name": "", "data": {}}
            self.presets_data[num_str]["name"] = dialog.result.strip()
            self._update_preset_button_ui(num_str)
            self._save_presets_to_file()

    def save_preset(self, num):
        num_str = str(num)
        # ターゲットにチェックが入っているカードの情報を集める
        p_data = {card.ip: {"mute": card.is_muted} 
                  for card in self.projector_cards if card.is_targeted.get()}
        
        if not p_data:
            messagebox.showwarning(t_text("title_fail"), t_text("msg_fail_target"))
            return

        # --- 上書きを確実にするための処理 ---
        if num_str in self.presets_data:
            # 既存の名前をキープしつつ、データだけを最新にする
            current_name = self.presets_data[num_str].get("name", f"Preset {num}")
            self.presets_data[num_str] = {"name": current_name, "data": p_data}
        else:
            # 新規登録
            self.presets_data[num_str] = {"name": f"Preset {num}", "data": p_data}
            
        self._save_presets_to_file()
        
        # UI更新（関数を呼び出すのではなく、ここで直接色をセットしてみます）
        self._update_preset_button_ui(num_str)
        
        print(f"DEBUG: Preset {num} saved with {len(p_data)} devices.")
        self.status_label.configure(text=f"Preset {num} を登録/上書きしました")

    def execute_preset(self, num):
        """プリセット実行と、ボタンの視覚的フィードバック"""
        print(f"🚀 Executing Preset {num}...")
        
        # --- 1. ボタンを光らせる演出 ---
        btn = self.preset_buttons.get(str(num))
        if btn:
            # 元の色を保存（通常は "transparent"）
            original_color = btn.cget("fg_color")
            # ハイライト色（CustomTkinterの標準ブルーなど）に変える
            btn.configure(fg_color="#1f538d") 
            
            # 200ミリ秒後に元の色に戻す
            self.after(200, lambda: btn.configure(fg_color=original_color))

        # --- 2. 実際のプロジェクター制御（修正版） ---
        num_str = str(num)
        if num_str in self.presets_data:
            # "data" の中に入っている、プロジェクターごとの状態を取り出す
            actions = self.presets_data[num_str].get("data", {})
            
            for ip, state_dict in actions.items():
                # 対象のプロジェクターカードを探す
                target_card = next((c for c in self.projector_cards if c.ip == ip), None)
                if target_card:
                    # 保存されているミュート状態 (True または False) を取り出す
                    is_mute = state_dict.get("mute")
                    
                    if is_mute is not None:
                        # 正しい関数 (set_mute_state) を使って状態を復元する
                        target_card.set_mute_state(is_mute)

    def clear_preset(self, num):
        num_str = str(num)
        if num_str in self.presets_data:
            del self.presets_data[num_str]
            self._save_presets_to_file()
            self._update_preset_button_ui(num_str)

    def load_presets(self):
        if os.path.exists(PRESETS_FILE):
            try:
                with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                    self.presets_data = json.load(f)
                    for num_str in self.presets_data.keys():
                        self._update_preset_button_ui(num_str)
            except: pass

    def _update_preset_button_ui(self, num_str):
        """プリセットボタンの外見を強制的にリフレッシュする"""
        btn = self.preset_buttons.get(num_str)
        if not btn: return

        preset = self.presets_data.get(num_str)
        
        if preset and preset.get("data"):
            name = preset.get("name", f"Preset {num_str}")
            # ★力技：一度透明にしてから青にする（これで確実に描き直されます）
            btn.configure(text=name, fg_color="transparent")
            self.update_idletasks() # 瞬間的に反映
            btn.configure(fg_color="#1565C0")
        else:
            btn.configure(text=f"Preset {num_str}", fg_color="transparent")
        
        self.update_idletasks()

    def _save_presets_to_file(self):
        with open(PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.presets_data, f, ensure_ascii=False, indent=4)

    def rearrange_grid(self):
        # 1. 配置を一旦クリア
        for card in self.projector_cards:
            card.grid_forget()
        
        # 2. 新しい列数で再配置
        for i, card in enumerate(self.projector_cards):
            card.grid(row=i // self.current_columns, 
                      column=i % self.current_columns, 
                      padx=4, pady=4, sticky="nsew")
        
        # 3. ★スクロールエリアの強制更新（これが重要）
        self.scroll_frame.update_idletasks()
        # 内部フレームのサイズを再計算させる「おまじない」
        self.scroll_frame._parent_canvas.configure(scrollregion=self.scroll_frame._parent_canvas.bbox("all"))
            
   # --- 自動リサイズ処理 ---
    def on_frame_resize(self, event):
        # 現在のサイズに応じた列幅を取得して計算
        config = self.grid_configs[self.current_size]
        new_columns = max(1, event.width // config["col_width"])
        
        # 列数が変わった時だけ再配置を実行する
        if self.current_columns != new_columns:
            self.current_columns = new_columns
            
            # 古い列の幅設定を一旦リセット
            for i in range(20):
                self.scroll_frame.grid_columnconfigure(i, weight=0)
            # 新しい列数で均等割りを再設定
            for i in range(self.current_columns):
                self.scroll_frame.grid_columnconfigure(i, weight=1)
                
            self.rearrange_grid()

    def handle_manage_menu(self, choice):
        self.focus_set()
        
        # 言語ファイル（JSON）から選択肢のリストを丸ごと取得
        options = _translations.get("data_options", ["Save Manually", "Initialize Data…"])
        
        # -----------------------------------------------
        # 1. 「手動で保存」 (0番目) が選ばれた場合
        # -----------------------------------------------
        if choice == options[0]:
            self.save_devices()
            self._save_presets_to_file()
            self.save_current_settings()
            # 「保存完了」を多言語化
            self.status_label.configure(text=t_text("status_saved"))
            
        # -----------------------------------------------
        # 2. 「データ初期化…」 (1番目) が選ばれた場合
        # -----------------------------------------------
        elif choice == options[1]:
            # ポップアップのタイトル（警告）とメッセージ（全消去の確認）を多言語化
            title_text = t_text("title_warning")
            confirm_msg = t_text("msg_clear_all_confirm")
            
            if messagebox.askyesno(title_text, confirm_msg, parent=self):
                for card in self.projector_cards:
                    card.destroy()
                self.projector_cards.clear()
                self.registered_ips.clear()
                
                self.presets_data.clear()
                for i in range(1, 11):
                    self._update_preset_button_ui(str(i))
                
                if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
                if os.path.exists(PRESETS_FILE): os.remove(PRESETS_FILE)
                self.rearrange_grid() # 画面を真っさらに
                                
                # 入力欄をリセットして、最新のサブネットを再取得
                self.ip_entry.delete(0, 'end')
                new_prefix = self.get_local_prefix()
                self.ip_entry.insert(0, new_prefix)
                
                # 「初期化しました」を多言語化
                self.status_label.configure(text=t_text("status_initialized"))

        # -----------------------------------------------
        # 3. メニューの表示を元の「データ」という文字に戻す
        # -----------------------------------------------
        self.manage_menu.set(t_text("menu_data"))

    # ▼ 追加：終了時に呼ばれる関数
    def on_closing(self):
        self.save_current_settings() # 位置とサイズを保存
        self.destroy() # アプリを終了

    def handle_keypress(self, event):
        if str(self.focus_get()).find("entry") != -1: return
        char = event.char.lower() if event.char else ""
        
        # 1-9キーでプリセット1-9実行、0キーでプリセット10を実行
        if char in [str(n) for n in range(1, 10)]:
            self.execute_preset(int(char))
        elif char == '0':
            self.execute_preset(10)
            
        elif char == 'm': 
            self.global_mute_state = not self.global_mute_state
            self.control_all_mute(self.global_mute_state)
        elif event.keysym == 'Up': self.control_all_mute(False)
        elif event.keysym == 'Down': self.control_all_mute(True)

    def refresh_all_status(self):
        self.focus_set()
        for card in self.projector_cards:
            # ▼ ここが重要：IPが "spacer" ではない（実機）ときだけ通信する
            if hasattr(card, "ip") and card.ip != "spacer":
                threading.Thread(target=card.fetch_status, daemon=True).start()
        
        self.after(3000, lambda: self.status_label.configure(text=t_text("status_refresh_done")))

    def add_projector(self, ip, name, save=True):
        if ip in self.registered_ips: return 
        
        # 現在のサイズ設定を取得
        config = self.grid_configs[self.current_size]
        
        # ProjectorCardに動的なサイズを渡すように変更
        card = ProjectorCard(
            self.scroll_frame,
            ip,
            name,
            icons=self._get_icons(config["icon_size"]),
            rename_cb=self.save_devices,
            delete_cb=self.remove_projector,
            width=config["width"],
            height=config["height"],
            font_size=config["font_size"],
            btn_height=config["btn_height"]
        )
        self.registered_ips.append(ip); self.projector_cards.append(card)
        self.rearrange_grid()
        if save: self.save_devices()

    def remove_projector(self, card_to_remove):
        card_to_remove.destroy()
        self.projector_cards.remove(card_to_remove); self.registered_ips.remove(card_to_remove.ip)
        self.rearrange_grid(); self.save_devices()

    def load_devices(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for dev in data:
                        if dev["ip"] == "spacer":
                            # 直接リストに追加
                            card = SpacerCard(self.scroll_frame, delete_cb=self.remove_projector)
                            self.projector_cards.append(card)
                        else:
                            self.add_projector(dev["ip"], dev["name"], save=False)
                # 全て読み込んだ後に再配置を呼ぶ
                self.rearrange_grid()
            except: pass

    def save_devices(self):
        # SpacerCardかProjectorCardかを判定して保存
        devices = []
        for c in self.projector_cards:
            devices.append({"ip": c.ip, "name": c.name})
            
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(devices, f, ensure_ascii=False, indent=4)

    def add_manual_ip(self):
        # 1. ロック確認
        if self.lock_switch.get() == 1:
            return

        # 2. フォーカスを一度奪う (OSに入力を確定させるおまじない)
        self.focus_set()
            
        ip = self.ip_entry.get().strip()
        
        # 3. 未入力チェック
        if not ip:
            return

        # 4. IPアドレスの形式チェック (バリデーション)
        is_valid = True
        parts = ip.split('.')
        if len(parts) == 4:
            for part in parts:
                if not part.isdigit() or not (0 <= int(part) <= 255):
                    is_valid = False
                    break
        else:
            is_valid = False

        if not is_valid:
            import tkinter.messagebox as messagebox
            messagebox.showerror(
                t_text("title_input_error"), 
                t_text("msg_ip_error").format(ip=ip), 
                parent=self
            )
            # エラーの時は、打ち直ししやすいように入力欄にフォーカスを戻して終了
            self.after(50, lambda: (self.ip_entry.focus_set(), self.ip_entry.icursor('end')))
            return

        # --- 以下、正常な場合の処理 ---

        # 5. 次回のためのプレフィックス抽出
        prefix = ".".join(parts[:-1]) + "."

        # 6. 入力欄のリセットと再入力
        self.ip_entry.delete(0, 'end')
        self.ip_entry.insert(0, prefix)
        
        # 7. 連続入力のためにフォーカスを戻す
        self.after(50, lambda: (self.ip_entry.focus_set(), self.ip_entry.icursor('end')))

        # 8. 追加・探査処理の実行
        import threading
        threading.Thread(target=self._fetch_name_and_add, args=(ip,), daemon=True).start()
        
        # 設定を保存
        self.save_current_settings()
        
    def _refocus_entry(self):
        self.ip_entry.focus_set()
        self.ip_entry.icursor('end')

    def _fetch_name_and_add(self, ip):
        import socket
        name = t_text("status_unknown")
        is_success = False
        
        # 一時的に全体の通信タイムアウトを 2秒 に設定する（フリーズ防止）
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(2.0)
        
        try:
            # ▼ 修正：timeout=2.0 を削除
            pj = Projector.from_address(ip)
            pj.authenticate(None)
            
            # 先ほどの修正通り、get('NAME') を使う
            name = pj.get('NAME') or "Projector"
            is_success = True
        except Exception as e:
            # 原因が分かったので、print部分は残しても消してもOKです
            name = t_text("status_manual_device")
            is_success = False
        finally:
            # 最後に、タイムアウトの設定を元の状態にきっちり戻す
            socket.setdefaulttimeout(old_timeout)

        self.after(0, lambda: self._handle_add_result(ip, name, is_success))

    def _handle_add_result(self, ip, name, is_success):
        """通信結果を受けて、カードの追加とステータスバーの表示を行う"""
        self.add_projector(ip, name)
        
        if is_success:
            self.status_label.configure(text=f"'{name}' を追加しました", text_color="gray")
            self.status_label.configure(text=t_text("msg_added").format(name=name), text_color="gray")
        else:
            # 応答がなかった場合はオレンジ色などで警告っぽく表示
            self.status_label.configure(text=t_text("msg_no_response"), text_color="#E64A19")
            # 3秒後に文字色を標準（gray）に戻す
            self.after(3000, lambda: self.status_label.configure(text_color="gray"))



    def start_scan(self):
        self.focus_set()
        
        # ▼ すでに探査中ならキャンセル処理をして終了する
        if self.is_scanning:
            self.cancel_scan = True
            self.scan_btn.configure(text=t_text("btn_scan_stopping"), state="disabled")
            self.status_label.configure(text=t_text("status_canceling"))
            return

        # ▼ ここから通常の探査開始処理
        self.is_scanning = True
        self.cancel_scan = False
        
        self.set_sidebar_state("disabled")
        self.lock_switch.configure(state="disabled")
        
        # 探査ボタンだけは「キャンセルボタン」として押せるように復活させる！
        self.scan_btn.configure(state="normal", text=t_text("btn_scan_stop"), fg_color="#C62828")
        self.status_label.configure(text=t_text("status_scanning")) 
        
        threading.Thread(target=self._scan_network, daemon=True).start()



    def _scan_network(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80))
            base_ip = ".".join(s.getsockname()[0].split(".")[:-1]) + "."; s.close()
        except: base_ip = "192.168.1."
        found = []
        for i in range(1, 255):
            # ▼ もし「キャンセルボタン」が押されていたら、ループを強制脱出！
            if self.cancel_scan:
                break
                
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.05)
                if s.connect_ex((f"{base_ip}{i}", 4352)) == 0: found.append(f"{base_ip}{i}")
        
        self.after(0, self._finish_scan, found)

    def _finish_scan(self, found):
        # 状態を元に戻す
        self.is_scanning = False
        self.lock_switch.configure(state="normal")
        if self.lock_switch.get() == 0:
            self.set_sidebar_state("normal")
            
        # ボタンの見た目を「探査」に戻す
        self.scan_btn.configure(state="normal", text=t_text("btn_scan"), fg_color="#2E7D32")
        
        # キャンセルされたか、完走したかでステータス表示を分ける
        if self.cancel_scan:
            self.status_label.configure(text=t_text("status_scan_canceled"))
            self.cancel_scan = False
        else:
            self.status_label.configure(text=t_text("status_scan_done"))
            for ip in found: threading.Thread(target=self._fetch_name_and_add, args=(ip,), daemon=True).start()


        
    def open_manual_sort_dialog(self):
        dialog = ManualSortDialog(self, self.projector_cards)
        self.wait_window(dialog)
        
        if dialog.applied:
            new_cards = []
            # 現在画面にある全てのカード（Spacer含む）を一旦把握
            current_all_cards = self.projector_cards[:]
            
            for item in dialog.result_list:
                # 既存のカード（実体があるもの）
                if hasattr(item, 'winfo_id') and item.winfo_exists():
                    new_cards.append(item)
                    if item in current_all_cards:
                        current_all_cards.remove(item)
                else:
                    # 新しく追加された空白ダミーオブジェクトなら実体化
                    new_cards.append(SpacerCard(self.scroll_frame, delete_cb=self.remove_projector))
            
            # リストから漏れた（＝ダイアログで×を押された）カードを破壊してメモリから消す
            for old_card in current_all_cards:
                old_card.destroy()
            
            self.projector_cards = new_cards
            self.registered_ips = [c.ip for c in self.projector_cards if c.ip != "spacer"]
            
            self.rearrange_grid()
            self.save_devices()
            self.status_label.configure(text=t_text("status_sort_applied"))

    def control_all_power(self, command):
        if command == "Power ON":
            self.power_label.configure(fg_color="#28a745", text=t_text("menu_power_on"))
        else:
            self.power_label.configure(fg_color="#dc3545", text=t_text("menu_power_off"))

        for card in self.projector_cards:
            # 空白カードはスキップ
            if card.ip != "spacer":
                card.control_power(command)

    def control_all_mute(self, is_mute):
        self.focus_set()
        if is_mute:
            self.btn_mute_on.configure(fg_color="#FF0000") 
            self.btn_mute_off.configure(fg_color="#444444") 
        else:
            self.btn_mute_on.configure(fg_color="#631414") 
            self.btn_mute_off.configure(fg_color="gray")

        for card in self.projector_cards:
            # 空白カードはスキップ
            if card.ip != "spacer":
                card.set_mute_state(is_mute)


    def start_remote_listeners(self):
        """UDPとTCPのリスナーを別スレッドで開始"""
        threading.Thread(target=self.udp_listener_loop, daemon=True).start()
        threading.Thread(target=self.tcp_listener_loop, daemon=True).start()

    def process_command(self, data):
        """受信した文字列を解析して実行する共通処理"""
        try:
            cmd = data.decode("utf-8").strip().lower()
            print(f"📥 Remote Command: {cmd}")

            # プリセット実行 (例: "preset 1" または "p1")
            if cmd.startswith("preset") or cmd.startswith("p"):
                num_str = cmd.replace("preset", "").replace("p", "").strip()
                if num_str.isdigit():
                    num = int(num_str)
                    if 1 <= num <= 10:
                        self.after(0, lambda n=num: self.execute_preset(n))

            # 一括ミュート (例: "mute on", "mute off")
            elif cmd == "mute on":
                self.after(0, lambda: self.control_all_mute(True))
            elif cmd == "mute off":
                self.after(0, lambda: self.control_all_mute(False))

            # 一括電源 (例: "all power on", "all power off")
            elif cmd == "all power on":
                self.after(0, lambda: self.control_all_power("Power ON"))
            elif cmd == "all power off":
                self.after(0, lambda: self.control_all_power("Power OFF"))

        except Exception as e:
            print(f"⚠️ Command Error: {e}")

    def udp_listener_loop(self):
        """UDPサーバー: 軽い制御用 (StreamDeck等)"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", self.udp_port))
        while True:
            data, addr = sock.recvfrom(1024)
            self.process_command(data)

    def tcp_listener_loop(self):
        """TCPサーバー: 確実な通信用"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("0.0.0.0", self.tcp_port))
        server.listen(5)
        while True:
            conn, addr = server.accept()
            data = conn.recv(1024)
            if data:
                self.process_command(data)
            conn.close()
            
    def toggle_manual_lock(self):
        """スイッチの状態でサイドバーをロック/解除"""
        if self.lock_switch.get() == 1:
            self.set_sidebar_state("disabled")
            self.status_label.configure(text=t_text("status_locked"), text_color="#FF5252")
        else:
            self.set_sidebar_state("normal")
            self.status_label.configure(text=t_text("status_idle"), text_color="gray")

    def set_sidebar_state(self, state="normal"):
        """一括切り替え（ラベルのバインド解除も考慮）"""
        for element in self.sidebar_elements:
            try:
                element.configure(state=state)
            except:
                pass

        # --- Powerラベル（Label）のクリック無効化 ---
        if state == "disabled":
            self.power_label.unbind("<ButtonRelease-1>")
            self.power_label.configure(cursor="arrow", fg_color="#37474F") # 色を暗くして無効感を出す
        else:
            self.power_label.configure(cursor="hand2", fg_color="#1f538d")

    # 多言語化用2つのメソッド        
    def preload_language(self):
        """起動時に設定を読み込み、グローバル翻訳辞書を書き換える"""
        global _translations, _current_lang
        
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    s = json.load(f)
                    _current_lang = s.get("lang", "ja")
            except: pass
        
        json_path = resource_path(f"locale/{_current_lang}.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    _translations = json.load(f)
            except:
                _translations = {}

    def change_language_setting(self, choice):
        global _current_lang

        self.focus_set()
        new_lang = "ja" if choice == "日本語" else "en"
        
        if new_lang == _current_lang:
            return

        _current_lang = new_lang

        # settings.json を読み込んで、言語だけを書き換えて保存
        settings = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    settings = json.load(f)
            except: pass
            
        settings["lang"] = new_lang
        
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
        except: pass
        
        # カスタムダイアログで通知
        self._show_restart_dialog()
        
        self.lang_menu.set(t_text("menu_lang"))

    def _show_restart_dialog(self):
        """キャンセル / 再起動のカスタムダイアログ"""
        dialog = ctk.CTkToplevel(self)
        dialog.title(t_text("msg_restart_title"))

        self.update_idletasks()
        dw, dh = 320, 140
        px = self.winfo_rootx() + (self.winfo_width()  - dw) // 2
        py = self.winfo_rooty() + (self.winfo_height() - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{px}+{py}")

        dialog.transient(self)
        dialog.grab_set()
        dialog.after(100, dialog.lift)

        ctk.CTkLabel(dialog, text=t_text("msg_restart_text"), wraplength=280, justify="center").pack(pady=(18, 8), padx=16)

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=(0, 12))
        ctk.CTkButton(btn_frame, text=t_text("btn_cancel"),  width=110, fg_color="gray",
                      command=dialog.destroy).pack(side="left", padx=8)
        ctk.CTkButton(btn_frame, text=t_text("btn_restart", "再起動"), width=110,
                      command=lambda: self._do_restart(dialog)).pack(side="left", padx=8)

        dialog.wait_window()

    def _do_restart(self, dialog=None):
        """アプリを再起動する"""
        if dialog and dialog.winfo_exists():
            dialog.destroy()
        self.save_current_settings()
        # EXE化時は sys.executable のみ、通常実行時は引数付きで起動
        args = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable] + sys.argv
        self.destroy()
        os.execv(sys.executable, args)

if __name__ == "__main__":
    app = App()
    app.mainloop()