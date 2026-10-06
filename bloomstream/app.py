from __future__ import annotations
from pathlib import Path
import queue, subprocess, threading, tkinter as tk
from tkinter import filedialog, messagebox, ttk
from .devices import DeviceChoice, detect_audio, detect_csi, detect_v4l2, diagnostics
from .model import AppConfig, AudioSource
from .pipeline import PipelineError, build_ffmpeg_command, shell_preview

CONFIG_PATH=Path.home()/'.config'/'bloomstream'/'config.json'

class BloomStreamApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('BloomStream v0.1'); self.geometry('1180x760'); self.minsize(980,650)
        self.config_data=AppConfig.load(CONFIG_PATH); self.process=None; self.log_queue=queue.Queue(); self.video_choices=[]; self.audio_choices=[]; self.panel_source_vars=[]; self.audio_widgets=[]
        self._style(); self._ui(); self.refresh_devices(); self.after(100,self._drain)

    def _style(self):
        s=ttk.Style(self)
        try: s.theme_use('clam')
        except tk.TclError: pass
        self.configure(bg='#17191d')
        for n in ['TFrame','TLabel','TLabelframe','TCheckbutton','TNotebook']:
            try: s.configure(n,background='#17191d',foreground='#e8e8e8')
            except tk.TclError: pass
        s.configure('TLabelframe.Label',background='#17191d',foreground='#e8e8e8')

    def _ui(self):
        top=ttk.Frame(self,padding=10); top.pack(fill='x')
        ttk.Label(top,text='BloomStream',font=('Sans',18,'bold')).pack(side='left'); ttk.Label(top,text='  4-panel Pi broadcaster').pack(side='left'); ttk.Button(top,text='Refresh Devices',command=self.refresh_devices).pack(side='right')
        nb=ttk.Notebook(self); nb.pack(fill='both',expand=True,padx=10,pady=(0,10))
        self.mixer=ttk.Frame(nb,padding=10); self.audio=ttk.Frame(nb,padding=10); self.output=ttk.Frame(nb,padding=10); self.diag=ttk.Frame(nb,padding=10)
        for f,t in [(self.mixer,'Mixer'),(self.audio,'Audio'),(self.output,'Output'),(self.diag,'Diagnostics')]: nb.add(f,text=t)
        self._mixer(); self._audio(); self._output(); self._diag()
        bar=ttk.Frame(self,padding=(10,0,10,8)); bar.pack(fill='x'); self.status=tk.StringVar(value='Ready'); ttk.Label(bar,textvariable=self.status).pack(side='left'); self.stop_btn=ttk.Button(bar,text='STOP',command=self.stop_output,state='disabled'); self.stop_btn.pack(side='right',padx=(5,0)); ttk.Button(bar,text='RECORD',command=self.start_recording).pack(side='right',padx=(5,0)); ttk.Button(bar,text='GO LIVE',command=self.start_stream).pack(side='right')

    def _mixer(self):
        row=ttk.Frame(self.mixer); row.pack(fill='x',pady=(0,8)); ttk.Label(row,text='Layout:').pack(side='left'); self.layout=tk.StringVar(value=self.config_data.layout)
        cb=ttk.Combobox(row,textvariable=self.layout,state='readonly',width=22,values=['2x2','1 large + 3 small','2 vertical','2 horizontal','fullscreen + PiP']); cb.pack(side='left',padx=6); cb.bind('<<ComboboxSelected>>',lambda e:self._save())
        grid=ttk.Frame(self.mixer); grid.pack(fill='both',expand=True)
        for c in range(2): grid.columnconfigure(c,weight=1)
        for r in range(2): grid.rowconfigure(r,weight=1)
        for i in range(4):
            card=ttk.LabelFrame(grid,text=f'PANEL {i+1}',padding=8); card.grid(row=i//2,column=i%2,sticky='nsew',padx=4,pady=4)
            v=tk.StringVar(value='Blank'); self.panel_source_vars.append(v); rr=ttk.Frame(card); rr.pack(fill='x'); ttk.Label(rr,text='Source').pack(side='left')
            combo=ttk.Combobox(rr,textvariable=v,state='readonly',width=34); combo.pack(side='left',fill='x',expand=True,padx=(8,4)); combo.bind('<<ComboboxSelected>>',lambda e,j=i:self._source_changed(j)); setattr(self,f'pcombo{i}',combo)
            ttk.Button(rr,text='Settings',command=lambda j=i:self._panel_settings(j)).pack(side='right')
            cv=tk.Canvas(card,bg='#050607',highlightthickness=1,highlightbackground='#34383f'); cv.pack(fill='both',expand=True,pady=(8,0)); cv.create_text(10,10,anchor='nw',fill='#8dffbd',text=f'PANEL {i+1}\nprogram-side preview in v0.1',font=('Monospace',10))

    def _audio(self):
        for i in range(3):
            f=ttk.LabelFrame(self.audio,text=f'AUDIO BUS {i+1}',padding=8); f.pack(fill='x',pady=4)
            device=tk.StringVar(value='No audio'); mode=tk.StringVar(value='stereo'); gain=tk.DoubleVar(value=0.0); pan=tk.DoubleVar(value=0.0); mute=tk.BooleanVar(value=False)
            ttk.Label(f,text='Source').grid(row=0,column=0,sticky='w'); cb=ttk.Combobox(f,textvariable=device,state='readonly',width=46); cb.grid(row=0,column=1,columnspan=5,sticky='ew',padx=6)
            ttk.Label(f,text='Mode').grid(row=1,column=0,sticky='w'); ttk.Combobox(f,textvariable=mode,state='readonly',width=9,values=['mono','stereo']).grid(row=1,column=1,sticky='w',padx=6)
            ttk.Label(f,text='Gain dB').grid(row=1,column=2); ttk.Spinbox(f,from_=-30,to=20,increment=.5,textvariable=gain,width=8).grid(row=1,column=3,padx=6)
            ttk.Label(f,text='Pan').grid(row=1,column=4); ttk.Scale(f,from_=-1,to=1,variable=pan,orient='horizontal',length=130).grid(row=1,column=5,padx=6); ttk.Checkbutton(f,text='Mute',variable=mute).grid(row=1,column=6,padx=6)
            f.columnconfigure(1,weight=1); self.audio_widgets.append(dict(device=device,mode=mode,gain=gain,pan=pan,mute=mute,combo=cb))

    def _output(self):
        o=self.config_data.output; f=ttk.LabelFrame(self.output,text='PROGRAM OUTPUT',padding=12); f.pack(fill='x')
        self.ow=tk.IntVar(value=o.width); self.oh=tk.IntVar(value=o.height); self.ofps=tk.IntVar(value=o.fps); self.ovb=tk.IntVar(value=o.video_bitrate_kbps); self.oab=tk.IntVar(value=o.audio_bitrate_kbps); self.endpoint=tk.StringVar(value=o.endpoint); self.key=tk.StringVar(value=''); self.record=tk.StringVar(value=o.record_path)
        for c,(lab,var) in enumerate([('Width',self.ow),('Height',self.oh),('FPS',self.ofps),('Video kbps',self.ovb),('Audio kbps',self.oab)]):
            ttk.Label(f,text=lab).grid(row=0,column=c,sticky='w',padx=4); ttk.Entry(f,textvariable=var,width=11).grid(row=1,column=c,sticky='ew',padx=4)
        ttk.Label(f,text='RTMP/RTMPS endpoint').grid(row=2,column=0,columnspan=2,sticky='w',padx=4,pady=(12,0)); ttk.Entry(f,textvariable=self.endpoint).grid(row=3,column=0,columnspan=5,sticky='ew',padx=4)
        ttk.Label(f,text='Stream key (memory only; never saved)').grid(row=4,column=0,columnspan=2,sticky='w',padx=4,pady=(12,0)); ttk.Entry(f,textvariable=self.key,show='•').grid(row=5,column=0,columnspan=5,sticky='ew',padx=4)
        ttk.Label(f,text='Recording path').grid(row=6,column=0,columnspan=2,sticky='w',padx=4,pady=(12,0)); ttk.Entry(f,textvariable=self.record).grid(row=7,column=0,columnspan=4,sticky='ew',padx=4); ttk.Button(f,text='Choose…',command=self._choose_record).grid(row=7,column=4,padx=4)
        for c in range(5): f.columnconfigure(c,weight=1)
        ttk.Button(self.output,text='Show FFmpeg Command',command=self.show_command).pack(anchor='w',pady=10); self.cmd=tk.Text(self.output,height=12,bg='#090a0c',fg='#d8ffd8',insertbackground='white',wrap='word'); self.cmd.pack(fill='both',expand=True)

    def _diag(self):
        ttk.Button(self.diag,text='Run Diagnostics',command=self.run_diag).pack(anchor='w',pady=(0,8)); self.diagtext=tk.Text(self.diag,bg='#090a0c',fg='#e7e7e7',insertbackground='white',wrap='none'); self.diagtext.pack(fill='both',expand=True); self.run_diag()

    def refresh_devices(self):
        self.video_choices=[DeviceChoice('Blank','','blank'),DeviceChoice('Test Pattern','','test'),DeviceChoice('Full Screen','','screen'),DeviceChoice('Screen Area','','area')]+detect_v4l2()+detect_csi(); labels=[x.label for x in self.video_choices]
        for i in range(4): getattr(self,f'pcombo{i}')['values']=labels
        for i,p in enumerate(self.config_data.panels[:4]):
            selected='Blank'
            for c in self.video_choices:
                if c.kind==p.source.kind and (not c.value or c.value==p.source.device): selected=c.label; break
            self.panel_source_vars[i].set(selected)
        self.audio_choices=detect_audio(); al=[x.label for x in self.audio_choices]
        for r in self.audio_widgets: r['combo']['values']=al
        self.status.set(f'Found {len(detect_v4l2())} V4L2 camera(s), {len(detect_csi())} CSI camera(s)')

    def _choice(self,label): return next((c for c in self.video_choices if c.label==label),DeviceChoice('Blank','','blank'))

    def _source_changed(self,i):
        c=self._choice(self.panel_source_vars[i].get()); s=self.config_data.panels[i].source; s.kind,s.name,s.device=c.kind,c.label,c.value
        if c.kind=='screen': s.width,s.height,s.x,s.y=self.winfo_screenwidth(),self.winfo_screenheight(),0,0
        if c.kind=='area': s.area_width,s.area_height=min(1280,self.winfo_screenwidth()),min(720,self.winfo_screenheight())
        self._save()

    def _panel_settings(self,i):
        s=self.config_data.panels[i].source; w=tk.Toplevel(self); w.title(f'Panel {i+1} settings'); w.transient(self)
        vars={k:(tk.StringVar(value=getattr(s,k)) if k in ['pixel_format','fit'] else tk.BooleanVar(value=getattr(s,k)) if k in ['hflip','vflip'] else tk.IntVar(value=getattr(s,k))) for k in ['width','height','fps','pixel_format','x','y','area_width','area_height','fit','rotation','hflip','vflip']}
        r=0
        for k in ['width','height','fps','pixel_format','x','y','area_width','area_height']:
            ttk.Label(w,text=k.replace('_',' ').title()).grid(row=r,column=0,sticky='w',padx=8,pady=4); ttk.Entry(w,textvariable=vars[k],width=16).grid(row=r,column=1,padx=8,pady=4); r+=1
        ttk.Label(w,text='Fit').grid(row=r,column=0,sticky='w',padx=8); ttk.Combobox(w,textvariable=vars['fit'],state='readonly',values=['fit','fill','stretch']).grid(row=r,column=1,padx=8); r+=1
        ttk.Label(w,text='Rotation').grid(row=r,column=0,sticky='w',padx=8); ttk.Combobox(w,textvariable=vars['rotation'],state='readonly',values=[0,90,180,270]).grid(row=r,column=1,padx=8); r+=1
        ttk.Checkbutton(w,text='Horizontal flip',variable=vars['hflip']).grid(row=r,column=0,padx=8,pady=4); ttk.Checkbutton(w,text='Vertical flip',variable=vars['vflip']).grid(row=r,column=1,padx=8,pady=4); r+=1
        def apply():
            for k,v in vars.items(): setattr(s,k,v.get())
            self._save(); w.destroy()
        ttk.Button(w,text='Apply',command=apply).grid(row=r,column=0,columnspan=2,pady=10)

    def _choose_record(self):
        p=filedialog.asksaveasfilename(title='Recording file',defaultextension='.mkv',filetypes=[('Matroska','*.mkv'),('MP4','*.mp4'),('All files','*.*')])
        if p: self.record.set(p)

    def _save(self):
        self.config_data.layout=self.layout.get(); o=self.config_data.output
        try: o.width=int(self.ow.get()); o.height=int(self.oh.get()); o.fps=int(self.ofps.get()); o.video_bitrate_kbps=int(self.ovb.get()); o.audio_bitrate_kbps=int(self.oab.get())
        except Exception: pass
        o.endpoint=self.endpoint.get().strip(); o.record_path=self.record.get().strip(); o.stream_key=self.key.get().strip(); self.config_data.audio=[]
        for r in self.audio_widgets:
            lab=str(r['device'].get()); dev=next((x.value for x in self.audio_choices if x.label==lab),'')
            self.config_data.audio.append(AudioSource(name=lab,device=dev,mode=str(r['mode'].get()),gain_db=float(r['gain'].get()),pan=float(r['pan'].get()),mute=bool(r['mute'].get()),sample_rate=o.sample_rate))
        self.config_data.save(CONFIG_PATH)

    def show_command(self):
        self._save()
        try: text=shell_preview(build_ffmpeg_command(self.config_data,'stream'),self.config_data.output.stream_key)
        except PipelineError as e: text=f'Cannot build stream command yet:\n{e}'
        self.cmd.delete('1.0','end'); self.cmd.insert('1.0',text)

    def start_stream(self): self._start('stream')
    def start_recording(self): self._start('record')

    def _start(self,mode):
        if self.process and self.process.poll() is None: messagebox.showwarning('BloomStream','An output is already running.'); return
        self._save()
        try: cmd=build_ffmpeg_command(self.config_data,mode)
        except PipelineError as e: messagebox.showerror('BloomStream',str(e)); return
        self.cmd.delete('1.0','end'); self.cmd.insert('1.0',shell_preview(cmd,self.config_data.output.stream_key)+'\n\n')
        try: self.process=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,bufsize=1)
        except FileNotFoundError: messagebox.showerror('BloomStream','ffmpeg not found. Run ./install.sh'); return
        self.stop_btn.configure(state='normal'); self.status.set('LIVE' if mode=='stream' else 'RECORDING'); threading.Thread(target=self._watch,daemon=True).start()

    def _watch(self):
        p=self.process
        if p and p.stderr:
            for line in p.stderr: self.log_queue.put(line)
        if p: self.log_queue.put(f'\n[FFmpeg exited with code {p.wait()}]\n')
        self.after(0,self._done)

    def _done(self): self.stop_btn.configure(state='disabled'); self.status.set('Stopped')

    def stop_output(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired: self.process.kill()
        self.status.set('Stopped'); self.stop_btn.configure(state='disabled')

    def _drain(self):
        try:
            while True: self.cmd.insert('end',self.log_queue.get_nowait()); self.cmd.see('end')
        except queue.Empty: pass
        self.after(100,self._drain)

    def run_diag(self): self.diagtext.delete('1.0','end'); self.diagtext.insert('1.0',diagnostics())

def main():
    app=BloomStreamApp(); app.protocol('WM_DELETE_WINDOW',lambda:(app.stop_output(),app.destroy())); app.mainloop()
