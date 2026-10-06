from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk

from .audio_meter import AudioMeterWorker


def install_audio_meter(app_class):
    """Bolt a lightweight master meter onto BloomStream without touching FFmpeg."""

    original_init = app_class.__init__
    original_mixer_ui = app_class._mixer_ui
    original_audio_ui = app_class._audio_ui
    original_refresh_devices = app_class.refresh_devices
    original_shutdown = app_class.shutdown

    def __init__(self, *args, **kwargs):
        self.audio_meter_queue = queue.Queue()
        self.audio_meter_worker = None
        self.audio_meter_device = ''
        original_init(self, *args, **kwargs)
        self.after(150, self._drain_audio_meter)
        self.after(250, self._sync_audio_meter)

    def _mixer_ui(self):
        original_mixer_ui(self)

        children = self.mixer.winfo_children()
        grid = children[-1] if children else None

        meter = ttk.LabelFrame(self.mixer, text='MASTER AUDIO • follows Audio Bus 1', padding=6)
        if grid is not None:
            meter.pack(fill='x', pady=(0, 8), before=grid)
        else:
            meter.pack(fill='x', pady=(0, 8))

        self.audio_meter_l = tk.DoubleVar(value=0.0)
        self.audio_meter_r = tk.DoubleVar(value=0.0)
        self.audio_meter_text = tk.StringVar(value='No audio source selected')

        ttk.Label(meter, text='L', width=2).grid(row=0, column=0, sticky='w')
        ttk.Progressbar(
            meter,
            variable=self.audio_meter_l,
            maximum=100.0,
            orient='horizontal',
        ).grid(row=0, column=1, sticky='ew', padx=(4, 8))

        ttk.Label(meter, text='R', width=2).grid(row=1, column=0, sticky='w')
        ttk.Progressbar(
            meter,
            variable=self.audio_meter_r,
            maximum=100.0,
            orient='horizontal',
        ).grid(row=1, column=1, sticky='ew', padx=(4, 8))

        ttk.Label(meter, textvariable=self.audio_meter_text, width=24).grid(
            row=0, column=2, rowspan=2, sticky='w', padx=(4, 0)
        )
        meter.columnconfigure(1, weight=1)

    def _audio_ui(self):
        original_audio_ui(self)
        if self.audio_widgets:
            self.audio_widgets[0]['combo'].bind(
                '<<ComboboxSelected>>',
                lambda _event: self.after(10, self._sync_audio_meter),
                add='+',
            )

    def refresh_devices(self):
        original_refresh_devices(self)
        self.after(10, self._sync_audio_meter)

    def _selected_meter_device(self) -> str:
        if not self.audio_widgets:
            return ''
        label = str(self.audio_widgets[0]['device'].get())
        return next((choice.value for choice in self.audio_choices if choice.label == label), '')

    def _sync_audio_meter(self):
        if getattr(self, 'closing', False):
            return

        device = self._selected_meter_device()
        if device == getattr(self, 'audio_meter_device', ''):
            return

        worker = getattr(self, 'audio_meter_worker', None)
        self.audio_meter_worker = None
        if worker:
            worker.stop()

        self.audio_meter_device = device
        self.audio_meter_l.set(0.0)
        self.audio_meter_r.set(0.0)

        if not device:
            self.audio_meter_text.set('No audio source selected')
            return

        self.audio_meter_text.set('Starting meter…')
        worker = AudioMeterWorker(
            device,
            lambda lp, rp, ldb, rdb: self.audio_meter_queue.put(('level', (lp, rp, ldb, rdb))),
            lambda text: self.audio_meter_queue.put(('error', text)),
        )
        self.audio_meter_worker = worker
        worker.start()

    def _drain_audio_meter(self):
        try:
            while True:
                kind, payload = self.audio_meter_queue.get_nowait()
                if kind == 'level':
                    lp, rp, ldb, rdb = payload
                    self.audio_meter_l.set(lp)
                    self.audio_meter_r.set(rp)
                    peak = max(ldb, rdb)
                    self.audio_meter_text.set(f'{peak:5.1f} dBFS')
                elif kind == 'error':
                    self.audio_meter_l.set(0.0)
                    self.audio_meter_r.set(0.0)
                    self.audio_meter_text.set('Meter unavailable')
        except queue.Empty:
            pass

        if not getattr(self, 'closing', False):
            self.after(100, self._drain_audio_meter)

    def shutdown(self):
        worker = getattr(self, 'audio_meter_worker', None)
        self.audio_meter_worker = None
        if worker:
            try:
                worker.stop()
            except Exception:
                pass
        original_shutdown(self)

    app_class.__init__ = __init__
    app_class._mixer_ui = _mixer_ui
    app_class._audio_ui = _audio_ui
    app_class.refresh_devices = refresh_devices
    app_class._selected_meter_device = _selected_meter_device
    app_class._sync_audio_meter = _sync_audio_meter
    app_class._drain_audio_meter = _drain_audio_meter
    app_class.shutdown = shutdown
    return app_class
