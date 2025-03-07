# Discord Music bot With Youtube integration
This is a simple bot that allows you to play local music, as well as music from youtube.

The things it can do are as follows.

Can play local music, Can play music\clips from Youtube, Has built in customisable sound board.

Discord users can add Youtube clips\music, pause, resume, skip, and see the queue with simple commands  

Admin can control the volume of the bot so you don't have to rely on discord volume. 


# Prerequisites   

1. Python 3.8 or higher

2. discord.py 		-> pip install discord.py

3. PyQt6 		-> pip install PyQt6

4. yt-dlp		-> pip install yt-dlp

5. psutil		-> pip install psutil

6. FFmpeg 		

7. Discord Bot Token  

# FFmpeg install help 
(Windows): Download FFmpeg from ffmpeg.org or a trusted build like gyan.dev (https://www.gyan.dev/ffmpeg/builds/) 
(e.g., ffmpeg-release-essentials.zip).

Extract the ZIP file to a folder (e.g., C:\ffmpeg).

Add the bin folder to your system PATH:
Right-click "This PC" > "Properties" > "Advanced system settings" > "Environment Variables."

Under "System variables," find "Path," click "Edit," and add C:\ffmpeg\bin.

Verify: Open a new terminal and run ffmpeg -version (should show version info).


Installation (Linux/macOS):

Linux: sudo apt install ffmpeg (Ubuntu/Debian) or sudo yum install ffmpeg (CentOS/RHEL).


macOS: brew install ffmpeg (with Homebrew installed).

Verify: ffmpeg -version


# Discord Bot Token 

1. Go to Discord Developer Portal. <- https://discord.com/developers/applications

2. Create a new application, then a bot under "Bot" settings.

3. Enable "Presence Intent," "Server Members Intent," and "Message Content Intent" under "Privileged Gateway Intents."

4. Copy the bot token and replace the TOKEN value in the code: (it will look like this) Line 21 TOKEN = "YOUR_BOT_TOKEN_HERE"


# Discord User Commands 

!play		-> example - !play Electric Callboy - PUMP IT 

!pause		-> will pause what is playing

!resume		-> will resume paused song

!skip     -> will skip to next song

!queue     -> will show what is in the queue

# For the noobs

open CMD or Powershell, navigate to folder where bot is located, and type in 

python .\DiscordBot+YoutubePlayer.py 

Hit Enter\Return
