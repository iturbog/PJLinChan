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

VERSION = "0.2"



# pyinstaller --noconsole --onefile --name "PJリンちゃん_v0.2" --icon="image/icon.ico" --add-data "image;image" main.py
#
# python -m venv .venv
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
# .\.venv\Scripts\Activate.ps1
# pip install customtkinter pypjlink pillow



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

# --- 設定ファイル ---
CONFIG_FILE = "projectors.json"
PRESETS_FILE = "presets.json"
SETTINGS_FILE = "settings.json"

# GUIのテーマ設定 (デフォルトをライトモードに変更)
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

def load_or_create_dummy_image(filename, size=(120, 90)):
    # ▼ 追加：PyInstaller対応のパスに変換
    target_path = resource_path(filename)
    
    try:
        # filename ではなく target_path を開くように変更
        img = Image.open(target_path)
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        img = Image.new('RGBA', size, (80, 80, 80, 150))
        d = ImageDraw.Draw(img)
        # エラー表示用にパスも出しておくとデバッグが楽です
        d.text((5, size[1]//2 - 10), f"Missing:\n{filename}", fill="white")
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)

class RenameDialog(ctk.CTkToplevel):
    """名前変更用のカスタムダイアログ"""
    def __init__(self, parent, current_name, title_text="名前の変更"):
        super().__init__(parent)
        self.title(title_text)
        self.result = None
        
        parent.update_idletasks()
        dialog_w = 300
        dialog_h = 150
        pos_x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (dialog_w // 2)
        pos_y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (dialog_h // 2)
        self.geometry(f"{dialog_w}x{dialog_h}+{pos_x}+{pos_y}")
        
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(self, text="新しい名前を入力してください:").pack(pady=(15, 5))
        
        self.entry = ctk.CTkEntry(self, width=200)
        self.entry.pack(pady=5)
        self.entry.insert(0, current_name)
        self.entry.select_range(0, 'end')
        self.entry.focus_set()

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="キャンセル", width=80, fg_color="gray", command=self.destroy).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="OK", width=80, command=self.on_ok).pack(side="left", padx=5)
        
        self.bind("<Return>", lambda event: self.on_ok())
        self.wait_window()

    def on_ok(self):
        self.result = self.entry.get()
        self.destroy()

class ProjectorCard(ctk.CTkFrame):
    """プロジェクター1台分の操作パネル"""
    def __init__(self, master, ip, name, icons, password=None, rename_cb=None, delete_cb=None):
        super().__init__(master)
        self.ip = ip
        self.name = name
        self.password = password
        self.icons = icons 
        self.rename_cb = rename_cb
        self.delete_cb = delete_cb
        self.is_muted = False
        self.power_state = "off"
        self.is_offline = True 

        # --- UI配置 ---
        self.is_targeted = ctk.BooleanVar(value=True)
        self.target_chk = ctk.CTkCheckBox(self, text="Target", variable=self.is_targeted, width=20, font=("Arial", 11))
        self.target_chk.pack(pady=(5, 0))

        # アイコンボタン (ここでの右クリックは「電源・管理」)
        self.icon_btn = ctk.CTkButton(self, text="", image=self.icons["offline"], width=80, height=60, 
                                      fg_color="transparent", hover_color="#37474F")
        self.icon_btn.pack(pady=2, padx=10)
        
        # 左クリック（離した瞬間）でミュート切り替え
        self.icon_btn.bind("<ButtonRelease-1>", lambda e: self.toggle_mute())

        # 情報ラベル (ここでの右クリックは「入力切替」)
        self.label = ctk.CTkLabel(self, text=f"{self.name}\n({self.ip})", 
                                  font=("Arial", 12, "bold"), justify="center", cursor="hand2")
        self.label.pack(pady=(0, 5))

        # --- 1. 管理メニュー (アイコン右クリック用) ---
        self.context_menu = tk.Menu(self, tearoff=0, font=("Arial", 14))
        self.context_menu.add_command(label="⚡ Power ON", command=lambda: self.control_power("Power ON"))
        self.context_menu.add_command(label="💤 Power OFF", command=lambda: self.control_power("Power OFF"))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="✏️ 名前の変更", command=self.rename_device)
        self.context_menu.add_command(label="❌ 削除", command=self.delete_device)

        # --- 2. 入力切替メニュー (ラベル右クリック用) ---
        self.input_menu = tk.Menu(self, tearoff=0, font=("Arial", 12))
        self.input_menu.add_command(label="HDMI 1", command=lambda: self.set_input_source("DIGITAL", 1))
        self.input_menu.add_command(label="HDMI 2", command=lambda: self.set_input_source("DIGITAL", 2))
        self.input_menu.add_command(label="SDI (Digi 3)", command=lambda: self.set_input_source("DIGITAL", 3))
        self.input_menu.add_separator()
        self.input_menu.add_command(label="VGA (RGB 1)", command=lambda: self.set_input_source("RGB", 1))

        # --- ★マウスバインドの最終整理★ ---
        
        # アイコンを右クリックした時だけ「電源管理」を出す
        self.icon_btn.bind("<ButtonRelease-3>", self.show_context_menu)
        
        # ラベルを右クリックした時は「入力切替」を出す
        self.label.bind("<ButtonRelease-3>", self.show_input_menu)
        
        # (念のため) ラベルを左クリックしても入力切替が出るようにしておきます
        self.label.bind("<ButtonRelease-1>", self.show_input_menu)

    def show_context_menu(self, event):
        """電源・管理メニューを表示"""
        self.context_menu.tk_popup(event.x_root, event.y_root)

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
        if messagebox.askyesno("削除", f"'{self.name}' を削除しますか？"):
            if self.delete_cb: self.delete_cb(self)

    def _update_ui_states(self):
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

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"PJリンちゃん {VERSION} - PJLink Multi-Controller -")
        self.geometry("1150x850")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # --- リモート制御設定 ---
        self.udp_port = 5000
        self.tcp_port = 5001
        self.start_remote_listeners()

        # PJアイコン
        icon_size = (80, 60)
        self.icons = {
            "offline": load_or_create_dummy_image("image/icon_offline.png", icon_size),
            "power_off": load_or_create_dummy_image("image/icon_power_off.png", icon_size),
            "power_on_muted": load_or_create_dummy_image("image/icon_power_on_muted.png", icon_size),
            "power_on_projecting": load_or_create_dummy_image("image/icon_power_on_projecting.png", icon_size),
        }

        # -----------------------------------
        # 1. サイドバー
        # -----------------------------------
        self.sidebar = ctk.CTkFrame(self, width=110, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_rowconfigure(10, weight=1)

        ctk.CTkLabel(self.sidebar, text="管理", font=("Arial", 14, "bold")).grid(row=0, column=0, padx=5, pady=(15, 5))
        self.ip_entry = ctk.CTkEntry(self.sidebar, placeholder_text="IP")
        self.ip_entry.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        
        btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=5, pady=5, sticky="ew")
        btn_frame.grid_columnconfigure((0,1), weight=1)
        ctk.CTkButton(btn_frame, text="追加", command=self.add_manual_ip, width=40).grid(row=0, column=0, padx=(0,2))
        self.scan_btn = ctk.CTkButton(btn_frame, text="探査", fg_color="#2E7D32", command=self.start_scan, width=40)
        self.scan_btn.grid(row=0, column=1, padx=(2,0))

        self.refresh_all_btn = ctk.CTkButton(self.sidebar, text="🔄 更新", fg_color="#546E7A", command=self.refresh_all_status)
        self.refresh_all_btn.grid(row=3, column=0, padx=10, pady=5, sticky="ew")
        
        self.status_label = ctk.CTkLabel(self.sidebar, text="待機中", text_color="gray", font=("Arial", 11))
        self.status_label.grid(row=4, column=0, padx=5, pady=0)

        ctk.CTkLabel(self.sidebar, text="一括", font=("Arial", 14, "bold")).grid(row=5, column=0, padx=5, pady=(20, 5))

        # --- 1. 全台電源制御：ラベル ＋ ポップアップメニュー ---
        self.power_label = ctk.CTkLabel(self.sidebar, text="Power", 
                                        fg_color="#1f538d", corner_radius=6, height=35,
                                        font=("Arial", 13, "bold"), cursor="hand2")
        self.power_label.grid(row=6, column=0, padx=10, pady=5, sticky="ew")
        
        # メニューの中身を作成
        self.all_power_menu = tk.Menu(self, tearoff=0, font=("Arial", 12))
        self.all_power_menu.add_command(label="⚡ ALL Power ON", command=lambda: self.control_all_power("Power ON"))
        self.all_power_menu.add_command(label="💤 ALL Power OFF", command=lambda: self.control_all_power("Power OFF"))
        
        # ラベルをクリックした時にメニューを出す設定
        self.power_label.bind("<ButtonRelease-1>", lambda e: self.all_power_menu.tk_popup(e.x_root, e.y_root))


        # Mute ONボタンを「self.btn_mute_on」という名前で作成して配置
        self.btn_mute_on = ctk.CTkButton(self.sidebar, text="Mute ON", fg_color="#C62828")
        self.btn_mute_on.bind("<ButtonRelease-1>", lambda event: self.control_all_mute(True))
        self.btn_mute_on.grid(row=7, column=0, padx=10, pady=5, sticky="ew")

        # Mute OFFボタンを「self.btn_mute_off」という名前で作成して配置
        self.btn_mute_off = ctk.CTkButton(self.sidebar, text="Mute OFF", fg_color="gray")
        self.btn_mute_off.bind("<ButtonRelease-1>", lambda event: self.control_all_mute(False))
        self.btn_mute_off.grid(row=8, column=0, padx=10, pady=5, sticky="ew")


        self.manage_menu = ctk.CTkOptionMenu(self.sidebar, values=["手動で保存", "データ初期化"], command=self.handle_manage_menu)
        self.manage_menu.set("データ")
        self.manage_menu.grid(row=11, column=0, padx=10, pady=(0, 5), sticky="ew")


        # テーマ切り替えメニュー (選択肢を2つに変更)
        self.theme_menu = ctk.CTkOptionMenu(self.sidebar, values=["ライトモード", "ダークモード"], command=self.change_theme)
        self.theme_menu.grid(row=12, column=0, padx=10, pady=(0, 20), sticky="ew")

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
        
        ctk.CTkLabel(self.preset_frame, text="PRESETS (1-5 / 6-0):", font=("Arial", 12, "bold")).grid(row=0, column=0, columnspan=5, pady=2)

        self.preset_buttons = {}
        self.presets_data = {} 

        for i in range(1, 11):
            # 1-5は1行目、6-10は2行目に配置
            row_idx = (i - 1) // 5 + 1
            col_idx = (i - 1) % 5
            
            btn = ctk.CTkButton(self.preset_frame, text=f"Preset {i}", height=35, fg_color="transparent", border_width=1, 
                                command=lambda num=i: self.execute_preset(num))
            btn.grid(row=row_idx, column=col_idx, padx=5, pady=2, sticky="ew")
            
            p_menu = tk.Menu(self, tearoff=0, font=("Arial", 14))
            p_menu.add_command(label="✏️ 名前の変更", command=lambda num=i: self.rename_preset(num))
            p_menu.add_command(label="❌ 登録を解除", command=lambda num=i: self.clear_preset(num))
            
            # command=... を消して、すべて bind に集約します
            btn = ctk.CTkButton(self.preset_frame, text=f"Preset {i}", height=35, fg_color="transparent", border_width=1)
            btn.grid(row=row_idx, column=col_idx, padx=5, pady=2, sticky="ew")
            
            # 左クリック（離して実行）
            btn.bind("<ButtonRelease-1>", lambda event, num=i: self.execute_preset(num))
            # Shift+左クリック（離して登録・上書き）
            btn.bind("<Shift-ButtonRelease-1>", lambda event, num=i: self.save_preset(num))
            # 右クリック（離してメニュー表示）
            btn.bind("<ButtonRelease-3>", lambda e, menu=p_menu: menu.tk_popup(e.x_root, e.y_root))
            
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
        
        # サイドバーの一括操作セクション
        ctk.CTkLabel(self.sidebar, text="一括", font=("Arial", 14, "bold")).grid(row=5, column=0, padx=5, pady=(20, 5))
        
        # --- [新規] 一括入力切替メニュー ---
        self.all_input_menu = ctk.CTkOptionMenu(
            self.sidebar, 
            values=["HDMI 1", "HDMI 2", "SDI (Digi 3)", "VGA (RGB 1)", "NETWORK"], 
            command=self.control_all_input
        )
        self.all_input_menu.set("Input Select")
        self.all_input_menu.grid(row=9, column=0, padx=10, pady=5, sticky="ew") # 位置は既存ボタンの下へ
        
        #####

        # ウィンドウを閉じるボタンが押された時の動作を指定
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def control_all_input(self, choice):
        """全台の入力を一斉に切り替える"""
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

    # --- テーマ設定の保存と読み込み ---
    def load_settings(self):
        theme = "ライトモード"
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    s = json.load(f)
                    theme = s.get("theme", "ライトモード")
                    
                    # ▼ 修正：ジオメトリ文字列をそのまま復元する
                    # これによりスケーリングによる「サイズの肥大化」を防ぎます
                    geo = s.get("geometry")
                    if geo:
                        self.geometry(geo)
            except: pass
        
        self.theme_menu.set(theme)
        self.change_theme(theme, save=False)

    def save_current_settings(self, theme_choice=None):
        """現在のテーマとウィンドウのジオメトリを保存する"""
        if theme_choice is None:
            theme_choice = self.theme_menu.get()
            
        # ▼ 修正：winfo_widthなどを使う代わりに self.geometry() で
        # 現在の状態を文字列（"幅x高さ+X+Y"）として取得します。
        # これが読み込み時と最も整合性が取れる値です。
        settings = {
            "theme": theme_choice,
            "geometry": self.geometry() 
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
        except: pass

    def change_theme(self, choice, save=True):
        if choice == "ダークモード":
            ctk.set_appearance_mode("Dark")
        else:
            ctk.set_appearance_mode("Light")
        if save:
            self.save_current_settings(choice)

    # --- 以下、ロジック変更なし ---
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
            messagebox.showwarning("登録失敗", "対象(Target)にチェックが入っているプロジェクターがありません。")
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
        # ▼ 変更点: 4ではなく、自動計算された列数で並べ替える
        for i, card in enumerate(self.projector_cards):
            card.grid_forget()
            card.grid(row=i // self.current_columns, column=i % self.current_columns, padx=8, pady=8, sticky="nsew")
            
    # --- 自動リサイズ処理 ---
    def on_frame_resize(self, event):
        # フレームの幅から列数を計算（カード幅120px + 余白 = 約170px と想定）
        new_columns = max(1, event.width // 170)
        
        # 列数が変わった時だけ再配置を実行する（処理を軽くするため）
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
        if choice == "手動で保存":
            self.save_devices()
            self._save_presets_to_file()
            self.save_current_settings()
            self.status_label.configure(text="保存完了")
            
        elif choice == "データ初期化":
            # 1. ユーザーに最終確認
            if messagebox.askyesno("警告", "すべてのプロジェクターとプリセットを消去します。\n本当によろしいですか？"):
                
                # 2. 画面からプロジェクターのカードをすべて消去
                for card in self.projector_cards:
                    card.destroy()
                self.projector_cards.clear()
                self.registered_ips.clear()
                
                # 3. プリセットデータを空にして、ボタンの見た目をリセット
                self.presets_data.clear()
                for i in range(1, 11):
                    self._update_preset_button_ui(str(i), False)
                
                # 4. 保存されているJSONファイルを削除
                if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
                if os.path.exists(PRESETS_FILE): os.remove(PRESETS_FILE)
                
                self.status_label.configure(text="初期化しました")

        # 5. メニューの表示を「データ」に戻す
        self.manage_menu.set("データ")

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
        for card in self.projector_cards: threading.Thread(target=card.fetch_status, daemon=True).start()
        self.after(3000, lambda: self.status_label.configure(text="更新完了"))

    def add_projector(self, ip, name, save=True):
        if ip in self.registered_ips: return 
        card = ProjectorCard(self.scroll_frame, ip, name, icons=self.icons, rename_cb=self.save_devices, delete_cb=self.remove_projector)
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
                    for dev in json.load(f): self.add_projector(dev["ip"], dev["name"], save=False)
            except: pass

    def save_devices(self):
        devices = [{"ip": c.ip, "name": c.name} for c in self.projector_cards]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(devices, f, ensure_ascii=False, indent=4)

    def add_manual_ip(self):
        ip = self.ip_entry.get().strip()
        if ip: 
            self.ip_entry.delete(0, 'end')
            threading.Thread(target=self._fetch_name_and_add, args=(ip,), daemon=True).start()
            
        # ▼ 追加：処理の後にフォーカスをメイン画面（self）に逃がす
        self.focus_set()

    def _fetch_name_and_add(self, ip):
        name = "不明"
        try:
            pj = Projector.from_address(ip); pj.authenticate(None)
            name = pj.get_name() or "Projector"
        except: name = "Manual Device"
        self.after(0, self.add_projector, ip, name)

    def start_scan(self):
        self.scan_btn.configure(state="disabled"); self.status_label.configure(text="探査中...") 
        threading.Thread(target=self._scan_network, daemon=True).start()

    def _scan_network(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80))
            base_ip = ".".join(s.getsockname()[0].split(".")[:-1]) + "."; s.close()
        except: base_ip = "192.168.1."
        found = []
        for i in range(1, 255):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.05)
                if s.connect_ex((f"{base_ip}{i}", 4352)) == 0: found.append(f"{base_ip}{i}")
        self.after(0, self._finish_scan, found)

    def _finish_scan(self, found):
        self.scan_btn.configure(state="normal"); self.status_label.configure(text=f"{len(found)}台発見")
        for ip in found: threading.Thread(target=self._fetch_name_and_add, args=(ip,), daemon=True).start()

    def control_all_power(self, command):
        """全台電源制御：ラベルの色をステータスとして使う"""
        if command == "Power ON":
            self.power_label.configure(fg_color="#28a745", text="⚡ Power: ON")
        else:
            self.power_label.configure(fg_color="#dc3545", text="💤 Power: OFF")

        for card in self.projector_cards:
            # if card.is_targeted.get(): ← これを削除！
            card.control_power(command)


    def control_all_mute(self, is_mute):
        """全台のミュート制御と、サイドバーボタンの見た目を更新"""
        
        # --- 1. サイドバーボタンの色を更新（視覚フィードバック） ---
        if is_mute:
            self.btn_mute_on.configure(fg_color="#FF0000") 
            self.btn_mute_off.configure(fg_color="#444444") 
        else:
            self.btn_mute_on.configure(fg_color="#631414") 
            self.btn_mute_off.configure(fg_color="gray")

        # --- 2. 実際のプロジェクターへの命令 ---
        for card in self.projector_cards:
            # チェックボックスに関係なく全台に命令！
            # さらに、子カードの正しい関数名「set_mute_state」を呼び出す
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
            

if __name__ == "__main__":
    app = App()
    app.mainloop()