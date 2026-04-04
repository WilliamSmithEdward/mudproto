import asyncio
import ctypes
import json
import threading
import tkinter as tk
from tkinter import ttk
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

OUTPUT_WRAP_COLUMN = 100


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
        # Legacy fallback
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_input_message(text: str) -> dict[str, Any]:
    return {
        "type": "input",
        "source": "mudproto-client-gui",
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
    def __init__(self, root: tk.Tk, uri: str = "ws://localhost:8765") -> None:
        self.root = root
        self.uri = uri
        self.websocket = None
        self.network_loop = asyncio.new_event_loop()
        self.network_thread = threading.Thread(target=self._run_network_loop, daemon=True)

        self.root.title("MudProto GUI Client")
        self.root.geometry("1440x1149")
        self.root.configure(bg="black")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.base_font = ("Consolas", 11)
        self.bold_font = ("Consolas", 11, "bold")
        self.command_history: list[str] = []
        self.history_index: int | None = None
        self.history_stash = ""
        self.output_ends_with_newline = True
        self.wrap_column = OUTPUT_WRAP_COLUMN
        self._focus_restore_job: str | None = None
        self._window_is_active = True

        self._build_widgets()
        self.root.bind("<FocusIn>", self._on_window_activated, add="+")
        self.root.bind("<FocusOut>", self._on_window_deactivated, add="+")
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
        style.configure(
            "MudProto.Horizontal.TScrollbar",
            background="#1f1f1f",
            darkcolor="#1f1f1f",
            lightcolor="#1f1f1f",
            troughcolor="#070707",
            bordercolor="#070707",
            arrowcolor="#b8b8b8",
            relief="flat",
        )
        style.map(
            "MudProto.Horizontal.TScrollbar",
            background=[("active", "#323232")],
        )

        container = tk.Frame(self.root, bg="black")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        output_frame = tk.Frame(container, bg="black")
        output_frame.pack(fill="both", expand=True)

        self.y_scrollbar = ttk.Scrollbar(
            output_frame,
            orient="vertical",
            style="MudProto.Vertical.TScrollbar",
        )
        self.y_scrollbar.pack(side="right", fill="y")

        self.x_scrollbar = ttk.Scrollbar(
            output_frame,
            orient="horizontal",
            style="MudProto.Horizontal.TScrollbar",
        )

        self.output_text = tk.Text(
            output_frame,
            bg="black",
            fg=COLOR_MAP["bright_white"],
            insertbackground=COLOR_MAP["bright_white"],
            selectbackground="#264f78",
            relief="flat",
            borderwidth=0,
            wrap="none",
            font=self.base_font,
            padx=10,
            pady=10,
            yscrollcommand=self.y_scrollbar.set,
            xscrollcommand=self._on_xscroll,
        )
        self.output_text.pack(side="left", fill="both", expand=True)
        self.output_text.configure(state="disabled")
        self.y_scrollbar.config(command=self.output_text.yview)
        self.x_scrollbar.config(command=self.output_text.xview)

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

    def _restore_input_focus(self) -> None:
        self._focus_restore_job = None
        try:
            if self.root.winfo_exists() and self.input_entry.winfo_exists():
                self.input_entry.focus_force()
                self.input_entry.icursor(tk.END)
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
            self.root.after(1, self._mark_window_inactive_if_needed)
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
        self._focus_restore_job = self.root.after(10, self._restore_input_focus)

    def _run_network_loop(self) -> None:
        asyncio.set_event_loop(self.network_loop)
        self.network_loop.run_forever()

    def connect(self) -> None:
        asyncio.run_coroutine_threadsafe(self._connect_async(), self.network_loop)

    async def _connect_async(self) -> None:
        if self.websocket is not None:
            return

        try:
            self.websocket = await websockets.connect(self.uri)
            self.root.after(0, self._set_prompt_text, "Connected. Waiting for server prompt...")
            self.root.after(0, self.append_system_message, f"Connected to {self.uri}", "bright_green")
            await self._receive_loop()
        except Exception as exc:
            self.websocket = None
            self.root.after(0, self._set_prompt_text, "Disconnected")
            self.root.after(0, self.append_system_message, f"Connection error: {exc}", "bright_red")

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
        user_text = raw_text.strip()
        if not user_text:
            return "break"

        self.input_entry.delete(0, tk.END)
        self._record_history(user_text)

        if user_text.lower() == "/clear":
            self.clear_output()
            return "break"

        if user_text.lower() == "/quit":
            self.on_close()
            return "break"

        self._advance_output_after_submit()
        future = asyncio.run_coroutine_threadsafe(self._send_text_async(user_text), self.network_loop)

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

    def _advance_output_after_submit(self) -> None:
        if self.output_ends_with_newline:
            return

        self.output_text.configure(state="normal")
        self.output_text.insert(tk.END, "\n")
        self.output_text.configure(state="disabled")
        self.output_text.see(tk.END)
        self.output_ends_with_newline = True

    def _on_xscroll(self, first: float | str, last: float | str) -> None:
        first_value = float(first)
        last_value = float(last)
        self.x_scrollbar.set(first_value, last_value)
        if first_value <= 0.0 and last_value >= 1.0:
            if self.x_scrollbar.winfo_ismapped():
                self.x_scrollbar.pack_forget()
        else:
            if not self.x_scrollbar.winfo_ismapped():
                self.x_scrollbar.pack(side="bottom", fill="x", before=self.y_scrollbar)

    def _set_prompt_text(self, text: str) -> None:
        self.append_parts(
            [{"text": text, "fg": "bright_cyan", "bold": False}],
            prefix_newline_if_needed=True,
        )

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

    def _wrap_line_parts(self, parts: list[Part]) -> list[Line]:
        if self.wrap_column <= 0:
            return [parts]

        wrapped_lines: list[Line] = []
        current_line: Line = []
        current_length = 0

        def flush_line() -> None:
            nonlocal current_line, current_length
            wrapped_lines.append(current_line)
            current_line = []
            current_length = 0

        def append_chunk(text: str, fg: str | None, bold: bool) -> None:
            nonlocal current_length
            if not text:
                return
            current_line.append({
                "text": text,
                "fg": fg or "bright_white",
                "bold": bold,
            })
            current_length += len(text)

        for part in parts:
            if not isinstance(part, dict):
                continue

            remaining = str(part.get("text", ""))
            fg = part.get("fg") if isinstance(part.get("fg"), str) else None
            bold = bool(part.get("bold", False))

            while remaining:
                available = max(1, self.wrap_column - current_length)
                if len(remaining) <= available:
                    append_chunk(remaining, fg, bold)
                    break

                split_at = remaining.rfind(" ", 0, available + 1)
                if split_at <= 0:
                    split_at = available
                    chunk = remaining[:split_at]
                    remaining = remaining[split_at:]
                else:
                    chunk = remaining[:split_at]
                    remaining = remaining[split_at + 1:]

                append_chunk(chunk.rstrip(), fg, bold)
                flush_line()
                remaining = remaining.lstrip()

        if current_line or not wrapped_lines:
            wrapped_lines.append(current_line)

        return wrapped_lines

    def append_parts(
        self,
        parts: list[Part],
        *,
        add_newline: bool = True,
        prefix_newline_if_needed: bool = False,
    ) -> None:
        self.output_text.configure(state="normal")
        if prefix_newline_if_needed and not self.output_ends_with_newline:
            self.output_text.insert(tk.END, "\n")
            self.output_ends_with_newline = True

        wrapped_lines = self._wrap_line_parts(parts)
        for line_index, wrapped_parts in enumerate(wrapped_lines):
            if line_index > 0:
                self.output_text.insert(tk.END, "\n")
            for part in wrapped_parts:
                if not isinstance(part, dict):
                    continue
                text = str(part.get("text", ""))
                fg = part.get("fg") if isinstance(part.get("fg"), str) else None
                bold = bool(part.get("bold", False))
                tag = self._ensure_tag(self.output_text, fg, bold)
                if tag is not None:
                    self.output_text.insert(tk.END, text, tag)
                else:
                    self.output_text.insert(tk.END, text)

        if add_newline:
            self.output_text.insert(tk.END, "\n")
            self.output_ends_with_newline = True
        else:
            self.output_ends_with_newline = False

        self.output_text.configure(state="disabled")
        self.output_text.see(tk.END)

    def _append_line_group(self, lines: list[Line]) -> None:
        if not lines:
            return

        self.output_text.configure(state="normal")
        wrote_any_line = False
        for line_index, parts in enumerate(lines):
            wrapped_lines = self._wrap_line_parts(parts)
            for wrapped_index, wrapped_parts in enumerate(wrapped_lines):
                if wrote_any_line or line_index > 0 or wrapped_index > 0:
                    self.output_text.insert(tk.END, "\n")
                wrote_any_line = True
                for part in wrapped_parts:
                    if not isinstance(part, dict):
                        continue
                    text = str(part.get("text", ""))
                    fg = part.get("fg") if isinstance(part.get("fg"), str) else None
                    bold = bool(part.get("bold", False))
                    tag = self._ensure_tag(self.output_text, fg, bold)
                    if tag is not None:
                        self.output_text.insert(tk.END, text, tag)
                    else:
                        self.output_text.insert(tk.END, text)

        self.output_ends_with_newline = bool(lines and not lines[-1])
        self.output_text.configure(state="disabled")
        self.output_text.see(tk.END)

    def append_system_message(self, text: str, fg: str = "bright_white") -> None:
        self.append_parts(
            [{"text": text, "fg": fg, "bold": False}],
            prefix_newline_if_needed=True,
        )

    def render_display_message(self, message: dict[str, Any]) -> None:
        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            return

        lines = _extract_lines(payload, "lines")
        prompt_lines = _extract_lines(payload, "prompt_lines")

        if lines:
            self._append_line_group(lines)
        if prompt_lines:
            self._append_line_group(prompt_lines)

    def clear_output(self) -> None:
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.configure(state="disabled")
        self.output_ends_with_newline = True

    def on_close(self) -> None:
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
