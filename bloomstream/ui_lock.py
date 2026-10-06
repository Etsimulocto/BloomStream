from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def install_ui_lock(app_class):
    """Add a hard Pi-safe UI lock around preview and output modes.

    Modes:
      idle    -> normal editing controls
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

    def _walk(widget):
        yield widget
        try:
            for child in widget.winfo_children():
                yield from _walk(child)
        except tk.TclError:
            return

    def _disable_widget(widget):
        try:
            if isinstance(widget, ttk.Notebook):
                for tab_id in widget.tabs():
                    widget.tab(tab_id, state='disabled')
                return

            if isinstance(widget, ttk.Widget):
                # ttk's state API is more reliable across widget subclasses
                # than configure(state=...) checks on Raspberry Pi/Tk builds.
                widget.state(['disabled'])
                return

            if isinstance(widget, (tk.Text, tk.Entry, tk.Button, tk.Scale, tk.Checkbutton, tk.Spinbox, tk.Listbox)):
                widget.configure(state='disabled')
        except (tk.TclError, AttributeError):
            pass

    def _enable_widget(widget):
        try:
            if isinstance(widget, ttk.Notebook):
                for tab_id in widget.tabs():
                    widget.tab(tab_id, state='normal')
                return

            if isinstance(widget, ttk.Combobox):
                widget.state(['!disabled', 'readonly'])
                return

            if isinstance(widget, ttk.Widget):
                widget.state(['!disabled'])
                return

            if isinstance(widget, (tk.Text, tk.Entry, tk.Button, tk.Scale, tk.Checkbutton, tk.Spinbox, tk.Listbox)):
                widget.configure(state='normal')
        except (tk.TclError, AttributeError):
            pass

    def _lock_all(self):
        for widget in _walk(self):
            if widget is self:
                continue
            _disable_widget(widget)

    def _unlock_all(self):
        for widget in _walk(self):
            if widget is self:
                continue
            _enable_widget(widget)

        # These two buttons have special idle-state behavior.
        try:
            self.preview_btn.state(['!disabled'])
            self.preview_btn.configure(text='PREVIEW ON')
        except tk.TclError:
            pass
        try:
            self.stop_btn.state(['disabled'])
        except tk.TclError:
            pass

    def _apply_lock(self, mode: str):
        self._ui_lock_mode = mode

        if mode == 'preview':
            _lock_all(self)
            # The current Mixer tab must remain visible, but other notebook tabs
            # stay disabled. Only PREVIEW OFF is re-enabled.
            try:
                self.preview_btn.state(['!disabled'])
                self.preview_btn.configure(text='PREVIEW OFF')
            except tk.TclError:
                pass
            try:
                self.stop_btn.state(['disabled'])
            except tk.TclError:
                pass
            self.status.set('PREVIEW • controls locked for Pi safety')
            return

        if mode == 'output':
            _lock_all(self)
            try:
                self.stop_btn.state(['!disabled'])
            except tk.TclError:
                pass
            try:
                self.preview_btn.state(['disabled'])
            except tk.TclError:
                pass
            return

        _unlock_all(self)

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
