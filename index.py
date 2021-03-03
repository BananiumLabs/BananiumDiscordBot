import os
import sys
import asyncio

import discord
import youtube_dl

from discord.ext import commands

from google.cloud import texttospeech as tts
from google.oauth2 import service_account
from os import path

import json

with open("discord_token.json", "r") as read_file:
    discord_credentials = json.load(read_file)['token']

credentials = service_account.Credentials.from_service_account_file('musty-the-mustang-9fc08f525930.json')

# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_message = lambda: ''


# ffmpegPath = "C:/binaries/ffmpeg.exe"
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0' # bind to ipv4 since ipv6 addresses cause issues sometimes
    # 'cookies': 'cookies.txt.json',
    # 'force_generic_extractor': True
}

ffmpeg_options = {
    'options': '-vn'
    # 'executable': ffmpegPath
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

timer_set = False

voice_type = "en-AU-Wavenet-D"

timer = 0

time_notifs = [60 * 10, 60 * 5]

time_msg = None

colors = {'work': 0xffd52b, 'break': 0x49b800, 'general': 0x33ccff, 'error': 0xff6f5c}


async def send_msg(ctx, title: str, message: str, color='general'):
    embed = discord.Embed(color=colors[color])
    embed.add_field(name=title, value=message, inline=False)
    await ctx.send(embed=embed)

async def send_msg_inline(ctx, title: str, message: str, color='general'):
    embed = discord.Embed(color=colors[color])
    embed.add_field(name=title, value=message, inline=True)
    await ctx.send(embed=embed)

def make_time_embed(type):
    embed = discord.Embed(color=colors[type])
    embed.add_field(name="⌛ " + type.capitalize() + " Time Remaining:", value=get_formatted_time(timer))
    return embed

def get_formatted_time(time: int):
    minutes = timer // 60
    seconds = timer % 60 if timer % 60 > 9 else '0' + str(timer % 60)
    return str(minutes) + ":" + str(seconds)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

class TTSSource():
    def __init__(self, voice_name, text):
        self.done = False
        language_code = '-'.join(voice_name.split('-')[:2])
        
        encryptedText = self.encryptDecrypt(text)
        
        filename = f'audio/{language_code}_{voice_name}_{encryptedText}.wav'
        
        # check if audio already cached
        if path.exists(filename):
            print(filename + " already exists!")
            self.filename = filename
            self.done = True
        else:
            text_input = tts.SynthesisInput(text=text)
            voice_params = tts.VoiceSelectionParams(
                language_code=language_code,
                name=voice_name)
            audio_config = tts.AudioConfig(
                audio_encoding=tts.AudioEncoding.LINEAR16)

            client = tts.TextToSpeechClient(credentials=credentials)
            response = client.synthesize_speech(
                input=text_input,
                voice=voice_params,
                audio_config=audio_config)

            
            with open(filename, 'wb') as out:
                out.write(response.audio_content)
                print(f'Audio content written to "{filename}"')
                self.filename = filename
                self.done = True

    def encryptDecrypt(self, inpString): 
        # Define XOR key 
        # Any character value will work 
        xorKey = 'P'; 
    
        # calculate length of input string 
        length = len(inpString); 
    
        # perform XOR operation of key 
        # with every caracter in string 
        for i in range(length): 
        
            inpString = (inpString[:i] + 
                chr(ord(inpString[i]) ^ ord(xorKey)) +
                        inpString[i + 1:]); 
            print(inpString[i], end = ""); 
        
        return inpString.replace("\0", ""); 

class Bananium(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start_timer(self, t, ctx, type):
        global timer
        print("TIMER:", t)
        if timer == 0:
            timer = int(t)
            while timer > 0:
                if not timer_set:
                    return

                timer -= 1
                if time_msg:
                    try:
                        await time_msg.edit(embed=make_time_embed(type))
                    except:
                        pass
                    

                if timer in time_notifs:
                    self.play_audio(ctx, 'local_mp3/ringtone_cut.mp3')
                    await asyncio.sleep(3)
                    timer -= 3

                    await self.fetch_audio(ctx, str(int((timer+5)//60)) + ' minutes remaining.')

                await asyncio.sleep(1)
        else:
            print("attempted to start timer when timer was already running!")

    async def join_current(self, ctx):
        if ctx.voice_client is None:
            channel = ctx.author.voice.channel
            await channel.connect()
    
    async def fetch_audio(self, ctx, text):
        audioClip = TTSSource(voice_type, text)
        while audioClip.done is False:
            await asyncio.sleep(1)
        self.play_audio(ctx, audioClip.filename)


    def play_audio(self, ctx, audioName):
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(audioName, **ffmpeg_options))
        ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)

    @commands.command()
    async def join(self, ctx, *, channel: discord.VoiceChannel):
        """Joins a voice channel"""

        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)

        await channel.connect()

    @commands.command()
    async def color(self, ctx, roleIn, color):
        """changes color for a role"""
        print("Login as")
        print(self.bot.user)
        print("-------")
        server = ctx.message.guild
        role = discord.utils.get(server.roles, id=roleIn) or discord.utils.get(server.roles, name=roleIn) or discord.utils.get(server.roles, name=roleIn.capitalize())
        color = int(color, 16)
        # print(color)
        if role and str(role.name).lower() in [str(r.name).lower() for r in ctx.author.roles]:
            await role.edit(colour=discord.Colour(color))
            await ctx.send("done :)")
        else:
            await ctx.send("u suck")

    @commands.command()
    async def play(self, ctx, *, query):
        """Plays a file from the local filesystem"""

        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio("local_mp3/" + query + ".mp3", **ffmpeg_options))
        ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)

        await ctx.send('Now playing: {}'.format(query))

    @commands.command()
    async def yt(self, ctx, *, url):
        """Plays from a url (almost anything youtube_dl supports)"""
    
        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=self.bot.loop)
            ctx.voice_client.play(player, after=lambda e: print('Player error: %s' % e) if e else None)

        await ctx.send('Now playing: {}'.format(player.title))

    @commands.command()
    async def stream(self, ctx, *, url):
        """Streams from a url (same as yt, but doesn't predownload)"""

        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            ctx.voice_client.play(player, after=lambda e: print('Player error: %s' % e) if e else None)

        await ctx.send('Now playing: {}'.format(player.title))
        await ctx.send('Note: If stream abruptly stop, try using yt() fallback command to download the full audio prior to playback. This will result in excessive buffering time.')

    @commands.command()
    async def volume(self, ctx, volume: int):
        """Changes the player's volume"""

        if ctx.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")

        ctx.voice_client.source.volume = volume / 100
        await ctx.send("Changed volume to {}%".format(volume))

    @commands.command()
    async def stop(self, ctx):
        """Stops and disconnects the bot from voice"""

        await ctx.voice_client.disconnect()

    @commands.command()
    async def pom(self, ctx, workTime: float, breakTime: float):
        """Initiates Pomodoro Timer"""
        global timer_set
        global voice_type
        global time_msg

        bt_str = str(int(breakTime) if int(breakTime) == breakTime else breakTime)
        wt_str = str(int(workTime) if int(workTime) == workTime else workTime)
        if workTime < 0.2 or breakTime < 0.2:
            await ctx.send("Please enter a time greater than 0.2 minutes.")
            return

        if timer_set:
            await ctx.send("Timer is already active. !cancel to kill.")
            return
        
        timer_set = True

        await send_msg(ctx, 'Timer Set', 'Work Time Set: ' + wt_str + ' minutes.\nBreak Time Set: ' + bt_str + ' minutes.')
        time_msg = await ctx.send(embed=make_time_embed('work'))
        
        await self.join_current(ctx)
        await self.fetch_audio(ctx, "Work time set for " + wt_str + " minutes. Break time set for " + bt_str + " minutes. Starting Now")

        await self.start_timer(workTime * 60, ctx, 'work')

        # start break time
        if not timer_set:
            return

        await self.join_current(ctx)
        await ctx.send("-pause")
        self.play_audio(ctx, 'local_mp3/oth_clip.mp3')
        await asyncio.sleep(28)
        await self.fetch_audio(ctx, bt_str + " minutes break time is starting now!")
        await self.start_timer(max(0.2*60, breakTime*60), ctx, 'break')
        self.play_audio(ctx, 'local_mp3/ringtone_cut.mp3')
        await asyncio.sleep(3)
        await self.fetch_audio(ctx, bt_str + " minutes break time has ended. Get back to work!")
        if time_msg:
                await time_msg.delete()

        # check if keep going
        # await asyncio.sleep(5)
        # audioClip = TTSSource(voice_type, "Want to go for another round of oxford university? Please type yes in bots channel to confirm.")
        # while audioClip.done is False:
        #     await asyncio.sleep(1)
        # source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(audioClip.filename, **ffmpeg_options))
        # ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)

        # isDone = True

        # # check if keep going
        # await asyncio.sleep(10)
        # audioClip = TTSSource(voice_type, "Oxford university session terminated.")
        # while audioClip.done is False:
        #     await asyncio.sleep(1)
        # source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(audioClip.filename, **ffmpeg_options))
        # ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)
        timer_set = False

    @commands.command(pass_context=True)
    async def time(self, ctx):
        """Prints Pomodoro time remaining"""
        global time_msg
        if timer > 0:
            if time_msg:
                await time_msg.delete()
                time_msg = None
            minutes = timer // 60
            seconds = timer % 60 if timer % 60 > 9 else '0' + str(timer % 60)
            time_msg = await ctx.send(embed=make_time_embed('work'))
        else:
            # await ctx.send("No timer active.")
            await send_msg(ctx, "❌", "No Timer Active", color='error')
        await ctx.message.delete()

    @commands.command()
    async def cancel(self, ctx):
        """Cancel Pomodoro Timer"""
        global timer_set

        if timer_set:
            # Ben I know this is super hacky, but im just going to put this here until we have time to get this
            # fixed. >
            await send_msg(ctx, "❌", "Please wait. Restarting script...", color='error')
            os.execl(sys.executable, sys.executable, *sys.argv)
            return

            await send_msg(ctx, "❌", "Timer Killed", color='error')
            timer_set = False
            if time_msg:
                await time_msg.delete()
        else:
            await send_msg(ctx, "❌", "No Timer Active", color='error')

    @commands.command()
    async def voice(self, ctx, voice: str):
        """Set Speech API voice type"""
        global voice_type

        voice_dict = {
            'IN_F': 'en-IN-Wavenet-A',
            'IN_M': 'en-IN-Wavenet-C',
            'US_F': 'en-US-Wavenet-G',
            'US_M': 'en-US-Wavenet-B',
            'GB_F': 'en-GB-Wavenet-A',
            'GB_M': 'en-GB-Wavenet-B',
            'AU_F': 'en-AU-Wavenet-C',
            'AU_M': 'en-AU-Wavenet-B'
        }
        if voice in voice_dict:
            voice_type = voice_dict[voice]
        else:
            voice_type = voice
        await ctx.send("New voice set to: " + voice_type)
        audioClip = TTSSource(voice_type, "New voice set.")
        while not audioClip.done:
            await asyncio.sleep(1)
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(audioClip.filename, **ffmpeg_options))
        ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)

    @commands.command()
    async def voicelist(self, ctx):
        """Lists example Google Speech API voice codes"""
        await send_msg(ctx, 'Voice List', r"""
    
    **AU_M:** Australian Male
    **AU_F:** Australian Female
    **IN_M:** Indian Male
    **IN_F:** Indian Female
    **US_M:** Standard Male
    **US_F:** Standard Female
    **GB_M:** British Male
    **GB_F:** British Female
    
        """)
    
    
    @commands.command()
    
    async def tts(self, ctx, *inStr):
        """TTS on voice channel using Google Natural Speech API"""
        global voice_type
        totalChars = 0
        cleanedStr = ""
        for x in inStr:
            cleanedStr += x.replace("\0", "")
        totalChars = len(cleanedStr)
        if (totalChars < 200):
            audioClip = TTSSource(voice_type, cleanedStr)
            while audioClip.done is False:
                await asyncio.sleep(1)
            source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(audioClip.filename, **ffmpeg_options))
            if ctx.voice_client is None:
                channel = ctx.author.voice.channel
                await channel.connect()
            ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)
        else:
            await ctx.send("Input string for TTS is too long. Please try again with a shorter string.")

    @commands.command()
    async def echo(self, ctx, *inStr):
        """Prints input inline message"""
        await send_msg_inline(ctx, inStr[0], inStr[1], color='general')
         
    @commands.command()
    async def joinForce(self, ctx):
        """Join voice channel and force bypass restrictions."""
        print("joining")
        channel = ctx.author.voice.channel
        await channel.connect()

    @commands.command()
    async def leaveForce(self, ctx):
        """Leave voice channel and force bypass restrictions."""
        await ctx.voice_client.disconnect()

    @commands.command(pass_context=True)
    async def omar(self, ctx, user):
        """Be Omar. Pass in a user as parameter."""
        user = user.replace("<","").replace(">","").replace("@","").replace("!","")
        print(user)
        user_member = await ctx.guild.fetch_member(user)
        if user_member is not None:
            kick_channel = await ctx.guild.create_voice_channel("kicked")
            await user_member.move_to(kick_channel, reason="you have been kicked by Omar.")
            await kick_channel.delete()
        else:
            print("user invalid for omar()")

    @commands.command()
    async def purge(self, ctx, count: int):
        """Purges the past x number of messages."""
        await ctx.channel.purge(limit=count+1)


    @play.before_invoke
    @yt.before_invoke
    @stream.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("You are not connected to a voice channel.")
                raise commands.CommandError("Author not connected to a voice channel.")
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()

bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"),
                   description='BananiumLabs Discord Bot. Script by EnumC and 64bitpanda')

@bot.event
async def on_ready():
    print('Logged in as {0} ({0.id})'.format(bot.user))
    print('------')
    await bot.get_channel(751662103483383838).send('Logged in as {0} ({0.id})'.format(bot.user))
    await bot.change_presence(activity=discord.Activity(name=' for !help | Coded by EnumC and 64bitpanda', type=3)) # Displays 'Watching !help'

bot.add_cog(Bananium(bot))
bot.run(discord_credentials)

# classTest = Bananium(bot)
# classTest.text_to_wav('en-US-Wavenet-A', "This is a test clip.")
