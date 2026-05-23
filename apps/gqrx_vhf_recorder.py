

APP_VERSION = "v1.0.9"

import tkinter as tk
from tkinter import filedialog, ttk
import socket
import subprocess
import os
import time

GQRX_HOST = 'localhost'
GQRX_PORT = 7356
CHANNEL_FREQ = 156550000  # Hz for Marine VHF Ch11
MODE = 'FM'
PASSBAND = 10000  # 10 kHz for marine VHF





class GQRXRecorderApp:
    def __init__(self, master):
        self.master = master
        master.title('GQRX VHF Ch11 Recorder')
        self.sock = None
        self.recording = False
        self.output_dir = '/home/pi/gqrxRecieved'
        self.filename = ''

        # Tabs
        self.notebook = ttk.Notebook(master)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Record Tab
        self.record_tab = tk.Frame(self.notebook)
        self.notebook.add(self.record_tab, text='Record')

        self.status_label = tk.Label(self.record_tab, text='Status: Initializing...')
        self.status_label.pack(pady=5)

        self.dir_button = tk.Button(self.record_tab, text='Select Output Directory', command=self.select_dir)
        self.dir_button.pack(pady=5)

        self.channel_map = {
            'Ch 06 (156.300 MHz)': 156300000,
            'Ch 10 (156.500 MHz)': 156500000,
            'Ch 11 (156.550 MHz)': 156550000,
            'Ch 12 (156.600 MHz)': 156600000,
            'Ch 13 (156.650 MHz)': 156650000,
            'Ch 14 (156.700 MHz)': 156700000,
            'Ch 16 (156.800 MHz)': 156800000,
            'Ch 22 (157.100 MHz)': 157100000,
            'Ch 67 (156.375 MHz)': 156375000,
            'Ch 70 (156.525 MHz)': 156525000,
            'Ch 72 (156.625 MHz)': 156625000,
        }
        self.selected_channel = tk.StringVar(value='Ch 11 (156.550 MHz)')
        self.channel_dropdown = tk.OptionMenu(self.record_tab, self.selected_channel, *self.channel_map.keys(), command=self.set_channel)
        self.channel_dropdown.pack(pady=5)

        self.playback_active = False
        self.playback_button = tk.Button(self.record_tab, text='Start Playback', command=self.toggle_playback, state=tk.NORMAL)
        self.playback_button.pack(pady=5)

        self.start_button = tk.Button(self.record_tab, text='Start Recording', command=self.start_recording, state=tk.DISABLED)
        self.start_button.pack(pady=5)

        self.stop_button = tk.Button(self.record_tab, text='Stop Recording', command=self.stop_recording, state=tk.DISABLED)
        self.stop_button.pack(pady=5)

        self.close_button = tk.Button(self.record_tab, text='Close', command=self.close_app, bg='#c0392b', fg='white')
        self.close_button.pack(pady=10)

        # Playback Tab
        self.playback_tab = tk.Frame(self.notebook)
        self.notebook.add(self.playback_tab, text='Playback')

        # Loop checkbox
        self.loop_var = tk.BooleanVar(value=False)
        self.loop_checkbox = tk.Checkbutton(self.playback_tab, text='Loop segment', variable=self.loop_var)
        self.loop_checkbox.pack(anchor=tk.W, padx=10, pady=(0, 5))

        # Volume control
        self.volume_var = tk.DoubleVar(value=1.0)
        self.volume_frame = tk.Frame(self.playback_tab)
        self.volume_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        tk.Label(self.volume_frame, text='Volume').pack(side=tk.LEFT)
        self.volume_slider = tk.Scale(self.volume_frame, from_=0.0, to=2.0, orient=tk.HORIZONTAL, resolution=0.01, variable=self.volume_var, length=200)
        self.volume_slider.pack(side=tk.LEFT, padx=10)


        # Load File button
        self.load_file_btn = tk.Button(self.playback_tab, text='Load File', command=self.load_playback_file)
        self.load_file_btn.pack(side=tk.LEFT, padx=10, pady=5)

        # Playback controls
        self.play_btn = tk.Button(self.playback_tab, text='Play Segment', command=self.play_segment)
        self.play_btn.pack(side=tk.LEFT, padx=10, pady=5)
        self.stop_btn = tk.Button(self.playback_tab, text='Stop', command=self.stop_segment)
        self.stop_btn.pack(side=tk.LEFT, padx=10, pady=5)

        # Label to show loaded file name
        self.playback_file_label = tk.Label(self.playback_tab, text='No file loaded')
        self.playback_file_label.pack(fill=tk.X, padx=10, pady=(0, 5))

        self.version_label = tk.Label(master, text=f"Version: {APP_VERSION}", font=("Arial", 8), fg="#888", anchor="e")
        self.version_label.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 2), padx=4)

        self.master.protocol("WM_DELETE_WINDOW", self.close_app)
        self.master.after(100, self.initialize_gqrx)

    def close_app(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.master.destroy()

    def stop_recording(self):
        if self.recording:
            self.send_cmd('U RECORD 0')
            self.status_label.config(text='Recording stopped')
            self.recording = False
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            self.playback_button.config(text='Start Playback')
            self.playback_active = False

    def __init__(self, master):
        self.master = master
        master.title('GQRX VHF Ch11 Recorder')
        self.sock = None
        self.recording = False
        self.output_dir = '/home/pi/gqrxRecieved'
        self.filename = ''

        # Tabs
        self.notebook = ttk.Notebook(master)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Record Tab
        self.record_tab = tk.Frame(self.notebook)
        self.notebook.add(self.record_tab, text='Record')

        self.status_label = tk.Label(self.record_tab, text='Status: Initializing...')
        self.status_label.pack(pady=5)

        self.dir_button = tk.Button(self.record_tab, text='Select Output Directory', command=self.select_dir)
        self.dir_button.pack(pady=5)

        self.channel_map = {
            'Ch 06 (156.300 MHz)': 156300000,
            'Ch 10 (156.500 MHz)': 156500000,
            'Ch 11 (156.550 MHz)': 156550000,
            'Ch 12 (156.600 MHz)': 156600000,
            'Ch 13 (156.650 MHz)': 156650000,
            'Ch 14 (156.700 MHz)': 156700000,
            'Ch 16 (156.800 MHz)': 156800000,
            'Ch 22 (157.100 MHz)': 157100000,
            'Ch 67 (156.375 MHz)': 156375000,
            'Ch 70 (156.525 MHz)': 156525000,
            'Ch 72 (156.625 MHz)': 156625000,
        }
        self.selected_channel = tk.StringVar(value='Ch 11 (156.550 MHz)')
        self.channel_dropdown = tk.OptionMenu(self.record_tab, self.selected_channel, *self.channel_map.keys(), command=self.set_channel)
        self.channel_dropdown.pack(pady=5)

        self.playback_active = False
        self.playback_button = tk.Button(self.record_tab, text='Start Playback', command=self.toggle_playback, state=tk.NORMAL)
        self.playback_button.pack(pady=5)

        self.start_button = tk.Button(self.record_tab, text='Start Recording', command=self.start_recording, state=tk.DISABLED)
        self.start_button.pack(pady=5)

        self.stop_button = tk.Button(self.record_tab, text='Stop Recording', command=self.stop_recording, state=tk.DISABLED)
        self.stop_button.pack(pady=5)

        self.close_button = tk.Button(self.record_tab, text='Close', command=self.close_app, bg='#c0392b', fg='white')
        self.close_button.pack(pady=10)


        # Playback Tab
        self.playback_tab = tk.Frame(self.notebook)
        self.notebook.add(self.playback_tab, text='Playback')

        # Load File button
        self.load_file_btn = tk.Button(self.playback_tab, text='Load File', command=self.load_playback_file)
        self.load_file_btn.pack(fill=tk.X, padx=10, pady=(10, 2))

        # Display loaded file name
        self.playback_file_label = tk.Label(self.playback_tab, text='No file loaded')
        self.playback_file_label.pack(fill=tk.X, padx=10, pady=(0, 5))

        # Timeline slider for segment selection
        self.timeline_frame = tk.Frame(self.playback_tab)
        self.timeline_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        tk.Label(self.timeline_frame, text='Segment:').pack(side=tk.LEFT)
        self.timeline_start = tk.DoubleVar(value=0.0)
        self.timeline_end = tk.DoubleVar(value=1.0)
        self.timeline_slider = tk.Scale(self.timeline_frame, from_=0.0, to=1.0, orient=tk.HORIZONTAL, resolution=0.01, variable=self.timeline_start, label='Start', length=120, command=self.update_segment_labels)
        self.timeline_slider.pack(side=tk.LEFT, padx=5)
        self.timeline_slider_end = tk.Scale(self.timeline_frame, from_=0.0, to=1.0, orient=tk.HORIZONTAL, resolution=0.01, variable=self.timeline_end, label='End', length=120, command=self.update_segment_labels)
        self.timeline_slider_end.pack(side=tk.LEFT, padx=5)

        # Segment time labels
        self.segment_start_label = tk.Label(self.playback_tab, text='Start: 0.0s')
        self.segment_start_label.pack(anchor=tk.W, padx=10)
        self.segment_end_label = tk.Label(self.playback_tab, text='End: 0.0s')
        self.segment_end_label.pack(anchor=tk.W, padx=10)

        # Loop checkbox
        self.loop_var = tk.BooleanVar(value=False)
        self.loop_checkbox = tk.Checkbutton(self.playback_tab, text='Loop segment', variable=self.loop_var)
        self.loop_checkbox.pack(anchor=tk.W, padx=10, pady=(0, 5))

        # Volume control
        self.volume_var = tk.DoubleVar(value=1.0)
        self.volume_frame = tk.Frame(self.playback_tab)
        self.volume_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        tk.Label(self.volume_frame, text='Volume').pack(side=tk.LEFT)
        self.volume_slider = tk.Scale(self.volume_frame, from_=0.0, to=2.0, orient=tk.HORIZONTAL, resolution=0.01, variable=self.volume_var, length=200)
        self.volume_slider.pack(side=tk.LEFT, padx=10)

        # Playback controls
        self.play_btn = tk.Button(self.playback_tab, text='Play Segment', command=self.play_segment)
        self.play_btn.pack(side=tk.LEFT, padx=10, pady=5)
        self.stop_btn = tk.Button(self.playback_tab, text='Stop', command=self.stop_segment)
        self.stop_btn.pack(side=tk.LEFT, padx=10, pady=5)

        self.version_label = tk.Label(master, text=f"Version: {APP_VERSION}", font=("Arial", 8), fg="#888", anchor="e")
        self.version_label.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 2), padx=4)

        self.master.protocol("WM_DELETE_WINDOW", self.close_app)
        self.master.after(100, self.initialize_gqrx)

    def close_app(self):
        """Gracefully stop recording, close sockets, and exit."""
        try:
            self.stop_recording()
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.master.destroy()

    def initialize_gqrx(self):
        """Attempt to connect to GQRX on startup."""
        if self.is_gqrx_running():
            self.connect_gqrx()
            if self.sock:
                self.status_label.config(text='Status: Connected to GQRX')
                self.set_channel(self.selected_channel.get())
            else:
                self.status_label.config(text='Status: GQRX running but connection failed')
        else:
            self.status_label.config(text='Status: GQRX is not running')

    def load_playback_file(self):
        filetypes = [('WAV files', '*.wav'), ('All files', '*.*')]
        filename = filedialog.askopenfilename(initialdir=self.output_dir, filetypes=filetypes)
        if filename:
            self.filename = filename
            self.playback_file_label.config(text=os.path.basename(filename))
            self.update_segment_labels()

    def update_segment_labels(self, *args):
        # Dummy duration for now; replace with actual duration if available
        duration = 60.0
        try:
            import wave
            if self.filename:
                with wave.open(self.filename, 'rb') as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    duration = frames / float(rate)
        except Exception:
            pass
        start_time = self.timeline_start.get() * duration
        end_time = self.timeline_end.get() * duration
        self.segment_start_label.config(text=f'Start: {start_time:.2f}s')
        self.segment_end_label.config(text=f'End: {end_time:.2f}s')
    def timeline_draw(self): pass
    def get_loaded_file_duration(self): return 0
    def timeline_click(self, event): pass
    def timeline_drag(self, event): pass
    def timeline_release(self, event): pass

    def play_segment(self):
        # Play the selected segment of the loaded WAV file, with optional looping
        if not hasattr(self, 'filename') or not self.filename:
            self.playback_file_label.config(text='No file loaded')
            return
        try:
            import wave
            import simpleaudio as sa
            import numpy as np
        except ImportError:
            self.playback_file_label.config(text='simpleaudio or numpy not installed')
            return

        def play_once():
            try:
                wf = wave.open(self.filename, 'rb')
                n_frames = wf.getnframes()
                framerate = wf.getframerate()
                nchannels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                start_frame = int(self.timeline_start.get() * n_frames)
                end_frame = int(self.timeline_end.get() * n_frames)
                if end_frame <= start_frame:
                    end_frame = start_frame + 1
                wf.setpos(start_frame)
                frames = wf.readframes(end_frame - start_frame)
                # Adjust volume
                if sampwidth == 2:
                    dtype = np.int16
                elif sampwidth == 1:
                    dtype = np.uint8
                else:
                    dtype = None
                if dtype:
                    audio = np.frombuffer(frames, dtype=dtype)
                    volume = self.volume_var.get()
                    # For unsigned 8-bit, center at 128
                    if dtype == np.uint8:
                        audio = audio.astype(np.int16) - 128
                        audio = np.clip(audio * volume, -128, 127).astype(np.int16) + 128
                        audio = np.clip(audio, 0, 255).astype(np.uint8)
                    else:
                        audio = np.clip(audio * volume, -32768, 32767).astype(np.int16)
                    frames = audio.tobytes()
                play_obj = sa.play_buffer(frames, nchannels, sampwidth, framerate)
                wf.close()
                return play_obj, (end_frame - start_frame) / framerate
            except Exception as e:
                self.playback_file_label.config(text=f'Playback error: {e}')
                return None, 0

        def loop_playback():
            if not getattr(self, '_loop_active', False):
                return
            play_obj, duration = play_once()
            if play_obj:
                self._play_obj = play_obj
                self.master.after(int(duration * 1000), loop_playback)

        # Stop any previous playback
        self.stop_segment()

        if self.loop_var.get():
            self._loop_active = True
            loop_playback()
        else:
            self._loop_active = False
            play_obj, _ = play_once()
            self._play_obj = play_obj

    def stop_segment(self):
        # Stop playback if active
        self._loop_active = False
        if hasattr(self, '_play_obj') and self._play_obj:
            try:
                self._play_obj.stop()
            except Exception:
                pass
            self._play_obj = None
        self.status_label.config(text="Playback stopped")

    def get_playback_state(self):
        # Query GQRX for DSP state: 'u dsp' returns 1 if playback is active, 0 otherwise
        try:
            resp = self.send_cmd('u dsp')
            return resp.strip().startswith('1')
        except Exception:
            return False

    def set_channel(self, channel_name):
        freq = self.channel_map.get(channel_name)
        if freq and self.sock:
            self.send_cmd(f'F {freq}')
            self.send_cmd(f'M FM 10000')  # Always set to narrow FM with 10kHz filter
            self.status_label.config(text=f'Set to {channel_name} (FM, 10kHz)')
            self.playback_button.config(state=tk.NORMAL)
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)

    def toggle_playback(self):
        if not self.sock:
            return
        if not self.playback_active:
            self.send_cmd('A 1')  # Activate play
            self.send_cmd('U dsp 1')
            self.status_label.config(text='Playback started. You can now record.')
            self.playback_button.config(text='Stop Playback')
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.playback_active = True
        else:
            self.send_cmd('U dsp 0')
            self.send_cmd('A 0')  # Deactivate play
            self.status_label.config(text='Playback stopped.')
            self.playback_button.config(text='Start Playback')
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            self.playback_active = False

    def is_gqrx_running(self):
        try:
            output = subprocess.check_output(['pgrep', 'gqrx'])
            return bool(output.strip())
        except Exception:
            return False

    def connect_gqrx(self):
        try:
            self.sock = socket.create_connection((GQRX_HOST, GQRX_PORT), timeout=2)
        except Exception:
            self.sock = None

    def send_cmd(self, cmd):
        if not self.sock:
            self.connect_gqrx()
        if self.sock:
            try:
                self.sock.sendall((cmd + '\n').encode())
                return self.sock.recv(1024).decode(errors='ignore')
            except Exception:
                self.sock = None
        return ''

    def select_dir(self):
        directory = filedialog.askdirectory(initialdir=self.output_dir)
        if directory:
            self.output_dir = directory

    def start_recording(self):
        if not self.recording:
            self.send_cmd('U RECORD 1')
            self.status_label.config(text='Recording started')
            self.recording = True
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)



if __name__ == "__main__":
    root = tk.Tk()
    app = GQRXRecorderApp(root)
    root.mainloop()
