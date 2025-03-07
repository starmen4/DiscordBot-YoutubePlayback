import os
import discord
import asyncio
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,QPushButton, QListWidget, QFileDialog, QListWidgetItem, QMessageBox,QSlider, QLabel
from PyQt6.QtCore import QThread, pyqtSignal, Qt, pyqtSlot
from PyQt6.QtGui import QColor
from discord.ext import commands
from queue import Queue
import time
import shutil
import logging
import psutil
from yt_dlp import YoutubeDL
from collections import OrderedDict

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Bot setup
TOKEN = "YOUR_BOT_TOKEN_HERE"
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True
intents.members = True
intents.presences = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Constants
QUICK_PLAY_FILE = "quick_play_files.txt"
TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp")
MAX_CACHE_SIZE = 5

# Global variables
vc = None
file_queue = Queue(maxsize=50)
paused_file = None
paused_position = 0
current_file = None
start_time = None
music_volume = 1.0
quick_sound_volume = 1.0
vc_lock = asyncio.Lock()
is_playing_quick_sound = False
youtube_cache = OrderedDict()

# Ensure temp directory exists
os.makedirs(TEMP_DIR, exist_ok=True)

# Utility Functions
# Loads quick play sound mappings from a file and returns them as a dictionary.
def load_quick_play_files():
    quick_play_files = {}
    if os.path.exists(QUICK_PLAY_FILE):
        with open(QUICK_PLAY_FILE, "r", encoding='utf-8') as f:
            for line in f:
                try:
                    name, path = line.strip().split(":", 1)
                    quick_play_files[name] = path
                except ValueError:
                    logger.warning(f"Invalid line in {QUICK_PLAY_FILE}: {line}")
    return quick_play_files

# Saves a quick play sound mapping (name: path) to the quick play file.
def save_quick_play_file(name, file_path):
    quick_play_files = load_quick_play_files()
    quick_play_files[name] = file_path
    with open(QUICK_PLAY_FILE, "w", encoding='utf-8') as f:
        f.writelines(f"{n}:{p}\n" for n, p in quick_play_files.items())

# Downloads a song from YouTube, caches it, and returns the file path and title.
def download_song(song_title):
    cache_key = song_title.lower()
    if cache_key in youtube_cache and os.path.exists(youtube_cache[cache_key]):
        logger.info(f"Cache hit for {song_title}")
        youtube_cache.move_to_end(cache_key)
        return youtube_cache[cache_key], song_title

    try:
        for file in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, file)
            if file_path not in youtube_cache.values() and file.endswith('.mp3'):
                try:
                    os.remove(file_path)
                except OSError as e:
                    logger.warning(f"Failed to remove {file_path}: {e}")

        ydl_search_opts = {
            'format': 'bestaudio',
            'noplaylist': True,
            'quiet': True,
            'default_search': 'ytsearch',
        }
        with YoutubeDL(ydl_search_opts) as ydl:
            info = ydl.extract_info(song_title, download=False)
            if not info or 'entries' not in info or not info['entries']:
                return None, "No video found."
            video = info['entries'][0]
            video_id, title = video['id'], video['title']
            base_url = f'https://www.youtube.com/watch?v={video_id}'

        safe_title = "".join(c if c.isalnum() or c in " -_()" else "_" for c in title)
        file_path = os.path.join(TEMP_DIR, f"{safe_title}")
        ydl_download_opts = {
            'format': 'bestaudio',
            'outtmpl': file_path,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
            'quiet': True,
        }
        with YoutubeDL(ydl_download_opts) as ydl:
            ydl.download([base_url])

        time.sleep(0.2)
        expected_file = f"{file_path}.mp3"
        if os.path.exists(expected_file):
            if len(youtube_cache) >= MAX_CACHE_SIZE:
                oldest_key = next(iter(youtube_cache))
                try:
                    os.remove(youtube_cache[oldest_key])
                except OSError as e:
                    logger.warning(f"Failed to remove cached file {youtube_cache[oldest_key]}: {e}")
                del youtube_cache[oldest_key]
            youtube_cache[cache_key] = expected_file
            return expected_file, title

        mp3_files = [f for f in os.listdir(TEMP_DIR) if f.endswith('.mp3') and safe_title in f]
        if mp3_files:
            found_file = os.path.join(TEMP_DIR, mp3_files[0])
            youtube_cache[cache_key] = found_file
            return found_file, title

        logger.error(f"Download failed: No matching .mp3 found for {song_title} in {TEMP_DIR}")
        return None, "Failed to download."
    except Exception as e:
        logger.error(f"Download error for {song_title}: {e}")
        return None, f"Error downloading: {e}"

# Terminates all running FFmpeg processes to release file handles.
def terminate_ffmpeg_processes():
    for proc in psutil.process_iter(['pid', 'name']):
        if 'ffmpeg' in proc.info['name'].lower():
            try:
                proc.kill()
                logger.info(f"Terminated FFmpeg process with PID {proc.info['pid']}")
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                logger.warning(f"Failed to terminate FFmpeg process {proc.info['pid']}: {e}")

# Bot Thread
class BotThread(QThread):
    ready_signal = pyqtSignal(bool)

    # Initializes the BotThread with an optional parent.
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None

    # Runs the bot's asyncio event loop.
    def run(self):
        asyncio.run(self.start_bot())

    # Starts the Discord bot and defines its commands and events.
    async def start_bot(self):
        # Handles the bot's on_ready event, logging login and enabling the connect button.
        @bot.event
        async def on_ready():
            logger.info(f"Bot logged in as {bot.user}")
            logger.info(f"Connected to {len(bot.guilds)} guild(s)" if bot.guilds else "No guilds connected!")
            self.ready_signal.emit(True)

        # Plays a song by downloading it and adding it to the queue or playing immediately.
        @bot.command(name="play")
        async def play(ctx, *, song_title):
            global vc, file_queue
            try:
                file_path, message = await asyncio.get_running_loop().run_in_executor(None, download_song, song_title)
                if not file_path:
                    await ctx.send(message)
                    return

                await ctx.send(f"Added to queue: {message}")
                if not vc or not vc.is_connected():
                    voice_channel = discord.utils.get(ctx.guild.voice_channels, name="tutturu~")
                    if not voice_channel:
                        await ctx.send("Voice channel 'tutturu~' not found!")
                        return
                    vc = await voice_channel.connect()

                async with vc_lock:
                    if vc.is_playing():
                        file_queue.put(file_path)
                    else:
                        global current_file, start_time
                        current_file = file_path
                        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(file_path), volume=music_volume)
                        vc.play(source, after=self._play_next_callback)
                        start_time = time.time()
                        logger.info(f"Started playing {current_file} at {start_time}")
                    self.main_window.update_queue_display()
            except Exception as e:
                logger.error(f"Play error: {e}")
                await ctx.send(f"Error: {e}")

        # Pauses the currently playing song.
        @bot.command(name="pause")
        async def pause(ctx):
            global paused_file, paused_position, start_time
            async with vc_lock:
                if vc and vc.is_playing():
                    paused_file = current_file
                    paused_position = time.time() - start_time if start_time else 0
                    vc.pause()
                    await ctx.send("Paused.")

        # Resumes a paused song.
        @bot.command(name="resume")
        async def resume(ctx):
            async with vc_lock:
                if vc and vc.is_paused():
                    vc.resume()
                    await ctx.send("Resumed.")

        # Stops playback and clears the queue.
        @bot.command(name="stop")
        async def stop(ctx):
            global paused_file, paused_position, current_file, start_time
            async with vc_lock:
                if vc and vc.is_playing():
                    vc.stop()
                file_queue.queue.clear()
                paused_file, paused_position, current_file, start_time = None, 0, None, None
                await ctx.send("Stopped and cleared.")
            self.main_window.update_queue_display()
            self.main_window.update_stop_button_state()

        # Skips the current song and plays the next in the queue.
        @bot.command(name="skip")
        async def skip(ctx):
            async with vc_lock:
                if vc and vc.is_playing():
                    vc.stop()
                    await ctx.send("Skipped.")

        # Displays the current song queue.
        @bot.command(name="queue")
        async def queue(ctx):
            if file_queue.empty():
                await ctx.send("Queue is empty.")
            else:
                queue_list = list(file_queue.queue)
                await ctx.send("Current queue:\n" + "\n".join(f"{i+1}. {os.path.basename(item)}" for i, item in enumerate(queue_list)))

        await bot.start(TOKEN)

    # Callback function to play the next song after the current one finishes.
    def _play_next_callback(self, error):
        if error:
            logger.error(f"Playback error: {error}")
        asyncio.run_coroutine_threadsafe(self.main_window.play_next(), bot.loop)

# Main GUI Window
class MainWindow(QMainWindow):
    stop_button_signal = pyqtSignal(bool)

    # Initializes the main GUI window with the bot thread.
    def __init__(self, bot_thread):
        super().__init__()
        self.setWindowTitle("Discord Music Player")
        self.setGeometry(100, 100, 600, 400)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        layout = QVBoxLayout(self.central_widget)

        connection_layout = QHBoxLayout()
        self.connect_button = QPushButton("Connect", clicked=self.connect_to_voice, enabled=False)
        self.disconnect_button = QPushButton("Disconnect", clicked=self.disconnect_from_voice, enabled=False)
        connection_layout.addWidget(self.connect_button)
        connection_layout.addWidget(self.disconnect_button)
        layout.addLayout(connection_layout)

        playback_layout = QHBoxLayout()
        self.pause_button = QPushButton("Pause", clicked=lambda: asyncio.run_coroutine_threadsafe(self.pause_music(), bot.loop))
        self.play_button = QPushButton("Play", clicked=lambda: asyncio.run_coroutine_threadsafe(self.resume_music(), bot.loop))
        self.stop_button = QPushButton("Stop", clicked=lambda: asyncio.run_coroutine_threadsafe(self.stop_music(), bot.loop), enabled=False)
        self.skip_button = QPushButton("Skip", clicked=lambda: asyncio.run_coroutine_threadsafe(self.skip_to_next(), bot.loop))
        playback_layout.addWidget(self.pause_button)
        playback_layout.addWidget(self.play_button)
        playback_layout.addWidget(self.stop_button)
        playback_layout.addWidget(self.skip_button)
        layout.addLayout(playback_layout)

        volume_layout = QHBoxLayout()
        self.music_volume_slider = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=100, value=100)
        self.music_volume_slider.valueChanged.connect(self.update_music_volume)
        volume_layout.addWidget(QLabel("Music Volume"))
        volume_layout.addWidget(self.music_volume_slider)
        layout.addLayout(volume_layout)

        quick_volume_layout = QHBoxLayout()
        self.quick_sound_volume_slider = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=100, value=100)
        self.quick_sound_volume_slider.valueChanged.connect(self.update_quick_sound_volume)
        quick_volume_layout.addWidget(QLabel("Quick Sound Volume"))
        quick_volume_layout.addWidget(self.quick_sound_volume_slider)
        layout.addLayout(quick_volume_layout)

        self.pick_file_button = QPushButton("Pick File", clicked=self.pick_file)
        layout.addWidget(self.pick_file_button)
        self.queue_list = QListWidget()
        layout.addWidget(self.queue_list)

        quick_sound_layout = QVBoxLayout()
        self.quick_buttons = {i: QPushButton(f"Quick Sound {i}", clicked=lambda _, i=i: self.play_quick_sound(i)) for i in range(1, 13)}
        for button in self.quick_buttons.values():
            quick_sound_layout.addWidget(button)
        layout.addLayout(quick_sound_layout)

        bot_thread.ready_signal.connect(self.on_bot_ready)
        self.stop_button_signal.connect(self.stop_button.setEnabled)

        quick_play_files = load_quick_play_files()
        for i in range(1, 13):
            if f"Quick Sound {i}" in quick_play_files:
                self.quick_buttons[i].setText(os.path.basename(quick_play_files[f"Quick Sound {i}"]))

    # Handles the bot ready signal, enabling the connect button.
    def on_bot_ready(self, ready):
        if ready:
            self.connect_button.setEnabled(True)
            logger.info("Bot ready, connect button enabled.")

    # Asynchronously connects the bot to the 'tutturu~' voice channel.
    async def connect_to_voice_async(self):
        global vc
        if not bot.guilds:
            logger.error("No guilds found!")
            return
        voice_channel = discord.utils.get(bot.guilds[0].voice_channels, name="tutturu~")
        if voice_channel:
            try:
                vc = await voice_channel.connect()
                self.disconnect_button.setEnabled(True)
                self.connect_button.setEnabled(False)
                logger.info("Connected to voice channel.")
            except discord.errors.ClientException as e:
                logger.error(f"Connection error: {e}")
        else:
            logger.error("Voice channel 'tutturu~' not found!")

    # Initiates an asynchronous voice connection from the GUI.
    def connect_to_voice(self):
        asyncio.run_coroutine_threadsafe(self.connect_to_voice_async(), bot.loop)

    # Disconnects the bot from the voice channel and triggers cleanup.
    def disconnect_from_voice(self):
        global vc
        if vc:
            asyncio.run_coroutine_threadsafe(self.disconnect_and_cleanup(), bot.loop)
            self.disconnect_button.setEnabled(False)
            self.connect_button.setEnabled(True)
            logger.info("Disconnected from voice channel.")

    # Asynchronously disconnects from voice and cleans up temporary files.
    async def disconnect_and_cleanup(self):
        global vc
        if vc:
            if vc.is_playing() or vc.is_paused():
                vc.stop()
            await vc.disconnect()
            await asyncio.sleep(1.5)
            terminate_ffmpeg_processes()
            if os.path.exists(TEMP_DIR):
                logger.info("Starting temp folder cleanup...")
                for attempt in range(3):
                    try:
                        shutil.rmtree(TEMP_DIR, ignore_errors=False)
                        logger.info("Temp folder cleared successfully.")
                        break
                    except Exception as e:
                        logger.warning(f"Cleanup attempt {attempt + 1} failed: {e}")
                        if attempt < 2:
                            await asyncio.sleep(0.5)
                        else:
                            logger.error(f"Failed to clear temp folder after retries: {e}")
                os.makedirs(TEMP_DIR, exist_ok=True)
            youtube_cache.clear()
            logger.info("Cleanup complete.")
            vc = None

    # Pauses the currently playing music.
    async def pause_music(self):
        async with vc_lock:
            if vc and vc.is_playing():
                vc.pause()

    # Resumes paused music.
    async def resume_music(self):
        async with vc_lock:
            if vc and vc.is_paused():
                vc.resume()

    # Stops music playback and clears the queue.
    async def stop_music(self):
        global paused_file, paused_position, current_file, start_time
        async with vc_lock:
            if vc and vc.is_playing():
                vc.stop()
            file_queue.queue.clear()
            paused_file, paused_position, current_file, start_time = None, 0, None, None
        self.update_stop_button_state()
        self.update_queue_display()

    # Skips to the next song in the queue.
    async def skip_to_next(self):
        async with vc_lock:
            if vc and vc.is_playing():
                vc.stop()
        self.update_stop_button_state()
        self.update_queue_display()

    # Opens a file dialog to pick an MP3 file and adds it to the queue.
    def pick_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "MP3 files (*.mp3);;All Files (*)")
        if file_path:
            file_queue.put(file_path)
            self.update_queue_display()
            self.update_stop_button_state()
            if not vc or not vc.is_playing():
                asyncio.run_coroutine_threadsafe(self.play_next(), bot.loop)

    # Updates the GUI queue display with current queue items.
    @pyqtSlot()
    def update_queue_display(self):
        self.queue_list.clear()
        queue_items = list(file_queue.queue)
        for i, item in enumerate(queue_items):
            item_display = QListWidgetItem(f"{i+1}: {os.path.basename(item)}")
            item_display.setForeground(QColor("green") if i == 0 and vc and vc.is_playing() else QColor("orange") if i == 1 else QColor("black"))
            self.queue_list.addItem(item_display)

    # Updates the stop button's enabled state based on playback and queue status.
    @pyqtSlot()
    def update_stop_button_state(self):
        self.stop_button_signal.emit(vc and (vc.is_playing() or not file_queue.empty()))

    # Assigns a sound file to a quick sound button.
    def assign_sound(self, button_index):
        button = self.quick_buttons[button_index]
        file_path, _ = QFileDialog.getOpenFileName(self, f"Select Sound for {button.text()}", "", "MP3 files (*.mp3);;All Files (*)")
        if file_path:
            button.setText(os.path.basename(file_path))
            save_quick_play_file(f"Quick Sound {button_index}", file_path)

    # Plays a quick sound, pausing current music if playing.
    async def play_quick_sound_coroutine(self, sound_file):
        global quick_sound_volume, is_playing_quick_sound, paused_file, paused_position, start_time
        async with vc_lock:
            if not vc or not vc.is_connected():
                logger.warning("Cannot play quick sound: Bot is not connected to a voice channel.")
                return
            try:
                if vc.is_playing() and current_file:
                    paused_file = current_file
                    paused_position = time.time() - start_time if start_time else 0
                    logger.info(f"Paused at {paused_position}")
                    vc.pause()
                    await asyncio.sleep(0.1)

                is_playing_quick_sound = True
                source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(sound_file), volume=quick_sound_volume)
                vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.resume_music_after_quick_sound(e), bot.loop))
            except Exception as e:
                logger.error(f"Quick sound error: {e}")
                is_playing_quick_sound = False

    # Resumes paused music after a quick sound finishes.
    async def resume_music_after_quick_sound(self, error):
        global is_playing_quick_sound, paused_file, paused_position, start_time, music_volume
        async with vc_lock:
            try:
                is_playing_quick_sound = False
                if error:
                    logger.error(f"Quick sound playback error: {error}")
                if paused_file and os.path.exists(paused_file):
                    if not vc:
                        await self.connect_to_voice_async()
                    while vc.is_playing():
                        await asyncio.sleep(0.05)
                    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(paused_file, before_options=f"-ss {paused_position}"), volume=music_volume)
                    vc.play(source, after=self.after_playing)
                    start_time = time.time() - paused_position
                    logger.info(f"Resumed at {paused_position}")
                else:
                    logger.warning(f"No paused file: {paused_file}")
            except Exception as e:
                logger.error(f"Resume error: {e}")
            finally:
                paused_file, paused_position = None, 0

    # Initiates playing a quick sound or prompts for assignment if none exists.
    def play_quick_sound(self, button_index):
        sound_file = load_quick_play_files().get(f"Quick Sound {button_index}")
        if sound_file:
            asyncio.run_coroutine_threadsafe(self.play_quick_sound_coroutine(sound_file), bot.loop)
        else:
            self.prompt_assign_sound(button_index)

    # Prompts the user to assign a sound to a quick sound button.
    def prompt_assign_sound(self, button_index):
        button = self.quick_buttons[button_index]
        if QMessageBox.question(self, "No Sound", f"No sound for {button.text()}. Assign now?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.assign_sound(button_index)

    # Plays the next song in the queue if available.
    async def play_next(self):
        global current_file, start_time, music_volume
        async with vc_lock:
            if vc and not file_queue.empty():
                current_file = file_queue.get()
                if os.path.exists(current_file):
                    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(current_file), volume=music_volume)
                    if not vc.is_playing():
                        vc.play(source, after=self.after_playing)
                        start_time = time.time()
                        logger.info(f"Started playing {current_file} at {start_time}")
                else:
                    logger.error(f"File missing: {current_file}")
            else:
                logger.info("Queue empty.")
                start_time = None
        self.update_stop_button_state()
        self.update_queue_display()

    # Callback function to handle the end of playback and trigger the next song.
    def after_playing(self, error):
        if error:
            logger.error(f"Playback error: {error}")
        if not is_playing_quick_sound:
            asyncio.run_coroutine_threadsafe(self.play_next(), bot.loop)

    # Updates the music volume based on the slider value.
    def update_music_volume(self):
        global music_volume
        music_volume = self.music_volume_slider.value() / 100
        asyncio.run_coroutine_threadsafe(self.set_music_volume(music_volume), bot.loop)

    # Updates the quick sound volume based on the slider value.
    def update_quick_sound_volume(self):
        global quick_sound_volume
        quick_sound_volume = self.quick_sound_volume_slider.value() / 100

    # Sets the music volume asynchronously.
    async def set_music_volume(self, new_volume):
        async with vc_lock:
            if vc and vc.source:
                vc.source.volume = new_volume

    # Handles window close events by cleaning up temporary files.
    def closeEvent(self, event):
        if os.path.exists(TEMP_DIR):
            terminate_ffmpeg_processes()
            shutil.rmtree(TEMP_DIR, ignore_errors=True)
        event.accept()

# Main entry point to initialize and run the application.
def main():
    import sys
    if os.path.exists(TEMP_DIR):
        logger.info("Cleaning up temp folder on startup...")
        terminate_ffmpeg_processes()
        try:
            shutil.rmtree(TEMP_DIR, ignore_errors=False)
            logger.info("Temp folder cleared on startup.")
        except Exception as e:
            logger.error(f"Failed to clear temp folder on startup: {e}")
        os.makedirs(TEMP_DIR, exist_ok=True)

    app = QApplication(sys.argv)
    bot_thread = BotThread()
    main_window = MainWindow(bot_thread)
    bot_thread.main_window = main_window
    bot_thread.start()
    main_window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()