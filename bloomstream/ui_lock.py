from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def install_ui_lock(app_class):
    """Add Pi-safe control locking without changing capture/encode code.

    Modes:
      idle    -> controls available normally
      preview -> only PREVIEW OFF remains usable
      output  -> only STOP remains usable
    """

    original_init = app_class.__init__
    original_start_preview = app_class.start_preview
    original_stop_preview = app_class.stop_preview
    original_drain_preview = app_class._drain_preview
    original_start = app_class._start
    original_output_done = app_class._output_done
    original_stop_output = app_class.stop_output

    def _set_widget_locked(widget, locked: bool, allowed: set[tk.Misc]):
        if widget in allowed:
            try:
                widget.configure(state='normal')
            except tk.TclError:
                pass
        else:
            if isinstance(widget, ttk.Notebook):
                try:
                    for tab_id in widget.tabs():
                        widget.tab(tab_id, state='disabled' if locked else 'normal')
                except tk.TclError:
                    pass
            elif isinstance(widget, ttk.Combobox):
                try:
                    widget.configure(state='disabled' if locked else 'readonly')
                except tk.TclError:
                    pass
            elif isinstance(widget, (ttk.Button, ttk.Entry, ttk.Spinbox, ttk.Scale, ttk.Checkbutton)):
                try:
                    widget.configure(state='disabled' if locked else 'normal')
                except tk.TclError:
                    pass
            elif isinstance(widget, tk.Text):
                try:
                    widget.configure(state='disabled' if locked else 'normal')
                except tk.TclError:
                    pass

        try:
            for child in widget.winfo_children():
                _set_widget_locked(child, locked, allowed)
        except tk.TclError:
            pass

    def _apply_lock(self, mode: str):
        if getattr(self, '_ui_lock_mode', None) == mode:
            return

        self._ui_lock_mode = mode
        if mode == 'preview':
            allowed = {self.preview_btn}
            _set_widget_locked(self, True, allowed)
            self.preview_btn.configure(state='normal', text='PREVIEW OFF')
            self.stop_btn.configure(state='disabled')
            self.status.set('PREVIEW • controls locked for Pi safety')
        elif mode == 'output':
            allowed = {self.stop_btn}
            _set_widget_locked(self, True, allowed)
            self.stop_btn.configure(state='normal')
            self.preview_btn.configure(state='disabled')
        else:
            _set_widget_locked(self, False, set())
            self.preview_btn.configure(state='normal', text='PREVIEW ON')
            self.stop_btn.configure(state='disabled')

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._ui_lock_mode = 'idle'

    def start_preview(self):
        original_start_preview(self)
        if self.preview_enabled:
            _apply_lock(self, 'preview')

    def stop_preview(self):
        original_stop_preview(self)
        if not (self.process and self.process.poll() is None):
            _apply_lock(self, 'idle')

    def _drain_preview(self):
        original_drain_preview(self)
        if (
            getattr(self, '_ui_lock_mode', 'idle') == 'preview'
            and not self.preview_enabled
            and not (self.process and self.process.poll() is None)
        ):
            _apply_lock(self, 'idle')

    def _start(self, mode: str):
        original_start(self, mode)
        if self.process and self.process.poll() is None:
            _apply_lock(self, 'output')

    def _output_done(self):
        original_output_done(self)
        _apply_lock(self, 'idle')

    def stop_output(self):
        original_stop_output(self)
        if not self.preview_enabled:
            _apply_lock(self, 'idle')

    app_class.__init__ = __init__
    app_class.start_preview = start_preview
    app_class.stop_preview = stop_preview
    app_class._drain_preview = _drain_preview
    app_class._start = _start
    app_class._output_done = _output_done
    app_class.stop_output = stop_output
    return app_class
