from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def install_ui_lock(app_class):
    """Add a hard Pi-safe modal shield around preview and output modes.

    Instead of relying on individual widget disabled states, this puts one
    lightweight Toplevel over BloomStream and grabs input while FFmpeg owns
    capture devices. The only clickable control is the matching STOP button.
    """

    original_init = app_class.__init__
    original_start_preview = app_class.start_preview
    original_stop_preview = app_class.stop_preview
    original_drain_preview = app_class._drain_preview
    original_start = app_class._start
    original_output_done = app_class._output_done
    original_stop_output = app_class.stop_output

    def _destroy_shield(self):
        shield = getattr(self, '_safety_shield', None)
        self._safety_shield = None
        if shield is None:
            return
        try:
            shield.grab_release()
        except tk.TclError:
            pass
        try:
            shield.destroy()
        except tk.TclError:
            pass

    def _sync_shield_geometry(self):
        shield = getattr(self, '_safety_shield', None)
        if shield is None:
            return
        try:
            self.update_idletasks()
            w = max(1, self.winfo_width())
            h = max(1, self.winfo_height())
            x = self.winfo_rootx()
            y = self.winfo_rooty()
            shield.geometry(f'{w}x{h}+{x}+{y}')
            shield.lift()
        except tk.TclError:
            pass

    def _show_shield(self, mode: str):
        _destroy_shield(self)

        shield = tk.Toplevel(self)
        self._safety_shield = shield
        shield.overrideredirect(True)
        shield.transient(self)
        shield.configure(bg='#0d0f12')

        outer = tk.Frame(shield, bg='#0d0f12', bd=0)
        outer.pack(fill='both', expand=True)

        box = tk.Frame(outer, bg='#17191d', padx=34, pady=28,
                       highlightthickness=1, highlightbackground='#3f464f')
        box.place(relx=.5, rely=.5, anchor='center')

        if mode == 'preview':
            title = 'PREVIEW RUNNING'
            detail = 'Pi safety lock active\nEditing is disabled until preview stops.'
            button_text = 'STOP PREVIEW'
            command = self.stop_preview
        else:
            live = str(self.status.get()).upper() == 'LIVE'
            title = 'LIVE' if live else 'RECORDING'
            detail = 'Pi safety lock active\nControls are disabled until output stops.'
            button_text = 'STOP LIVE' if live else 'STOP RECORDING'
            command = self.stop_output

        tk.Label(box, text=title, bg='#17191d', fg='#8dffbd',
                 font=('Sans', 20, 'bold')).pack(pady=(0, 10))
        tk.Label(box, text=detail, bg='#17191d', fg='#d8d8d8',
                 justify='center', font=('Sans', 11)).pack(pady=(0, 18))
        ttk.Button(box, text=button_text, command=command).pack(ipadx=24, ipady=8)

        _sync_shield_geometry(self)
        try:
            shield.grab_set()
            shield.focus_force()
        except tk.TclError:
            pass

        self._ui_lock_mode = mode
        if mode == 'preview':
            self.status.set('PREVIEW • Pi safety lock active')

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._ui_lock_mode = 'idle'
        self._safety_shield = None
        # Keep the shield covering the client area if the window moves/resizes.
        self.bind('<Configure>', lambda _event: self.after_idle(lambda: _sync_shield_geometry(self)), add='+')

    def start_preview(self):
        original_start_preview(self)
        if self.preview_enabled:
            _show_shield(self, 'preview')

    def stop_preview(self):
        original_stop_preview(self)
        _destroy_shield(self)
        self._ui_lock_mode = 'idle'

    def _drain_preview(self):
        original_drain_preview(self)
        if (
            getattr(self, '_ui_lock_mode', 'idle') == 'preview'
            and not self.preview_enabled
            and not (self.process and self.process.poll() is None)
        ):
            _destroy_shield(self)
            self._ui_lock_mode = 'idle'

    def _start(self, mode: str):
        original_start(self, mode)
        if self.process and self.process.poll() is None:
            _show_shield(self, 'output')

    def _output_done(self):
        original_output_done(self)
        _destroy_shield(self)
        self._ui_lock_mode = 'idle'

    def stop_output(self):
        original_stop_output(self)
        _destroy_shield(self)
        self._ui_lock_mode = 'idle'

    app_class.__init__ = __init__
    app_class.start_preview = start_preview
    app_class.stop_preview = stop_preview
    app_class._drain_preview = _drain_preview
    app_class._start = _start
    app_class._output_done = _output_done
    app_class.stop_output = stop_output
    return app_class
