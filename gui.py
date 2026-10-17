"""WWBS 的 Tk 界面基础组件。"""

import ctypes
import os
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, TOP, X, Canvas, Entry, Frame, Label, StringVar, Tk
from tkinter import font as tkfont
from tkinter import messagebox as tkinter_messagebox
from tkinter import simpledialog as tkinter_simpledialog
from tkinter import ttk

from PIL import Image, ImageTk

from ui_controls import CenteredToplevel as Toplevel
from ui_controls import ParentDialogs, RoundedButton, ThinScrollbar


messagebox = ParentDialogs(tkinter_messagebox)
simpledialog = ParentDialogs(tkinter_simpledialog)

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FONT = "Consolas"
SIMPLE_COLORS = {
    "app_bg": "#f5f5f7",
    "panel": "#ffffff",
    "panel_alt": "#fbfbfd",
    "line": "#d2d2d7",
    "line_soft": "#e5e5ea",
    "text": "#1d1d1f",
    "muted": "#6e6e73",
    "primary": "#007aff",
    "primary_hover": "#0a84ff",
    "danger": "#ff3b30",
    "preview": "#111318",
}
DANIYA_COLORS = {
    "app_bg": "#fff4f8",
    "panel": "#fffafd",
    "panel_alt": "#fff0f6",
    "line": "#e9b9cf",
    "line_soft": "#f3d9e5",
    "text": "#402c39",
    "muted": "#806474",
    "primary": "#d65f98",
    "primary_hover": "#e976ab",
    "danger": "#c94f73",
    "preview": "#241d2d",
}
AEMEATH_COLORS = {
    "app_bg": "#fff7fb",
    "panel": "#fffdfd",
    "panel_alt": "#fff0f7",
    "line": "#e8b7ce",
    "line_soft": "#f3d9e6",
    "text": "#43303f",
    "muted": "#856778",
    "primary": "#d95d9d",
    "primary_hover": "#ee78b4",
    "danger": "#c84e78",
    "preview": "#252336",
}
JINGRAN_COLORS = {
    "app_bg": "#0a1117",
    "panel": "#101a22",
    "panel_alt": "#15232c",
    "line": "#31515c",
    "line_soft": "#243a43",
    "text": "#edf4f4",
    "muted": "#9ab0b5",
    "primary": "#42c8dc",
    "primary_hover": "#6edbe8",
    "danger": "#d17a58",
    "preview": "#050a0f",
}
CARTETHYIA_COLORS = {
    "app_bg": "#edf4ff",
    "panel": "#f9fbff",
    "panel_alt": "#e3edfb",
    "line": "#9db6d8",
    "line_soft": "#cbd9ec",
    "text": "#1c2c4a",
    "muted": "#587096",
    "primary": "#315faf",
    "primary_hover": "#4778ca",
    "danger": "#9d5366",
    "preview": "#09152b",
}
COLORS = dict(SIMPLE_COLORS)


def apply_windows_taskbar_icon(window, icon_path: Path) -> bool:
    """Apply an .ico to the real top-level HWND used by the Windows taskbar."""
    if os.name != "nt" or not icon_path.exists():
        return False
    try:
        window.update_idletasks()
        child_hwnd = int(window.winfo_id())
        parent_hwnd = int(ctypes.windll.user32.GetParent(child_hwnd))
        hwnd = parent_hwnd or child_hwnd
        image_icon = 1
        load_from_file = 0x0010
        wm_seticon = 0x0080
        handles = []
        for size, slot in ((16, 0), (32, 1)):
            handle = ctypes.windll.user32.LoadImageW(
                None,
                str(icon_path),
                image_icon,
                size,
                size,
                load_from_file,
            )
            if handle:
                ctypes.windll.user32.SendMessageW(hwnd, wm_seticon, slot, handle)
                handles.append(handle)
        if handles:
            # Windows needs these handles to remain alive for the lifetime of the window.
            window._wwbs_native_icon_handles = handles
            return True
    except Exception:
        pass
    return False


class TemplateCropper:
    def __init__(self, parent: Tk, source_path: Path, templates_dir: Path, log, ui=None):
        self.ui = ui
        self.source_path = source_path
        self.templates_dir = templates_dir
        self.log = log
        self.window = Toplevel(parent)
        self.window.title("制作识别模板")
        self.window.geometry("1120x760")
        self.window.configure(bg=COLORS["panel"])
        self.image = Image.open(source_path).convert("RGB")
        self.scale = min(1060 / self.image.width, 660 / self.image.height, 1.0)
        preview_size = (int(self.image.width * self.scale), int(self.image.height * self.scale))
        self.preview = self.image.resize(preview_size, Image.Resampling.BILINEAR)
        self.photo = ImageTk.PhotoImage(self.preview)
        self.start_x = 0
        self.start_y = 0
        self.rect_id: int | None = None
        self.selection: tuple[int, int, int, int] | None = None

        Label(self.window, text="在截图上拖框选择按钮或图标，建议包含文字/边框等明显特征。", bg=COLORS["panel"], fg=COLORS["text"]).pack(side=TOP, fill=X, padx=10, pady=6)
        self.canvas = Canvas(self.window, width=preview_size[0], height=preview_size[1], cursor="crosshair")
        self.canvas.pack(side=TOP, padx=10, pady=6)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.bind("<ButtonPress-1>", self._start)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish)

        buttons = Frame(self.window, padx=10, pady=8, bg=COLORS["panel"])
        buttons.pack(side=TOP, fill=X)
        RoundedButton(buttons, colors=COLORS, text="保存模板", primary=True, command=self._save).pack(side=LEFT)
        RoundedButton(buttons, colors=COLORS, text="关闭", command=self.window.destroy).pack(side=LEFT, padx=8)

    def _start(self, event) -> None:
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#00d084", width=2)

    def _drag(self, event) -> None:
        if self.rect_id is not None:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _finish(self, event) -> None:
        x1, x2 = sorted((self.start_x, event.x))
        y1, y2 = sorted((self.start_y, event.y))
        self.selection = (x1, y1, x2, y2)

    def _save(self) -> None:
        if not self.selection:
            messagebox.showinfo("提示", "请先拖框选择一个模板区域。", parent=self.window)
            return
        name = self.ui._ask_text("模板文件名", "输入模板文件名，例如 menu.png", parent=self.window) if self.ui else simpledialog.askstring("模板文件名", "输入模板文件名，例如 menu.png", parent=self.window)
        if not name:
            return
        if not name.lower().endswith(".png"):
            name += ".png"
        safe_name = Path(name).name
        x1, y1, x2, y2 = self.selection
        if abs(x2 - x1) < 8 or abs(y2 - y1) < 8:
            messagebox.showinfo("提示", "选择区域太小，请框大一点。", parent=self.window)
            return
        crop_box = (
            int(x1 / self.scale),
            int(y1 / self.scale),
            int(x2 / self.scale),
            int(y2 / self.scale),
        )
        target = self.templates_dir / safe_name
        self.image.crop(crop_box).save(target)
        self.log(f"模板已保存: {target}")
        messagebox.showinfo("已保存", f"模板已保存:\n{target}", parent=self.window)
        self.window.destroy()


class AppGuiMixin:
    def _create_scrollable_tab(self, parent: Frame, *, padding: int = 20,
                               modern: bool = True, stretch: bool = False) -> tuple[Frame, Canvas]:
        canvas = Canvas(parent, highlightthickness=0, bg=COLORS["panel"])
        if modern:
            scrollbar = Canvas(parent, width=7, highlightthickness=0, bd=0,
                               bg=COLORS["panel"], cursor="hand2")
            scrollbar._keep_canvas_style = True
            canvas._scroll_range = (0.0, 1.0)

            def draw_scrollbar(_event=None) -> None:
                scrollbar.delete("all")
                first, last = canvas._scroll_range
                height = scrollbar.winfo_height()
                if height <= 1 or last - first >= 0.999:
                    return
                scrollbar.create_line(3, 0, 3, height, fill=COLORS["line_soft"], width=2)
                top = max(2, int(first * height))
                bottom = min(height - 2, max(top + 24, int(last * height)))
                scrollbar.create_line(3, top, 3, bottom, fill=COLORS["line"], width=5, capstyle="round")

            def update_scrollbar(first, last) -> None:
                canvas._scroll_range = (float(first), float(last))
                draw_scrollbar()

            def drag_scrollbar(event) -> None:
                first, last = canvas._scroll_range
                visible = min(1.0, last - first)
                height = max(1, scrollbar.winfo_height())
                thumb = max(24, int(visible * height))
                travel = max(1, height - thumb)
                top = max(0, min(travel, event.y - thumb // 2))
                canvas.yview_moveto(top / travel * (1.0 - visible))

            scrollbar.bind("<Configure>", draw_scrollbar)
            scrollbar.bind("<Button-1>", drag_scrollbar)
            scrollbar.bind("<B1-Motion>", drag_scrollbar)
            canvas.configure(yscrollcommand=update_scrollbar)
        else:
            scrollbar = self._thin_scrollbar(parent, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
        canvas._scrollbar = scrollbar
        content = Frame(canvas, padx=padding, pady=18 if padding else 0, bg=COLORS["panel"])
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill="y")

        def resize_content(_event=None):
            options = {'width': max(1, canvas.winfo_width())}
            if stretch:
                options['height'] = max(canvas.winfo_height(), content.winfo_reqheight())
            canvas.itemconfigure(content_window, **options)
            # Prevent short lists from exposing a blank band above their cards.
            bounds = canvas.bbox(content_window)
            if bounds:
                canvas.configure(scrollregion=(0, 0, max(1, canvas.winfo_width()),
                                               max(canvas.winfo_height(), bounds[3])))
                if bounds[3] <= canvas.winfo_height():
                    canvas.yview_moveto(0)
        content.bind('<Configure>', resize_content)
        canvas.bind('<Configure>', resize_content)
        return content, canvas

    @staticmethod
    def _bind_mousewheel_tree(widget, canvas: Canvas) -> None:
        def scroll(event) -> str:
            delta = -1 if event.delta > 0 else 1
            canvas.yview_scroll(delta * 3, "units")
            return "break"

        widget.bind("<MouseWheel>", scroll, add="+")
        for child in widget.winfo_children():
            AppGuiMixin._bind_mousewheel_tree(child, canvas)

    def _scroll_start_left(self, event) -> str:
        direction = -1 if getattr(event, "delta", 0) > 0 else 1
        self.start_left_canvas.yview_scroll(direction * 3, "units")
        return "break"

    def _bind_start_left_mousewheel(self, widget) -> None:
        if isinstance(widget, ttk.Combobox) or getattr(widget, "_is_rounded_picker", False):
            return  # Keep the zone picker's own wheel selection behavior.
        widget.bind("<MouseWheel>", self._scroll_start_left, add="+")
        for child in widget.winfo_children():
            self._bind_start_left_mousewheel(child)

    def _update_start_scrollbar(self, first: str, last: str) -> None:
        self._start_scroll_range = (float(first), float(last))
        self._draw_start_scrollbar()

    def _draw_start_scrollbar(self) -> None:
        bar = self.start_left_scrollbar
        bar.delete("all")
        height = bar.winfo_height()
        width = bar.winfo_width()
        first, last = self._start_scroll_range
        if height <= 1 or last - first >= 0.999:
            return
        bar.create_line(width // 2, 0, width // 2, height,
                        fill=COLORS["line_soft"], width=2)
        top = max(2, int(first * height))
        bottom = min(height - 2, max(top + 24, int(last * height)))
        bar.create_line(width // 2, top, width // 2, bottom,
                        fill=COLORS["line"], width=5, capstyle="round")

    def _drag_start_scrollbar(self, event) -> None:
        first, last = self._start_scroll_range
        visible = min(1.0, last - first)
        height = max(1, self.start_left_scrollbar.winfo_height())
        thumb = max(24, int(visible * height))
        travel = max(1, height - thumb)
        top = max(0, min(travel, event.y - thumb // 2))
        self.start_left_canvas.yview_moveto((top / travel) * (1.0 - visible))

    @staticmethod
    def _paint_rounded_card(canvas: Canvas, x0: int, y0: int, x1: int, y1: int,
                            radius: int, color: str) -> None:
        from ui_controls import paint_round
        paint_round(canvas, x0, y0, x1, y1, radius, color)

    def _rounded_panel(self, parent, *, padding: int = 12, color: str | None = None,
                       outer_color: str | None = None):
        """Return a rounded shell and a normal Frame for its contents."""
        color = color or COLORS["panel_alt"]
        outer_color = outer_color or COLORS["panel"]
        shell = Frame(parent, bg=outer_color)
        backdrop = Canvas(shell, bg=outer_color, highlightthickness=0, bd=0)
        backdrop.place(relx=0, rely=0, relwidth=1, relheight=1)
        backdrop._keep_canvas_style = True
        content = Frame(shell, bg=color, padx=max(0, padding-6), pady=max(0, padding-6))
        content.pack(fill=BOTH, expand=True, padx=8, pady=8)

        def redraw(event) -> None:
            backdrop.delete("all")
            self._paint_rounded_card(backdrop, 0, 0, event.width, event.height, 14,
                                     COLORS["line_soft"])
            self._paint_rounded_card(backdrop, 1, 1, event.width - 1, event.height - 1,
                                     13, color)

        shell.bind("<Configure>", redraw)
        return shell, content

    def _close_rounded_picker(self) -> None:
        picker = getattr(self, "_active_rounded_picker", None)
        close = getattr(picker, "_popup_close", None)
        if close:
            close()

    def _ui_button(self, parent, *, text, command, width=None, **options):
        primary = options.pop('style', '') == 'Primary.TButton' or options.get('fg') in ('white', '#ffffff')
        colors = dict(COLORS)
        if primary and options.get('bg'):
            colors['primary'] = options['bg']
            colors['primary_hover'] = options.get('activebackground', options['bg'])
        return RoundedButton(parent, text=text, command=command, colors=colors,
                             width=width*9+24 if width else 100, primary=primary,
                             state=options.get('state', 'normal'), font_family=FONT_FAMILY)

    def _thin_scrollbar(self, parent, **options):
        return ThinScrollbar(parent, colors=COLORS, **options)

    def _rounded_entry(self, parent, **options):
        font = options.pop('font', (FONT_FAMILY, 10))
        measure = tkfont.Font(root=self.root, font=font)
        fill = options.pop('bg', COLORS['panel'])
        width = options.pop('width', 20)
        for key in ('relief', 'bd', 'highlightthickness', 'highlightbackground', 'highlightcolor'):
            options.pop(key, None)
        height = max(30, measure.metrics('linespace')+10)
        shell = Canvas(parent, width=measure.measure('0')*width+20, height=height,
                       bg=parent.cget('bg'), highlightthickness=0, bd=0)
        shell._keep_canvas_style = True
        shell._is_rounded_entry = True
        entry = Entry(shell, font=font, bg=fill, relief='flat', bd=0, highlightthickness=0,
                      insertbackground=options.pop('insertbackground', COLORS['text']),
                      fg=options.pop('fg', COLORS['text']), readonlybackground=fill, **options)
        entry._rounded_shell = shell
        entry.place(x=10, y=5, relwidth=1, width=-20, relheight=1, height=-10)

        def draw(_event=None):
            shell.delete('shape')
            w, h = max(20, shell.winfo_width()), max(height, shell.winfo_height())
            self._paint_rounded_card(shell, 0, 0, w, h, 8,
                                     COLORS['primary'] if self.root.focus_get() is entry else COLORS['line'])
            self._paint_rounded_card(shell, 1, 1, w-1, h-1, 7, fill)

        shell.bind('<Configure>', draw)
        entry.bind('<FocusIn>', draw, add='+')
        entry.bind('<FocusOut>', draw, add='+')
        for method in ('pack', 'pack_configure', 'pack_forget', 'grid', 'grid_configure', 'grid_remove', 'place'):
            setattr(entry, method, getattr(shell, method))
        return entry

    def _card_body(self, parent):
        shell, body = self._rounded_panel(parent, padding=16, color=COLORS['panel_alt'])
        body.pack = shell.pack
        return body

    def _wrap_button_row(self, parent):
        """Keep action labels readable when the window or font size changes."""
        buttons = [child for child in parent.winfo_children()
                   if getattr(child, '_is_rounded_button', False)]
        for button in buttons:
            button.pack_forget()
        previous = {'columns': 0}
        def layout(event=None):
            width = event.width if event else parent.winfo_width()
            cell = max((button.winfo_reqwidth() for button in buttons), default=100)+10
            columns = max(1, min(len(buttons), int(width/cell)))
            if columns == previous['columns']:
                return
            for column in range(max(columns, previous['columns'])):
                parent.columnconfigure(column, weight=0, minsize=0)
            for index, button in enumerate(buttons):
                button.grid(row=index//columns, column=index%columns, sticky='w', padx=(0, 10), pady=4)
            previous['columns'] = columns
        parent.bind('<Configure>', layout, add='+')
        layout()

    @staticmethod
    def _reserve_row_controls(parent, stretch):
        """Allocate action widths before giving remaining space to a picker."""
        stretch = getattr(stretch, '_rounded_shell', stretch)
        children = parent.winfo_children()
        for child in children:
            child.pack_forget()
        for column, child in enumerate(children):
            child.grid(row=0, column=column, sticky='ew', padx=(0, 8))
            parent.columnconfigure(column, weight=1 if child is stretch else 0)

    def _ask_text(self, title, prompt, *, initialvalue='', parent=None):
        owner = parent or self.root
        dialog = Toplevel(owner)
        dialog._centered_by_app = True
        dialog.withdraw()
        dialog.title(title)
        dialog.transient(owner)
        dialog.configure(bg=COLORS['app_bg'])
        dialog.resizable(False, False)
        shell, body = self._rounded_panel(dialog, padding=18, outer_color=COLORS['app_bg'])
        shell.pack(fill=BOTH, expand=True, padx=14, pady=14)
        Label(body, text=prompt, bg=COLORS['panel_alt'], fg=COLORS['text'],
              font=(FONT_FAMILY, 11), wraplength=440, justify=LEFT).pack(anchor='w', pady=(0, 12))
        value = StringVar(value=initialvalue)
        entry = self._rounded_entry(body, textvariable=value, width=34)
        entry.pack(fill=X)
        result = {'value': None}
        def accept():
            result['value'] = value.get()
            dialog.destroy()
        actions = Frame(body, bg=COLORS['panel_alt'])
        actions.pack(fill=X, pady=(14, 0))
        self._rounded_button(actions, '取消', dialog.destroy, width=84).pack(side=RIGHT)
        self._rounded_button(actions, '确定', accept, width=84, primary=True).pack(side=RIGHT, padx=(0, 8))
        dialog.bind('<Return>', lambda _: accept())
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        dialog.update_idletasks()
        width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        x = owner.winfo_x() + (owner.winfo_width()-width)//2
        y = owner.winfo_y() + (owner.winfo_height()-height)//2
        x = max(owner.winfo_vrootx(), min(x, owner.winfo_vrootx()+owner.winfo_vrootwidth()-width))
        y = max(owner.winfo_vrooty(), min(y, owner.winfo_vrooty()+owner.winfo_vrootheight()-height-32))
        dialog.geometry(f'{width}x{height}{x:+d}{y:+d}')
        dialog.deiconify()
        entry.focus_force()
        entry.select_range(0, END)
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result['value']

    def _rounded_picker(self, parent, variable: StringVar, values, on_change,
                        *, height: int = 31, editable: bool = False) -> Canvas:
        """A rounded selector with a compact scrollable popup and wheel selection."""
        height = max(height, tkfont.Font(root=self.root, family=FONT_FAMILY,
                                         size=13, weight="bold").metrics("linespace") + 8)
        choices = list(values)
        label_font = tkfont.Font(root=self.root, family=FONT_FAMILY, size=10)
        def display_label(value, available):
            if label_font.measure(value) <= available:
                return value
            # Keep both the start of a preset name and its import suffix visible.
            for kept in range(len(value)-1, -1, -1):
                front, back = (kept+1)//2, kept//2
                shortened = value[:front] + "…" + (value[-back:] if back else "")
                if label_font.measure(shortened) <= available:
                    return shortened
            return ""
        picker = Canvas(parent, height=height, bg=parent.cget("bg"),
                        highlightthickness=0, bd=0, cursor="hand2", takefocus=True)
        picker._keep_canvas_style = True
        picker._is_rounded_picker = True
        def set_choices(values):
            self._close_rounded_picker()
            choices[:] = list(values)
        picker.set_choices = set_choices

        def draw(_event=None) -> None:
            picker.delete("all")
            width = max(80, picker.winfo_width())
            self._paint_rounded_card(picker, 0, 0, width, height, 8, COLORS["line"])
            self._paint_rounded_card(picker, 1, 1, width - 1, height - 1, 7, COLORS["panel"])
            picker.create_text(12, height // 2, text=display_label(variable.get(), max(1, width-40)), anchor="w",
                               width=width - 40, fill=COLORS["text"],
                               font=(FONT_FAMILY, 10))
            picker.create_text(width - 17, height // 2, text="⌄", fill=COLORS["muted"],
                               font=(FONT_FAMILY, 13, "bold"))

        def wheel(event) -> str:
            if not choices:
                return 'break'
            try:
                index = choices.index(variable.get())
            except ValueError:
                index = 0
            direction = -1 if event.delta > 0 else 1
            selected = choices[max(0, min(len(choices) - 1, index + direction))]
            if selected != variable.get():
                variable.set(selected)
                on_change()
            return "break"

        def popup(_event=None) -> str:
            previous = getattr(picker, "_popup_window", None)
            if previous is not None and previous.winfo_exists():
                picker._popup_close()
                return "break"
            self._close_rounded_picker()
            window = Toplevel(picker)
            window.overrideredirect(True)
            window.transient(self.root)
            picker._popup_window = window
            self._active_rounded_picker = picker
            width = max(180, picker.winfo_width())
            visible = min(8, len(choices))
            row_height = max(32, tkfont.Font(root=self.root, family=FONT_FAMILY,
                                             size=10).metrics("linespace") + 12)
            entry_height = max(40, row_height + 8) if editable else 0
            screen_left = picker.winfo_vrootx()
            screen_top = picker.winfo_vrooty()
            screen_right = screen_left + picker.winfo_vrootwidth()
            screen_bottom = screen_top + picker.winfo_vrootheight()
            x = max(screen_left + 8, min(picker.winfo_rootx(), screen_right - width - 8))
            below = picker.winfo_rooty() + height + 2
            # A shorter list below the picker keeps controls above it clickable.
            below_rows = (screen_bottom - 8 - below - 8 - entry_height) // row_height
            if below_rows >= 1:
                visible = min(visible, below_rows)
                y = below
            else:
                above_rows = (picker.winfo_rooty() - screen_top - 18 - entry_height) // row_height
                visible = min(visible, max(1, above_rows))
                y = picker.winfo_rooty() - (visible * row_height + 8 + entry_height) - 2
            total_height = visible * row_height + 8 + entry_height
            y = max(screen_top + 8, min(y, screen_bottom - total_height - 8))
            window.geometry(f"{width}x{total_height}{x:+d}{y:+d}")
            outside_binding = None

            def close_popup() -> None:
                nonlocal outside_binding
                if outside_binding is not None:
                    self.root.unbind("<Button-1>", outside_binding)
                    outside_binding = None
                if window.winfo_exists():
                    window.destroy()
                picker._popup_window = None
                picker._popup_close = None
                if getattr(self, "_active_rounded_picker", None) is picker:
                    self._active_rounded_picker = None

            def close_if_outside(event) -> None:
                if not (x <= event.x_root < x + width and y <= event.y_root < y + total_height):
                    close_popup()

            picker._popup_close = close_popup

            def bind_outside() -> None:
                nonlocal outside_binding
                if window.winfo_exists():
                    outside_binding = self.root.bind("<Button-1>", close_if_outside, add="+")

            picker.after_idle(bind_outside)
            surface = Canvas(window, width=width, height=total_height,
                             bg=COLORS["panel"], highlightthickness=0, bd=0)
            surface.pack(fill=BOTH, expand=True)
            try:
                selected_index = choices.index(variable.get())
            except ValueError:
                selected_index = 0
            offset = max(0, min(len(choices) - visible, selected_index - visible // 2))
            custom = None

            def redraw() -> None:
                surface.delete("all")
                self._paint_rounded_card(surface, 0, 0, width, total_height, 9, COLORS["line"])
                self._paint_rounded_card(surface, 1, 1, width - 1, total_height - 1,
                                         8, COLORS["panel"])
                for row, value in enumerate(choices[offset:offset + visible]):
                    top = row * row_height + 4 + entry_height
                    if value == variable.get():
                        self._paint_rounded_card(surface, 5, top, width - 13, top + row_height,
                                                 6, COLORS["panel_alt"])
                    surface.create_text(14, top + row_height // 2, text=display_label(value, width-38), anchor="w",
                                        width=width - 38, fill=COLORS["text"],
                                        font=(FONT_FAMILY, 10))
                if len(choices) > visible:
                    track_top, track_bottom = 8 + entry_height, total_height - 8
                    track_height = track_bottom - track_top
                    thumb_height = max(22, int(track_height * visible / len(choices)))
                    thumb_top = track_top + int((track_height - thumb_height) * offset / (len(choices) - visible))
                    surface.create_line(width - 6, track_top, width - 6, track_bottom,
                                        fill=COLORS["line_soft"], width=2)
                    surface.create_line(width - 6, thumb_top, width - 6, thumb_top + thumb_height,
                                        fill=COLORS["muted"], width=4, capstyle="round")
                if custom is not None:
                    surface.create_window(7, 7, window=custom, anchor="nw", width=width - 20,
                                          height=27)

            def scroll_list(event) -> str:
                nonlocal offset
                offset = max(0, min(len(choices) - visible, offset + (-1 if event.delta > 0 else 1)))
                redraw()
                return "break"

            def choose(event) -> None:
                nonlocal offset
                if not 0 <= event.x < width or not 0 <= event.y < total_height:
                    close_popup()
                    return
                if event.x >= width - 13 and len(choices) > visible:
                    offset = max(0, min(len(choices) - visible,
                                        int((event.y - entry_height) / (total_height - entry_height)
                                            * (len(choices) - visible + 1))))
                    redraw()
                    return
                if event.y < entry_height:
                    return
                index = offset + max(0, min(visible - 1,
                                             (event.y - 4 - entry_height) // row_height))
                if 0 <= index < len(choices):
                    variable.set(choices[index])
                    on_change()
                close_popup()

            redraw()
            if editable:
                custom = Entry(surface, font=(FONT_FAMILY, 10), relief="flat", bd=0,
                               bg=COLORS["panel_alt"], fg=COLORS["text"],
                               insertbackground=COLORS["text"])
                custom.insert(0, variable.get())
                redraw()

                def save_custom(_event=None) -> None:
                    variable.set(custom.get().strip())
                    on_change()
                    close_popup()

                custom.bind("<Return>", save_custom)
            surface.bind("<MouseWheel>", scroll_list)
            surface.bind("<Button-1>", choose)
            surface.bind("<B1-Motion>", lambda event: choose(event)
                         if event.x >= width - 13 else None)
            window.bind("<Escape>", lambda _event: close_popup())
            window.protocol("WM_DELETE_WINDOW", close_popup)
            window.lift()
            window.focus_set()
            if editable:
                custom.focus_set()
                custom.select_range(0, END)
            return "break"

        picker.bind("<Configure>", draw)
        picker.bind("<MouseWheel>", wheel)
        picker.bind("<Button-1>", popup)
        picker.bind("<Return>", popup)
        picker.bind("<space>", popup)
        redraw_job = None

        def schedule_draw(*_args):
            nonlocal redraw_job
            if not picker.winfo_exists():
                return
            if redraw_job:
                picker.after_cancel(redraw_job)

            def refresh():
                nonlocal redraw_job
                redraw_job = None
                if picker.winfo_exists():
                    draw()

            redraw_job = picker.after_idle(refresh)

        trace_id = variable.trace_add("write", schedule_draw)

        def dispose(event):
            nonlocal redraw_job
            if event.widget is not picker:
                return
            if redraw_job:
                picker.after_cancel(redraw_job)
                redraw_job = None
            variable.trace_remove("write", trace_id)
            close = getattr(picker, "_popup_close", None)
            if close:
                close()

        picker.bind("<Destroy>", dispose, add="+")
        draw()
        return picker

    def _rounded_button(self, parent, label: str, command, *, width: int = 130,
                        primary: bool = False) -> Canvas:
        measure_font = tkfont.Font(root=self.root, family=FONT_FAMILY, size=10,
                                   weight="bold" if primary else "normal")
        width = max(width, measure_font.measure(label) + 32)
        height = max(42, measure_font.metrics("linespace") + 18)
        button = Canvas(parent, width=width, height=height, bg=parent.cget("bg"),
                        highlightthickness=0, bd=0, cursor="hand2", takefocus=True)
        button._keep_canvas_style = True

        def draw(state: str = "default") -> None:
            button.delete("all")
            actual_width = button.winfo_width() if button.winfo_width() > 1 else width
            actual_height = button.winfo_height() if button.winfo_height() > 1 else height
            fill = (COLORS["primary_hover"] if state == "hover" else COLORS["primary"])
            if not primary:
                fill = COLORS["panel"] if state == "default" else COLORS["panel_alt"]
            if state == "pressed":
                fill = COLORS["line_soft"] if not primary else COLORS["primary"]
            self._paint_rounded_card(button, 0, 0, actual_width, actual_height, 9,
                                     COLORS["primary"] if primary else COLORS["line"])
            self._paint_rounded_card(button, 1, 1, actual_width - 1, actual_height - 1, 8, fill)
            button.create_text(actual_width // 2, actual_height // 2, text=label,
                               fill="#ffffff" if primary else COLORS["text"],
                               font=(FONT_FAMILY, 10, "bold" if primary else "normal"))

        button.bind("<Configure>", lambda _event: draw())
        button.bind("<Enter>", lambda _event: draw("hover"))
        button.bind("<Leave>", lambda _event: draw())
        button.bind("<ButtonPress-1>", lambda _event: draw("pressed"))
        button.bind("<ButtonRelease-1>", lambda event: (
            draw("hover"), command() if 0 <= event.x < button.winfo_width()
            and 0 <= event.y < button.winfo_height() else None
        ))
        button.bind("<Return>", lambda _event: command())
        button.bind("<space>", lambda _event: command())
        draw()
        return button
