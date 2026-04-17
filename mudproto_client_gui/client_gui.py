import asyncio
import ctypes
import json
import os
import ssl
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from datetime import datetime, timezone
from typing import Any, TypeAlias

import websockets


Part: TypeAlias = dict[str, Any]
Line: TypeAlias = list[Part]


COLOR_MAP = {
    "black": "#000000",
    "red": "#c50f1f",
    "green": "#13a10e",
    "yellow": "#c19c00",
    "orange": "#ff8c00",
    "blue": "#0037da",
    "magenta": "#881798",
    "cyan": "#3a96dd",
    "white": "#cccccc",
    "bright_black": "#767676",
    "bright_red": "#e74856",
    "bright_green": "#16c60c",
    "bright_yellow": "#f9f1a5",
    "bright_blue": "#3b78ff",
    "bright_magenta": "#b4009e",
    "bright_cyan": "#61d6d6",
    "bright_white": "#f2f2f2",
}

RECONNECT_INTERVAL_MS = 5000
OUTPUT_RIGHT_MARGIN_PX = 80
MENU_BAR_PADX = 8
MENU_BAR_PADY = 6
MENU_BUTTON_PADX = 12
MENU_BUTTON_PADY = 6
CLIENT_ROOT = Path(__file__).resolve().parent.parent
SERVER_ROOT = CLIENT_ROOT / "mudproto_server"
GUI_CONFIGURATION_ROOT = CLIENT_ROOT / "mudproto_client_gui" / "gui-configuration"
CLIENT_GUI_SETTINGS_FILE = GUI_CONFIGURATION_ROOT / "server_info.json"
CLIENT_GUI_CONFIG_FILE = GUI_CONFIGURATION_ROOT / "client_config.json"
DEFAULT_CLIENT_CONFIG_FILENAME = "mudproto-client-config.json"
SERVER_SETTINGS_FILE = SERVER_ROOT / "configuration" / "server" / "settings.json"


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception:
        return {}

    return raw if isinstance(raw, dict) else {}


def _load_network_settings() -> dict[str, Any]:
    server_settings = _load_json_object(SERVER_SETTINGS_FILE)
    server_network = server_settings.get("network", {})
    network = dict(server_network) if isinstance(server_network, dict) else {}

    client_settings = _load_json_object(CLIENT_GUI_SETTINGS_FILE)
    client_network = client_settings.get("network", {})
    if isinstance(client_network, dict):
        network.update(client_network)

    return network


def _resolve_network_path(raw_path: str) -> Path:
    path = Path(str(raw_path).strip())
    if path.is_absolute():
        return path

    if str(raw_path).strip().replace("\\", "/").startswith("configuration/"):
        return SERVER_ROOT / path
    return CLIENT_ROOT / path


def _normalize_aliases(raw_aliases: object) -> dict[str, str]:
    if not isinstance(raw_aliases, dict):
        return {}

    aliases: dict[str, str] = {}
    for raw_key, raw_value in raw_aliases.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        if key and value:
            aliases[key] = value
    return aliases


def _normalize_client_config(raw: object, *, fallback_server_uri: str | None = None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    fallback = str(fallback_server_uri).strip() if fallback_server_uri else default_server_uri()
    server_uri = str(data.get("server_uri", "")).strip() or fallback
    return {
        "version": 1,
        "server_uri": server_uri,
        "aliases": _normalize_aliases(data.get("aliases", {})),
    }


def _load_client_config(path: Path = CLIENT_GUI_CONFIG_FILE) -> dict[str, Any]:
    return _normalize_client_config(_load_json_object(path))


def _write_client_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(_normalize_client_config(config), handle, indent=2)


def default_server_uri() -> str:
    env_uri = os.environ.get("MUDPROTO_SERVER_URI", "").strip()
    if env_uri:
        return env_uri

    network = _load_network_settings()
    host = str(network.get("host", "localhost")).strip() or "localhost"
    port = int(network.get("port", 8765))
    scheme = "wss" if bool(network.get("tls_enabled", False)) else "ws"
    return f"{scheme}://{host}:{port}/"


def build_client_ssl_context(uri: str) -> ssl.SSLContext | None:
    if not str(uri).strip().lower().startswith("wss://"):
        return None

    network = _load_network_settings()
    verify_server = bool(network.get("tls_verify_server", False))
    env_verify = os.environ.get("MUDPROTO_TLS_VERIFY_SERVER", "").strip().lower()
    if env_verify:
        verify_server = env_verify in {"1", "true", "yes", "on"}

    ca_file = os.environ.get("MUDPROTO_TLS_CA_FILE", "").strip() or str(network.get("tls_ca_file", "")).strip()
    context = ssl.create_default_context()

    if ca_file:
        resolved_ca = _resolve_network_path(ca_file)
        if not resolved_ca.exists():
            raise FileNotFoundError(f"TLS CA file not found: {resolved_ca}")
        context.load_verify_locations(cafile=str(resolved_ca))

    if not verify_server:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    return context


def configure_windows_dpi_awareness() -> None:
    if not hasattr(ctypes, "windll"):
        return

    try:
        # Preferred on modern Windows: per-monitor DPI awareness v2.
        dpi_aware_v2 = ctypes.c_void_p(-4)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(dpi_aware_v2):
            return
    except Exception:
        pass

    try:
        # Fallback for Windows 8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        # Older Windows API fallback
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_input_message(text: str) -> dict[str, Any]:
    return {
        "type": "input",
        "source": "mudproto_client_gui",
        "timestamp": utc_now_iso(),
        "payload": {
            "text": text,
        },
    }


def _extract_lines(payload: dict[str, Any], key: str) -> list[Line]:
    candidate = payload.get(key)
    if not isinstance(candidate, list):
        return []
    return [line for line in candidate if isinstance(line, list)]


class MudProtoGuiClient:
    def __init__(self, root: tk.Tk, uri: str | None = None) -> None:
        self.root = root
        self.client_config_path = CLIENT_GUI_CONFIG_FILE
        stored_client_config = _load_client_config(self.client_config_path)
        self.aliases = dict(stored_client_config.get("aliases", {}))
        stored_uri = str(stored_client_config.get("server_uri", "")).strip()
        self.uri = str(uri).strip() if uri and str(uri).strip() else (stored_uri or default_server_uri())
        self.websocket = None
        self.network_loop = asyncio.new_event_loop()
        self.network_thread = threading.Thread(target=self._run_network_loop, daemon=True)
        self._connecting = False
        self._closing = False
        self._manual_disconnect = False
        self._reconnect_job: str | None = None

        self.root.title("MudProto GUI Client")
        self.root.geometry("1440x1149")
        self.root.configure(bg="black")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.base_font = ("Consolas", 11)
        self.menu_font = ("Consolas", 12)
        self.bold_font = ("Consolas", 11, "bold")
        self.command_history: list[str] = []
        self.history_index: int | None = None
        self.history_stash = ""
        self.output_ends_with_newline = True
        self._focus_restore_job: str | None = None
        self._window_is_active = True
        self._connection_tooltip: tk.Toplevel | None = None

        self._build_widgets()
        self.root.bind_all("<FocusIn>", self._on_window_activated, add="+")
        self.root.bind_all("<FocusOut>", self._on_window_deactivated, add="+")
        self.root.bind_all("<KeyPress>", self._on_global_key_press, add="+")
        self.network_thread.start()
        self.append_system_message(f"Connecting to {self.uri}...", fg="bright_cyan")
        self.connect()

    def _build_widgets(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "MudProto.Vertical.TScrollbar",
            background="#1f1f1f",
            darkcolor="#1f1f1f",
            lightcolor="#1f1f1f",
            troughcolor="#070707",
            bordercolor="#070707",
            arrowcolor="#b8b8b8",
            relief="flat",
        )
        style.map(
            "MudProto.Vertical.TScrollbar",
            background=[("active", "#323232")],
        )

        container = tk.Frame(self.root, bg="black")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        menu_frame = tk.Frame(
            container,
            bg="#090909",
            highlightbackground="#262626",
            highlightthickness=1,
            bd=0,
            padx=MENU_BAR_PADX,
            pady=MENU_BAR_PADY,
        )
        menu_frame.pack(fill="x", pady=(0, 8))

        menu_button_options = {
            "bg": "#090909",
            "fg": COLOR_MAP["bright_white"],
            "activebackground": "#151515",
            "activeforeground": COLOR_MAP["bright_white"],
            "relief": "flat",
            "bd": 0,
            "font": self.menu_font,
            "padx": MENU_BUTTON_PADX,
            "pady": MENU_BUTTON_PADY,
            "highlightthickness": 0,
        }
        menu_options = {
            "tearoff": False,
            "bg": "#101010",
            "fg": COLOR_MAP["bright_white"],
            "activebackground": "#1e1e1e",
            "activeforeground": COLOR_MAP["bright_white"],
            "relief": "flat",
            "bd": 1,
            "font": self.menu_font,
            "activeborderwidth": 0,
        }

        self.file_menu_button = tk.Menubutton(menu_frame, text="File", **menu_button_options)
        self.file_menu_button.pack(side="left", padx=(0, 2))
        file_menu = tk.Menu(self.file_menu_button, **menu_options)
        self._add_menu_command(file_menu, "Load Config...", self.load_config_from_dialog)
        self._add_menu_command(file_menu, "Save Config", self.save_config)
        self._add_menu_command(file_menu, "Save Config As...", self.save_config_as)
        file_menu.add_separator()
        self._add_menu_command(file_menu, "Exit", self.on_close)
        self.file_menu_button.configure(menu=file_menu)

        self.edit_menu_button = tk.Menubutton(menu_frame, text="Edit", **menu_button_options)
        self.edit_menu_button.pack(side="left", padx=2)
        edit_menu = tk.Menu(self.edit_menu_button, **menu_options)
        self._add_menu_command(edit_menu, "Clear Output", self.clear_output)
        self.edit_menu_button.configure(menu=edit_menu)

        self.configuration_menu_button = tk.Menubutton(menu_frame, text="Configuration", **menu_button_options)
        self.configuration_menu_button.pack(side="left", padx=2)
        configuration_menu = tk.Menu(self.configuration_menu_button, **menu_options)
        self._add_menu_command(configuration_menu, "Aliases", self.open_aliases_modal_placeholder)
        self._add_menu_command(configuration_menu, "Key Bindings", self.open_key_bindings_modal_placeholder)
        self.configuration_menu_button.configure(menu=configuration_menu)

        self.connection_menu_button = tk.Menubutton(menu_frame, text="Connection", **menu_button_options)
        self.connection_menu_button.pack(side="left", padx=2)
        connection_menu = tk.Menu(self.connection_menu_button, **menu_options)
        self._add_menu_command(connection_menu, "Set Server URI...", self.prompt_server_uri)
        connection_menu.add_separator()
        self._add_menu_command(connection_menu, "Connect", self.connect)
        self._add_menu_command(connection_menu, "Disconnect", self.disconnect)
        self.connection_menu_button.configure(menu=connection_menu)

        self.help_menu_button = tk.Menubutton(menu_frame, text="Help", **menu_button_options)
        self.help_menu_button.pack(side="left", padx=(2, 8))
        help_menu = tk.Menu(self.help_menu_button, **menu_options)
        self._add_menu_command(help_menu, "About Client Settings", self.show_about_dialog)
        self.help_menu_button.configure(menu=help_menu)

        self.connection_state_label = tk.Label(
            menu_frame,
            text="Disconnected",
            bg="#101010",
            fg=COLOR_MAP["bright_red"],
            font=self.base_font,
            padx=10,
            pady=4,
            cursor="hand2",
            highlightbackground="#262626",
            highlightthickness=1,
        )
        self.connection_state_label.pack(side="right", padx=(8, 0))
        self.connection_state_label.bind("<Enter>", self._show_connection_tooltip)
        self.connection_state_label.bind("<Leave>", self._hide_connection_tooltip)

        output_frame = tk.Frame(container, bg="black")
        output_frame.pack(fill="both", expand=True)

        self.y_scrollbar = ttk.Scrollbar(
            output_frame,
            orient="vertical",
            style="MudProto.Vertical.TScrollbar",
        )
        self.y_scrollbar.pack(side="right", fill="y")

        self.output_text = tk.Text(
            output_frame,
            bg="black",
            fg=COLOR_MAP["bright_white"],
            insertbackground=COLOR_MAP["bright_white"],
            selectbackground="#264f78",
            relief="flat",
            borderwidth=0,
            wrap="word",
            font=self.base_font,
            padx=10,
            pady=10,
            yscrollcommand=self.y_scrollbar.set,
        )
        self.output_text.pack(side="left", fill="both", expand=True)
        self.output_margin_tag = "mudproto_output_margin"
        self.output_text.tag_configure(self.output_margin_tag, rmargin=OUTPUT_RIGHT_MARGIN_PX)
        self.output_text.configure(state="disabled")
        self.output_text.bind("<KeyPress>", self._on_global_key_press, add="+")
        self.y_scrollbar.bind("<KeyPress>", self._on_global_key_press, add="+")
        self.y_scrollbar.config(command=self.output_text.yview)

        input_frame = tk.Frame(container, bg="black")
        input_frame.pack(fill="x", pady=(0, 0))

        entry_prefix = tk.Label(
            input_frame,
            text=">",
            bg="black",
            fg=COLOR_MAP["bright_green"],
            font=self.bold_font,
            padx=4,
        )
        entry_prefix.pack(side="left")

        self.input_entry = tk.Entry(
            input_frame,
            bg="black",
            fg=COLOR_MAP["bright_white"],
            insertbackground=COLOR_MAP["bright_green"],
            relief="flat",
            borderwidth=1,
            font=self.base_font,
        )
        self.input_entry.pack(side="left", fill="x", expand=True, padx=(4, 0), ipady=6)
        self.input_entry.bind("<Return>", self.on_submit)
        self.input_entry.bind("<Up>", self.on_history_up)
        self.input_entry.bind("<Down>", self.on_history_down)
        self.input_entry.focus_set()

    def _add_menu_command(self, menu: tk.Menu, label: str, command) -> None:
        menu.add_command(label=f"  {label}  ", command=command)

    def _build_client_config(self) -> dict[str, Any]:
        return _normalize_client_config({
            "version": 1,
            "server_uri": self.uri,
            "aliases": getattr(self, "aliases", {}),
        })

    def _persist_default_client_config(self) -> None:
        try:
            _write_client_config(self.client_config_path, self._build_client_config())
        except Exception:
            return

    def _set_connection_indicator(self, text: str, fg: str = "bright_white") -> None:
        self._hide_connection_tooltip()
        if hasattr(self, "connection_state_label"):
            self.connection_state_label.configure(
                text=text,
                fg=COLOR_MAP.get(fg, COLOR_MAP["bright_white"]),
                cursor="hand2" if text == "Connected" else "arrow",
            )

    def _show_connection_tooltip(self, _event=None) -> None:
        if not hasattr(self, "connection_state_label"):
            return
        if str(self.connection_state_label.cget("text")) != "Connected":
            return
        if self._connection_tooltip is not None:
            return

        try:
            tooltip = tk.Toplevel(self.root)
            tooltip.wm_overrideredirect(True)
            tooltip.configure(bg="#101010", highlightbackground="#262626", highlightthickness=1)
            tk.Label(
                tooltip,
                text=self.uri,
                bg="#101010",
                fg=COLOR_MAP["bright_cyan"],
                font=self.base_font,
                padx=8,
                pady=4,
            ).pack()
            x = self.connection_state_label.winfo_rootx()
            y = self.connection_state_label.winfo_rooty() + self.connection_state_label.winfo_height() + 6
            tooltip.wm_geometry(f"+{x}+{y}")
            self._connection_tooltip = tooltip
        except tk.TclError:
            self._connection_tooltip = None

    def _hide_connection_tooltip(self, _event=None) -> None:
        if self._connection_tooltip is None:
            return
        try:
            self._connection_tooltip.destroy()
        except tk.TclError:
            pass
        self._connection_tooltip = None

    def _apply_client_config(self, config: dict[str, Any], *, announce: bool = True) -> None:
        normalized = _normalize_client_config(config)
        self.aliases = dict(normalized.get("aliases", {}))
        self.uri = str(normalized.get("server_uri", self.uri)).strip() or default_server_uri()
        self._set_connection_indicator("Connected" if self.websocket is not None else "Disconnected", "bright_green" if self.websocket is not None else "bright_red")
        self._persist_default_client_config()
        if announce:
            self.append_system_message("Loaded client config. Reconnect to apply any server change.", fg="bright_green")

    def save_config(self) -> None:
        try:
            _write_client_config(self.client_config_path, self._build_client_config())
            self.append_system_message(f"Saved client config to {self.client_config_path.name}.", fg="bright_green")
        except Exception as exc:
            self.append_system_message(f"Failed to save client config: {exc}", fg="bright_red")

    def save_config_as(self) -> None:
        target = filedialog.asksaveasfilename(
            title="Save MudProto Client Config",
            initialdir=str(self.client_config_path.parent),
            initialfile=DEFAULT_CLIENT_CONFIG_FILENAME,
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not target:
            return

        try:
            self.client_config_path = Path(target)
            _write_client_config(self.client_config_path, self._build_client_config())
            self.append_system_message(f"Saved client config to {self.client_config_path.name}.", fg="bright_green")
        except Exception as exc:
            self.append_system_message(f"Failed to save client config: {exc}", fg="bright_red")

    def load_config_from_dialog(self) -> None:
        target = filedialog.askopenfilename(
            title="Load MudProto Client Config",
            initialdir=str(self.client_config_path.parent),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not target:
            return

        try:
            selected_path = Path(target)
            loaded_config = _load_client_config(selected_path)
            self.client_config_path = selected_path
            self._apply_client_config(loaded_config)
        except Exception as exc:
            self.append_system_message(f"Failed to load client config: {exc}", fg="bright_red")

    def prompt_server_uri(self) -> None:
        new_uri = simpledialog.askstring("Server URI", "Enter the server WebSocket URI:", initialvalue=self.uri, parent=self.root)
        if new_uri is None:
            return

        normalized_uri = str(new_uri).strip()
        if not normalized_uri:
            self.append_system_message("Server URI was left unchanged.", fg="bright_yellow")
            return

        self.uri = normalized_uri
        self._set_connection_indicator("Connected" if self.websocket is not None else "Disconnected", "bright_green" if self.websocket is not None else "bright_red")
        self._persist_default_client_config()
        self.append_system_message(f"Server URI updated to {self.uri}", fg="bright_cyan")

    def _show_themed_message(self, title: str, message: str) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.configure(bg="#090909")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        outer = tk.Frame(dialog, bg="#090909", padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        body = tk.Frame(outer, bg="#101010", highlightbackground="#262626", highlightthickness=1, padx=14, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=title, bg="#101010", fg=COLOR_MAP["bright_cyan"], font=self.menu_font).pack(anchor="w", pady=(0, 10))
        tk.Label(body, text=message, justify="left", bg="#101010", fg=COLOR_MAP["bright_white"], font=self.base_font, wraplength=420).pack(anchor="w")
        tk.Button(body, text="Close", command=dialog.destroy, bg="#151515", fg=COLOR_MAP["bright_white"], activebackground="#1e1e1e", activeforeground=COLOR_MAP["bright_white"], relief="flat", bd=1, padx=12, pady=4, highlightthickness=0).pack(anchor="e", pady=(14, 0))

        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(20, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(20, (self.root.winfo_height() - dialog.winfo_height()) // 3)
        dialog.geometry(f"+{x}+{y}")

    def open_aliases_modal_placeholder(self) -> None:
        self._show_themed_message(
            "Aliases",
            "The aliases editor entry point is now ready. This will become the primary place to add, update, and delete aliases in a future step.",
        )

    def open_key_bindings_modal_placeholder(self) -> None:
        self._show_themed_message(
            "Key Bindings",
            "The key bindings editor entry point is now ready. This will become the primary place to add, update, and delete key bindings in a future step.",
        )

    def show_about_dialog(self) -> None:
        self._show_themed_message(
            "MudProto Client Settings",
            "The File menu can load and save portable client config packages.\n\n"
            "Local commands stay client-side:\n"
            "#clear\n"
            "#quit",
        )

    def _restore_input_focus(self) -> None:
        self._focus_restore_job = None
        try:
            if self.root.winfo_exists() and self.input_entry.winfo_exists():
                self.input_entry.focus_force()
                self.input_entry.icursor(tk.END)
        except tk.TclError:
            pass

    def _schedule_input_focus_restore(self) -> None:
        try:
            if self.root.winfo_exists():
                self._focus_restore_job = self.root.after(10, self._restore_input_focus)
                self.root.after(60, self._restore_input_focus)
                self.root.after(140, self._restore_input_focus)
        except tk.TclError:
            pass

    def _mark_window_inactive_if_needed(self) -> None:
        try:
            focused_widget = self.root.focus_displayof()
        except tk.TclError:
            focused_widget = None

        if focused_widget is None:
            self._window_is_active = False

    def _on_window_deactivated(self, _event=None) -> None:
        try:
            self.root.after(50, self._mark_window_inactive_if_needed)
        except tk.TclError:
            self._window_is_active = False

    def _on_window_activated(self, _event=None) -> None:
        if self._window_is_active:
            return

        self._window_is_active = True
        if self._focus_restore_job is not None:
            try:
                self.root.after_cancel(self._focus_restore_job)
            except tk.TclError:
                pass
        self._schedule_input_focus_restore()

    def _global_backspace(self) -> str:
        insert_index = int(self.input_entry.index(tk.INSERT))
        if insert_index > 0:
            self.input_entry.delete(insert_index - 1)
        return "break"

    def _global_delete(self) -> str:
        insert_index = int(self.input_entry.index(tk.INSERT))
        current_text = self.input_entry.get()
        if insert_index < len(current_text):
            self.input_entry.delete(insert_index)
        return "break"

    def _global_left(self) -> str:
        insert_index = max(0, int(self.input_entry.index(tk.INSERT)) - 1)
        self.input_entry.icursor(insert_index)
        return "break"

    def _global_right(self) -> str:
        insert_index = min(len(self.input_entry.get()), int(self.input_entry.index(tk.INSERT)) + 1)
        self.input_entry.icursor(insert_index)
        return "break"

    def _global_home(self) -> str:
        self.input_entry.icursor(0)
        return "break"

    def _global_end(self) -> str:
        self.input_entry.icursor(tk.END)
        return "break"

    def _on_global_key_press(self, event) -> str | None:
        if event is None:
            return None

        widget = getattr(event, "widget", None)
        if widget is self.input_entry:
            return None

        keysym = str(getattr(event, "keysym", "") or "")
        event_char = str(getattr(event, "char", "") or "")

        if keysym in {
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
            "Win_L", "Win_R", "Caps_Lock", "Num_Lock", "Escape",
        }:
            return None

        try:
            self.input_entry.focus_force()
            self.input_entry.icursor(tk.END)
        except tk.TclError:
            return None

        key_handlers = {
            "Return": self.on_submit,
            "BackSpace": self._global_backspace,
            "Delete": self._global_delete,
            "Left": self._global_left,
            "Right": self._global_right,
            "Home": self._global_home,
            "End": self._global_end,
            "Up": self.on_history_up,
            "Down": self.on_history_down,
        }
        handler = key_handlers.get(keysym)
        if handler is not None:
            return handler()

        if event_char and event_char.isprintable():
            self.input_entry.insert(tk.INSERT, event_char)
            return "break"

        return None

    def _run_network_loop(self) -> None:
        asyncio.set_event_loop(self.network_loop)
        self.network_loop.run_forever()

    def _cancel_reconnect(self) -> None:
        if self._reconnect_job is None:
            return
        try:
            self.root.after_cancel(self._reconnect_job)
        except tk.TclError:
            pass
        self._reconnect_job = None

    def _schedule_reconnect(self) -> None:
        if self._closing or self._manual_disconnect or self.websocket is not None or self._connecting:
            return
        if self._reconnect_job is not None:
            return

        self.append_system_message("Connection lost. Reconnecting in 5 seconds...", "bright_yellow")
        try:
            self._reconnect_job = self.root.after(RECONNECT_INTERVAL_MS, self._attempt_reconnect)
        except tk.TclError:
            self._reconnect_job = None

    def _attempt_reconnect(self) -> None:
        self._reconnect_job = None
        if self._closing or self.websocket is not None or self._connecting:
            return

        self.append_system_message(f"Reconnecting to {self.uri}...", "bright_cyan")
        self.connect()

    def connect(self) -> None:
        if self._closing or self.websocket is not None or self._connecting:
            return

        self._manual_disconnect = False
        self._cancel_reconnect()
        self._connecting = True
        self._set_connection_indicator("Connecting", "bright_yellow")
        self._persist_default_client_config()
        asyncio.run_coroutine_threadsafe(self._connect_async(), self.network_loop)

    def disconnect(self) -> None:
        self._manual_disconnect = True
        self._cancel_reconnect()
        self._connecting = False
        self._set_connection_indicator("Disconnected", "bright_red")
        self._append_local_status_line("Disconnected locally.", fg="bright_yellow")

        try:
            asyncio.run_coroutine_threadsafe(self._close_async(), self.network_loop)
        except Exception:
            pass

    async def _connect_async(self) -> None:
        if self._closing or self.websocket is not None:
            self._connecting = False
            return

        try:
            ssl_context = build_client_ssl_context(self.uri)
            self.websocket = await websockets.connect(self.uri, ssl=ssl_context)
            self.root.after(0, self._cancel_reconnect)
            self.root.after(0, self._set_connection_indicator, "Connected", "bright_green")
            self.root.after(0, self._set_prompt_text, "Connected. Waiting for server prompt...")
            self.root.after(0, self.append_system_message, f"Connected to {self.uri}", "bright_green")
            await self._receive_loop()
        except Exception as exc:
            self.websocket = None
            self.root.after(0, self._set_connection_indicator, "Disconnected", "bright_red")
            self.root.after(0, self._set_prompt_text, "Disconnected")
            self.root.after(0, self.append_system_message, f"Connection error: {exc}", "bright_red")
        finally:
            self._connecting = False
            if not self._closing and self.websocket is None:
                self.root.after(0, self._schedule_reconnect)

    async def _receive_loop(self) -> None:
        websocket = self.websocket
        if websocket is None:
            return

        try:
            async for response_text in websocket:
                try:
                    response = json.loads(response_text)
                except json.JSONDecodeError:
                    continue

                if response.get("type") == "display":
                    self.root.after(0, self.render_display_message, response)
        except websockets.ConnectionClosed:
            self.root.after(0, self.append_system_message, "Connection closed by server.", "bright_yellow")
        finally:
            self.websocket = None
            self.root.after(0, self._set_connection_indicator, "Disconnected", "bright_red")
            self.root.after(0, self._set_prompt_text, "Disconnected")

    async def _send_text_async(self, text: str) -> None:
        if self.websocket is None:
            raise RuntimeError("Not connected to server.")
        await self.websocket.send(json.dumps(build_input_message(text)))

    async def _close_async(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()

    def on_submit(self, _event=None) -> str | None:
        raw_text = self.input_entry.get()
        normalized_text = raw_text.strip()

        self.input_entry.delete(0, tk.END)
        if normalized_text:
            self._record_history(normalized_text)

        local_command = normalized_text.lower()
        if local_command == "#clear":
            self.clear_output()
            return "break"

        if local_command == "#quit":
            self.on_close()
            return "break"

        if local_command.startswith("#"):
            self.append_system_message("Unknown local command. Available: #clear, #quit.", fg="bright_yellow")
            return "break"

        future = asyncio.run_coroutine_threadsafe(self._send_text_async(raw_text), self.network_loop)

        def _report_result() -> None:
            try:
                future.result()
            except Exception as exc:
                self.root.after(0, self.append_system_message, f"Send failed: {exc}", "bright_red")

        threading.Thread(target=_report_result, daemon=True).start()
        return "break"

    def on_history_up(self, _event=None) -> str:
        if not self.command_history:
            return "break"

        if self.history_index is None:
            self.history_stash = self.input_entry.get()
            self.history_index = len(self.command_history) - 1
        elif self.history_index > 0:
            self.history_index -= 1

        self._set_input_text(self.command_history[self.history_index])
        return "break"

    def on_history_down(self, _event=None) -> str:
        if self.history_index is None:
            return "break"

        if self.history_index < len(self.command_history) - 1:
            self.history_index += 1
            self._set_input_text(self.command_history[self.history_index])
        else:
            self.history_index = None
            self._set_input_text(self.history_stash)

        return "break"

    def _record_history(self, command: str) -> None:
        if not self.command_history or self.command_history[-1] != command:
            self.command_history.append(command)
        self.history_index = None
        self.history_stash = ""

    def _set_input_text(self, text: str) -> None:
        self.input_entry.delete(0, tk.END)
        self.input_entry.insert(0, text)
        self.input_entry.icursor(tk.END)

    def _set_prompt_text(self, text: str) -> None:
        self._append_local_status_line(text, fg="bright_cyan")

    def _append_local_status_line(self, text: str, *, fg: str = "bright_white") -> None:
        lines: list[Line] = []
        if not self.output_ends_with_newline:
            lines.append([])
        lines.append([{"text": str(text), "fg": fg, "bold": False}])
        lines.append([])
        self._append_line_group(lines)

    def _ensure_tag(self, widget: tk.Text, fg: str | None, bold: bool) -> str | None:
        if not fg and not bold:
            return None

        color_key = fg if fg in COLOR_MAP else "bright_white"
        widget_name = str(widget)
        tag_name = f"{widget_name}:{color_key}:{'bold' if bold else 'normal'}"
        if tag_name not in widget.tag_names():
            widget.tag_configure(
                tag_name,
                foreground=COLOR_MAP[color_key],
                font=self.bold_font if bold else self.base_font,
            )
        return tag_name

    def _append_line_group(self, lines: list[Line]) -> None:
        if not lines:
            return

        self.output_text.configure(state="normal")

        if not self.output_ends_with_newline:
            self.output_text.insert(tk.END, "\n")

        for line_index, parts in enumerate(lines):
            if line_index > 0:
                self.output_text.insert(tk.END, "\n")
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = str(part.get("text", ""))
                fg = part.get("fg") if isinstance(part.get("fg"), str) else None
                bold = bool(part.get("bold", False))
                tag = self._ensure_tag(self.output_text, fg, bold)
                margin_tag = getattr(self, "output_margin_tag", None)
                if tag is not None and margin_tag:
                    self.output_text.insert(tk.END, text, (margin_tag, tag))
                elif tag is not None:
                    self.output_text.insert(tk.END, text, tag)
                elif margin_tag:
                    self.output_text.insert(tk.END, text, margin_tag)
                else:
                    self.output_text.insert(tk.END, text)

        self.output_ends_with_newline = bool(lines and not lines[-1])
        self.output_text.configure(state="disabled")
        self.output_text.see(tk.END)

    def append_system_message(self, text: str, fg: str = "bright_white") -> None:
        self._append_local_status_line(text, fg=fg)

    def render_display_message(self, message: dict[str, Any]) -> None:
        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            return

        lines = _extract_lines(payload, "lines")
        prompt_lines = _extract_lines(payload, "prompt_lines")
        rendered_lines: list[Line] = []
        if lines:
            rendered_lines.extend(lines)
        if prompt_lines:
            rendered_lines.extend(prompt_lines)
        if rendered_lines:
            self._append_line_group(rendered_lines)

    def clear_output(self) -> None:
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.configure(state="disabled")
        self.output_ends_with_newline = True

    def on_close(self) -> None:
        self._closing = True
        self._cancel_reconnect()
        self._persist_default_client_config()

        try:
            asyncio.run_coroutine_threadsafe(self._close_async(), self.network_loop)
        except Exception:
            pass

        try:
            self.network_loop.call_soon_threadsafe(self.network_loop.stop)
        except Exception:
            pass

        self.root.destroy()


def main() -> None:
    configure_windows_dpi_awareness()
    root = tk.Tk()
    MudProtoGuiClient(root)
    root.mainloop()


if __name__ == "__main__":
    main()

