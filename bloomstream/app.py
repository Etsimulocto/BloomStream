from __future__ import annotations

from pathlib import Path
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .devices import DeviceChoice, detect_audio, detect_csi, detect_v4l2, diagnostics
from .model import AppConfig, AudioSource
from .pipeline import PipelineError, build_ffmpeg_command, shell_preview
from .program_preview import ProgramPreviewWorker

CONFIG_PATH = Path.home() / '.config' / 'bloomstream' / 'config.json'


class BloomStreamApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('BloomStream v0.3')
        self.geometry('1180x820')
        self.minsize(980, 700)

        self.config_data = AppConfig.load(CONFIG_PATH)
        self.process: subprocess.Popen | None = None
        self.preview_worker: ProgramPreviewWorker | None = None
        self.preview_enabled = False
        self.closing = False

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.preview_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.preview_image = None
        self.video_choices: list[DeviceChoice] = []
        self.audio_choices: list[DeviceChoice] = []
        self.panel_source_vars: list[tk.StringVar] = []
        self.panel_status_labels: list[tk.StringVar] = []
        self.audio_widgets: list[dict] = []

        self._style()
        self._ui()
        self.refresh_devices()
        self.after(100, self._drain_logs)
        self.after(120, self._drain_preview)

    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use('clam')
        except tk.TclError:
            pass
        self.configure(bg='#17191d')
        for n in ['TFrame', 'TLabel', 'TLabelframe', 'TCheckbutton', 'TNotebook']:
            try:
                s.configure(n, background='#17191d', foreground='#e8e8e8')
            except tk.TclError:
                pass
        s.configure('TLabelframe.Label', background='#17191d', foreground='#e8e8e8')

    def _ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill='x')
        ttk.Label(top, text='BloomStream', font=('Sans', 18, 'bold')).pack(side='left')
        ttk.Label(top, text='  4-panel Pi broadcaster').pack(side='left')
        ttk.Button(top, text='Refresh Devices', command=self.refresh_devices).pack(side='right')

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.mixer = ttk.Frame(nb, padding=10)
        self.audio = ttk.Frame(nb, padding=10)
        self.output = ttk.Frame(nb, padding=10)
        self.diag = ttk.Frame(nb, padding=10)
        for frame, title in [
            (self.mixer, 'Mixer'), (self.audio, 'Audio'),
            (self.output, 'Output'), (self.diag, 'Diagnostics')
        ]:
            nb.add(frame, text=title)

        self._mixer_ui()
        self._audio_ui()
        self._output_ui()
        self._diag_ui()

        bar = ttk.Frame(self, padding=(10, 0, 10, 8))
        bar.pack(fill='x')
        self.status = tk.StringVar(value='Ready')
        ttk.Label(bar, textvariable=self.status).pack(side='left')
        self.stop_btn = ttk.Button(bar, text='STOP', command=self.stop_output, state='disabled')
        self.stop_btn.pack(side='right', padx=(5, 0))
        ttk.Button(bar, text='RECORD', command=self.start_recording).pack(side='right', padx=(5, 0))
        ttk.Button(bar, text='GO LIVE', command=self.start_stream).pack(side='right')

    def _mixer_ui(self):
        controls = ttk.Frame(self.mixer)
        controls.pack(fill='x', pady=(0, 8))
        ttk.Label(controls, text='Layout:').pack(side='left')
        self.layout = tk.StringVar(value=self.config_data.layout)
        layout_box = ttk.Combobox(
            controls,
            textvariable=self.layout,
            state='readonly',
            width=22,
            values=['2x2', '1 large + 3 small', '2 vertical', '2 horizontal', 'fullscreen + PiP'],
        )
        layout_box.pack(side='left', padx=6)
        layout_box.bind('<<ComboboxSelected>>', lambda _e: self._layout_changed())

        self.preview_btn = ttk.Button(controls, text='PREVIEW ON', command=self.toggle_preview)
        self.preview_btn.pack(side='right')
        ttk.Label(controls, text='single shared preview • 640×360 @ 2 fps').pack(side='right', padx=8)

        preview_frame = ttk.LabelFrame(self.mixer, text='PROGRAM PREVIEW', padding=6)
        preview_frame.pack(fill='x', pady=(0, 8))
        self.preview_canvas = tk.Canvas(
            preview_frame,
            width=640,
            height=360,
            bg='#050607',
            highlightthickness=1,
            highlightbackground='#34383f',
        )
        self.preview_canvas.pack(anchor='center')
        self._draw_preview_status('Preview OFF\nPress PREVIEW ON to start one shared compositor preview.')

        grid = ttk.Frame(self.mixer)
        grid.pack(fill='both', expand=True)
        for c in range(2):
            grid.columnconfigure(c, weight=1)
        for r in range(2):
            grid.rowconfigure(r, weight=1)

        for i in range(4):
            card = ttk.LabelFrame(grid, text=f'PANEL {i+1}', padding=8)
            card.grid(row=i // 2, column=i % 2, sticky='nsew', padx=4, pady=4)

            source_var = tk.StringVar(value='Blank')
            self.panel_source_vars.append(source_var)
            status_var = tk.StringVar(value='Blank')
            self.panel_status_labels.append(status_var)

            row = ttk.Frame(card)
            row.pack(fill='x')
            ttk.Label(row, text='Source').pack(side='left')
            combo = ttk.Combobox(row, textvariable=source_var, state='readonly', width=34)
            combo.pack(side='left', fill='x', expand=True, padx=(8, 4))
            combo.bind('<<ComboboxSelected>>', lambda _e, j=i: self._source_changed(j))
            setattr(self, f'pcombo{i}', combo)
            ttk.Button(row, text='Settings', command=lambda j=i: self._panel_settings(j)).pack(side='right')

            ttk.Label(card, textvariable=status_var, justify='left').pack(anchor='w', pady=(8, 0))

    def _audio_ui(self):
        for i in range(3):
            frame = ttk.LabelFrame(self.audio, text=f'AUDIO BUS {i+1}', padding=8)
            frame.pack(fill='x', pady=4)
            device = tk.StringVar(value='No audio')
            mode = tk.StringVar(value='stereo')
            gain = tk.DoubleVar(value=0.0)
            pan = tk.DoubleVar(value=0.0)
            mute = tk.BooleanVar(value=False)

            ttk.Label(frame, text='Source').grid(row=0, column=0, sticky='w')
            cb = ttk.Combobox(frame, textvariable=device, state='readonly', width=46)
            cb.grid(row=0, column=1, columnspan=5, sticky='ew', padx=6)
            ttk.Label(frame, text='Mode').grid(row=1, column=0, sticky='w')
            ttk.Combobox(frame, textvariable=mode, state='readonly', width=9, values=['mono', 'stereo']).grid(row=1, column=1, sticky='w', padx=6)
            ttk.Label(frame, text='Gain dB').grid(row=1, column=2)
            ttk.Spinbox(frame, from_=-30, to=20, increment=.5, textvariable=gain, width=8).grid(row=1, column=3, padx=6)
            ttk.Label(frame, text='Pan').grid(row=1, column=4)
            ttk.Scale(frame, from_=-1, to=1, variable=pan, orient='horizontal', length=130).grid(row=1, column=5, padx=6)
            ttk.Checkbutton(frame, text='Mute', variable=mute).grid(row=1, column=6, padx=6)
            frame.columnconfigure(1, weight=1)
            self.audio_widgets.append(dict(device=device, mode=mode, gain=gain, pan=pan, mute=mute, combo=cb))

    def _output_ui(self):
        o = self.config_data.output
        frame = ttk.LabelFrame(self.output, text='PROGRAM OUTPUT', padding=12)
        frame.pack(fill='x')

        self.ow = tk.IntVar(value=o.width)
        self.oh = tk.IntVar(value=o.height)
        self.ofps = tk.IntVar(value=o.fps)
        self.ovb = tk.IntVar(value=o.video_bitrate_kbps)
        self.oab = tk.IntVar(value=o.audio_bitrate_kbps)
        self.endpoint = tk.StringVar(value=o.endpoint)
        self.key = tk.StringVar(value='')
        self.record = tk.StringVar(value=o.record_path)

        for c, (label, var) in enumerate([
            ('Width', self.ow), ('Height', self.oh), ('FPS', self.ofps),
            ('Video kbps', self.ovb), ('Audio kbps', self.oab),
        ]):
            ttk.Label(frame, text=label).grid(row=0, column=c, sticky='w', padx=4)
            ttk.Entry(frame, textvariable=var, width=11).grid(row=1, column=c, sticky='ew', padx=4)

        ttk.Label(frame, text='RTMP/RTMPS endpoint').grid(row=2, column=0, columnspan=2, sticky='w', padx=4, pady=(12, 0))
        ttk.Entry(frame, textvariable=self.endpoint).grid(row=3, column=0, columnspan=5, sticky='ew', padx=4)
        ttk.Label(frame, text='Stream key (memory only; never saved)').grid(row=4, column=0, columnspan=2, sticky='w', padx=4, pady=(12, 0))
        ttk.Entry(frame, textvariable=self.key, show='•').grid(row=5, column=0, columnspan=5, sticky='ew', padx=4)
        ttk.Label(frame, text='Recording path').grid(row=6, column=0, columnspan=2, sticky='w', padx=4, pady=(12, 0))
        ttk.Entry(frame, textvariable=self.record).grid(row=7, column=0, columnspan=4, sticky='ew', padx=4)
        ttk.Button(frame, text='Choose…', command=self._choose_record).grid(row=7, column=4, padx=4)
        for c in range(5):
            frame.columnconfigure(c, weight=1)

        ttk.Button(self.output, text='Show FFmpeg Command', command=self.show_command).pack(anchor='w', pady=10)
        self.cmd = tk.Text(self.output, height=12, bg='#090a0c', fg='#d8ffd8', insertbackground='white', wrap='word')
        self.cmd.pack(fill='both', expand=True)

    def _diag_ui(self):
        ttk.Button(self.diag, text='Run Diagnostics', command=self.run_diag).pack(anchor='w', pady=(0, 8))
        self.diagtext = tk.Text(self.diag, bg='#090a0c', fg='#e7e7e7', insertbackground='white', wrap='none')
        self.diagtext.pack(fill='both', expand=True)
        self.run_diag()

    def refresh_devices(self):
        self.video_choices = [
            DeviceChoice('Blank', '', 'blank'),
            DeviceChoice('Test Pattern', '', 'test'),
            DeviceChoice('Full Screen', '', 'screen'),
            DeviceChoice('Screen Area', '', 'area'),
        ] + detect_v4l2() + detect_csi()
        labels = [x.label for x in self.video_choices]
        for i in range(4):
            getattr(self, f'pcombo{i}')['values'] = labels

        for i, panel in enumerate(self.config_data.panels[:4]):
            selected = 'Blank'
            for choice in self.video_choices:
                if choice.kind == panel.source.kind and (not choice.value or choice.value == panel.source.device):
                    selected = choice.label
                    break
            self.panel_source_vars[i].set(selected)
            self._update_panel_status(i)

        self.audio_choices = detect_audio()
        audio_labels = [x.label for x in self.audio_choices]
        for row in self.audio_widgets:
            row['combo']['values'] = audio_labels

        self.status.set(f'Found {len(detect_v4l2())} V4L2 camera(s), {len(detect_csi())} CSI camera(s)')

    def _choice(self, label: str) -> DeviceChoice:
        return next((c for c in self.video_choices if c.label == label), DeviceChoice('Blank', '', 'blank'))

    def _update_panel_status(self, i: int):
        src = self.config_data.panels[i].source
        detail = src.name or src.kind
        if src.device:
            detail += f'\n{src.device}'
        detail += f'\n{src.width}×{src.height} @ {src.fps} fps'
        self.panel_status_labels[i].set(detail)

    def _layout_changed(self):
        self._save()
        self._preview_config_changed()

    def _source_changed(self, i: int):
        choice = self._choice(self.panel_source_vars[i].get())
        src = self.config_data.panels[i].source
        src.kind, src.name, src.device = choice.kind, choice.label, choice.value
        if choice.kind == 'screen':
            src.width, src.height, src.x, src.y = self.winfo_screenwidth(), self.winfo_screenheight(), 0, 0
        if choice.kind == 'area':
            src.area_width = min(1280, self.winfo_screenwidth())
            src.area_height = min(720, self.winfo_screenheight())
        self._save()
        self._update_panel_status(i)
        self._preview_config_changed()

    def _panel_settings(self, i: int):
        src = self.config_data.panels[i].source
        win = tk.Toplevel(self)
        win.title(f'Panel {i+1} settings')
        win.transient(self)
        vars_ = {
            k: (tk.StringVar(value=getattr(src, k)) if k in ['pixel_format', 'fit']
                else tk.BooleanVar(value=getattr(src, k)) if k in ['hflip', 'vflip']
                else tk.IntVar(value=getattr(src, k)))
            for k in ['width', 'height', 'fps', 'pixel_format', 'x', 'y', 'area_width', 'area_height', 'fit', 'rotation', 'hflip', 'vflip']
        }
        row = 0
        for key in ['width', 'height', 'fps', 'pixel_format', 'x', 'y', 'area_width', 'area_height']:
            ttk.Label(win, text=key.replace('_', ' ').title()).grid(row=row, column=0, sticky='w', padx=8, pady=4)
            ttk.Entry(win, textvariable=vars_[key], width=16).grid(row=row, column=1, padx=8, pady=4)
            row += 1
        ttk.Label(win, text='Fit').grid(row=row, column=0, sticky='w', padx=8)
        ttk.Combobox(win, textvariable=vars_['fit'], state='readonly', values=['fit', 'fill', 'stretch']).grid(row=row, column=1, padx=8)
        row += 1
        ttk.Label(win, text='Rotation').grid(row=row, column=0, sticky='w', padx=8)
        ttk.Combobox(win, textvariable=vars_['rotation'], state='readonly', values=[0, 90, 180, 270]).grid(row=row, column=1, padx=8)
        row += 1
        ttk.Checkbutton(win, text='Horizontal flip', variable=vars_['hflip']).grid(row=row, column=0, padx=8, pady=4)
        ttk.Checkbutton(win, text='Vertical flip', variable=vars_['vflip']).grid(row=row, column=1, padx=8, pady=4)
        row += 1

        def apply():
            for key, value in vars_.items():
                setattr(src, key, value.get())
            self._save()
            self._update_panel_status(i)
            win.destroy()
            self._preview_config_changed()

        ttk.Button(win, text='Apply', command=apply).grid(row=row, column=0, columnspan=2, pady=10)

    def _choose_record(self):
        path = filedialog.asksaveasfilename(
            title='Recording file',
            defaultextension='.mkv',
            filetypes=[('Matroska', '*.mkv'), ('MP4', '*.mp4'), ('All files', '*.*')],
        )
        if path:
            self.record.set(path)

    def _save(self):
        self.config_data.layout = self.layout.get()
        out = self.config_data.output
        try:
            out.width = int(self.ow.get())
            out.height = int(self.oh.get())
            out.fps = int(self.ofps.get())
            out.video_bitrate_kbps = int(self.ovb.get())
            out.audio_bitrate_kbps = int(self.oab.get())
        except Exception:
            pass
        out.endpoint = self.endpoint.get().strip()
        out.record_path = self.record.get().strip()
        out.stream_key = self.key.get().strip()

        self.config_data.audio = []
        for row in self.audio_widgets:
            label = str(row['device'].get())
            device = next((x.value for x in self.audio_choices if x.label == label), '')
            self.config_data.audio.append(AudioSource(
                name=label,
                device=device,
                mode=str(row['mode'].get()),
                gain_db=float(row['gain'].get()),
                pan=float(row['pan'].get()),
                mute=bool(row['mute'].get()),
                sample_rate=out.sample_rate,
            ))
        self.config_data.save(CONFIG_PATH)

    def show_command(self):
        self._save()
        try:
            text = shell_preview(build_ffmpeg_command(self.config_data, 'stream'), self.config_data.output.stream_key)
        except PipelineError as exc:
            text = f'Cannot build stream command yet:\n{exc}'
        self.cmd.delete('1.0', 'end')
        self.cmd.insert('1.0', text)

    def _draw_preview_status(self, text: str, error: bool = False):
        self.preview_canvas.delete('all')
        self.preview_canvas.create_text(
            16, 16,
            anchor='nw',
            fill='#ffb0b0' if error else '#8dffbd',
            text=text,
            font=('Monospace', 11),
        )

    def toggle_preview(self):
        if self.preview_enabled:
            self.stop_preview()
        else:
            self.start_preview()

    def start_preview(self):
        if self.process and self.process.poll() is None:
            messagebox.showwarning('BloomStream', 'Stop RECORD/LIVE before starting preview.')
            return
        if self.preview_enabled:
            return
        self._save()
        self.preview_enabled = True
        self.preview_btn.configure(text='PREVIEW OFF')
        self._draw_preview_status('Starting one shared program preview…')
        self.preview_worker = ProgramPreviewWorker(
            self.config_data,
            lambda data: self.preview_queue.put(('frame', data)),
            lambda text: self.preview_queue.put(('error', text)),
            lambda: self.preview_queue.put(('exit', '')),
        )
        self.preview_worker.start()

    def stop_preview(self):
        self.preview_enabled = False
        worker = self.preview_worker
        self.preview_worker = None
        if worker:
            worker.stop()
        self.preview_btn.configure(text='PREVIEW ON')
        self.preview_image = None
        self._draw_preview_status('Preview OFF')

    def _preview_config_changed(self):
        if self.preview_enabled:
            self.stop_preview()
            self.after(250, self.start_preview)

    def _drain_preview(self):
        try:
            while True:
                kind, payload = self.preview_queue.get_nowait()
                if kind == 'frame' and self.preview_enabled:
                    try:
                        img = tk.PhotoImage(data=payload, format='PPM')
                        self.preview_image = img
                        self.preview_canvas.delete('all')
                        self.preview_canvas.create_image(320, 180, image=img, anchor='center')
                    except tk.TclError as exc:
                        self._draw_preview_status(f'Preview decode error\n{exc}', error=True)
                elif kind == 'error' and self.preview_enabled:
                    self._draw_preview_status(f'Preview unavailable\n{payload[:300]}', error=True)
                elif kind == 'exit' and self.preview_enabled:
                    # Do not automatically restart. Explicit preview stays safe and predictable.
                    self.preview_enabled = False
                    self.preview_btn.configure(text='PREVIEW ON')
        except queue.Empty:
            pass
        if not self.closing:
            self.after(120, self._drain_preview)

    def start_stream(self):
        self._start('stream')

    def start_recording(self):
        self._start('record')

    def _start(self, mode: str):
        if self.process and self.process.poll() is None:
            messagebox.showwarning('BloomStream', 'An output is already running.')
            return
        self._save()
        self.stop_preview()
        try:
            cmd = build_ffmpeg_command(self.config_data, mode)
        except PipelineError as exc:
            messagebox.showerror('BloomStream', str(exc))
            return

        self.cmd.delete('1.0', 'end')
        self.cmd.insert('1.0', shell_preview(cmd, self.config_data.output.stream_key) + '\n\n')
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            messagebox.showerror('BloomStream', 'ffmpeg not found. Run ./install.sh')
            return

        self.stop_btn.configure(state='normal')
        self.status.set('LIVE' if mode == 'stream' else 'RECORDING')
        threading.Thread(target=self._watch_output, daemon=True).start()

    def _watch_output(self):
        proc = self.process
        if proc and proc.stderr:
            for line in proc.stderr:
                self.log_queue.put(line)
        if proc:
            self.log_queue.put(f'\n[FFmpeg exited with code {proc.wait()}]\n')
        if not self.closing:
            self.after(0, self._output_done)

    def _output_done(self):
        self.stop_btn.configure(state='disabled')
        self.status.set('Stopped')

    def stop_output(self):
        proc = self.process
        if proc and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write('q\n')
                    proc.stdin.flush()
                proc.wait(timeout=5)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
        self.stop_btn.configure(state='disabled')
        self.status.set('Stopped')

    def _drain_logs(self):
        try:
            while True:
                self.cmd.insert('end', self.log_queue.get_nowait())
                self.cmd.see('end')
        except queue.Empty:
            pass
        if not self.closing:
            self.after(100, self._drain_logs)

    def run_diag(self):
        self.diagtext.delete('1.0', 'end')
        self.diagtext.insert('1.0', diagnostics())

    def shutdown(self):
        # Window close must never wait on preview workers.
        self.closing = True
        worker = self.preview_worker
        self.preview_worker = None
        if worker:
            try:
                worker.stop()
            except Exception:
                pass
        proc = self.process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        self.destroy()


def main():
    app = BloomStreamApp()
    app.protocol('WM_DELETE_WINDOW', app.shutdown)
    app.mainloop()
