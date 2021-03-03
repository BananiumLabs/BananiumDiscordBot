import os
import sys
import asyncio

import discord
import youtube_dl
import functools
import itertools
import math
import random
from async_timeout import timeout
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


ffmpeg_options = {
    'options': '-vn'
    # 'executable': ffmpegPath
}



timer_set = False

voice_type = "en-AU-Wavenet-D"

timer = 0

time_notifs = [60 * 10, 60 * 5]

time_msg = None

colors = {'work': 0xffd52b, 'break': 0x49b800, 'general': 0x33ccff, 'error': 0xff6f5c}

class VoiceError(Exception):
    pass


class YTDLError(Exception):
    pass

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

    ytdl = youtube_dl.YoutubeDL(ytdl_format_options)
    
    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')
        date = data.get('upload_date')
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        self.duration = self.parse_duration(int(data.get('duration')))
        self.tags = data.get('tags')
        self.url = data.get('webpage_url')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.dislikes = data.get('dislike_count')
        self.stream_url = data.get('url')

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)
        
    @classmethod
    async def from_url(cls, ctx: commands.Context, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data and data['entries'] is not None:
            # take first item from a playlist
            # print(data)
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(ctx, discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

    @classmethod
    async def create_source(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        webpage_url = process_info['webpage_url']
        partial = functools.partial(cls.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            raise YTDLError('Couldn\'t fetch `{}`'.format(webpage_url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('Couldn\'t retrieve any matches for `{}`'.format(webpage_url))

        return cls(ctx, discord.FFmpegPCMAudio(info['url'], **ffmpeg_options), data=info)

    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append('{} days'.format(days))
        if hours > 0:
            duration.append('{} hours'.format(hours))
        if minutes > 0:
            duration.append('{} minutes'.format(minutes))
        if seconds > 0:
            duration.append('{} seconds'.format(seconds))

        return ', '.join(duration)
class Song:
    def __init__(self, source: YTDLSource):
        self.source = source
        self.requester = source.requester

    def create_embed(self):
        embed = (discord.Embed(title='Now playing',
                               description='```css\n{0.source.title}\n```'.format(self),
                               color=discord.Color.blurple())
                 .add_field(name='Duration', value=self.source.duration)
                 .add_field(name='Requested by', value=self.requester.mention)
                 .add_field(name='Uploader', value='[{0.source.uploader}]({0.source.uploader_url})'.format(self))
                 .add_field(name='URL', value='[Click]({0.source.url})'.format(self))
                 .set_thumbnail(url=self.source.thumbnail))

        return embed
class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]

class VoiceState:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self._ctx = ctx

        self.current = None
        self.voice = None
        self.next = asyncio.Event()
        self.songs = SongQueue()

        self._loop = False
        self._volume = 0.5
        self.skip_votes = set()

        self.audio_player = bot.loop.create_task(self.audio_player_task())

    def __del__(self):
        self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value

    @property
    def is_playing(self):
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.next.clear()

            if not self.loop:
                # Try to get the next song within 3 minutes.
                # If no song will be added to the queue in time,
                # the player will disconnect due to performance
                # reasons.
                try:
                    async with timeout(180):  # 3 minutes
                        self.current = await self.songs.get()
                except asyncio.TimeoutError:
                    self.bot.loop.create_task(self.stop())
                    return

            self.current.source.volume = self._volume
            self.voice.play(self.current.source, after=self.play_next_song)
            await self.current.source.channel.send(embed=self.current.create_embed())

            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise VoiceError(str(error))

        self.next.set()

    def skip(self):
        self.skip_votes.clear()

        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect()
            self.voice = None

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
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send('An error occurred: {}'.format(str(error)))

    @commands.command(name='join', invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        """Joins a voice channel."""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='summon')
    @commands.has_permissions(manage_guild=True)
    async def _summon(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """Summons the bot to a voice channel.
        If no channel was specified, it joins your channel.
        """

        if not channel and not ctx.author.voice:
            raise VoiceError('You are neither connected to a voice channel nor specified a channel to join.')

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='leave', aliases=['disconnect'])
    @commands.has_permissions(manage_guild=True)
    async def _leave(self, ctx: commands.Context):
        """Clears the queue and leaves the voice channel."""

        if not ctx.voice_state.voice:
            return await ctx.send('Not connected to any voice channel.')

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name='volume')
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """Sets the volume of the player."""

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        if 0 > volume > 100:
            return await ctx.send('Volume must be between 0 and 100')

        ctx.voice_state.current.source.volume = volume / 100
        await ctx.send('Volume of the player set to {}%'.format(volume))

    @commands.command(name='now', aliases=['current', 'playing'])
    async def _now(self, ctx: commands.Context):
        """Displays the currently playing song."""

        await ctx.send(embed=ctx.voice_state.current.create_embed())

    @commands.command(name='pause')
    @commands.has_permissions(manage_guild=True)
    async def _pause(self, ctx: commands.Context):
        """Pauses the currently playing song."""

        if not ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='resume')
    @commands.has_permissions(manage_guild=True)
    async def _resume(self, ctx: commands.Context):
        """Resumes a currently paused song."""

        if not ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='stop')
    @commands.has_permissions(manage_guild=True)
    async def _stop(self, ctx: commands.Context):
        """Stops playing song and clears the queue."""

        ctx.voice_state.songs.clear()

        if not ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction('⏹')

    @commands.command(name='skip')
    async def _skip(self, ctx: commands.Context):
        """Vote to skip a song. The requester can automatically skip.
        3 skip votes are needed for the song to be skipped.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send('Not playing any music right now...')

        voter = ctx.message.author
        if voter == ctx.voice_state.current.requester:
            await ctx.message.add_reaction('⏭')
            ctx.voice_state.skip()

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.add(voter.id)
            total_votes = len(ctx.voice_state.skip_votes)

            if total_votes >= 1:
                await ctx.message.add_reaction('⏭')
                ctx.voice_state.skip()
            else:
                await ctx.send('Skip vote added, currently at **{}/3**'.format(total_votes))

        else:
            await ctx.send('You have already voted to skip this song.')

    @commands.command(name='queue')
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """Shows the player's queue.
        You can optionally specify the page to show. Each page contains 10 elements.
        """

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [**{1.source.title}**]({1.source.url})\n'.format(i + 1, song)

        embed = (discord.Embed(description='**{} tracks:**\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='Viewing page {}/{}'.format(page, pages)))
        await ctx.send(embed=embed)

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        """Shuffles the queue."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction('✅')

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index: int):
        """Removes a song from the queue at a given index."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction('✅')

    @commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        """Loops the currently playing song.
        Invoke this command again to unloop the song.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await ctx.message.add_reaction('✅')

    @commands.command(name='play')
    async def _play(self, ctx: commands.Context, *, search: str):
        """Plays a song.
        If there are songs in the queue, this will be queued until the
        other songs finished playing.
        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        async with ctx.typing():
            try:
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
            except YTDLError as e:
                await ctx.send('An error occurred while processing this request: {}'.format(str(e)))
            else:
                song = Song(source)

                await ctx.voice_state.songs.put(song)
                await ctx.send('Enqueued {}'.format(str(source)))

    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError('Bot is already in a voice channel.')


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

    # @commands.command()
    # async def join(self, ctx, *, channel: discord.VoiceChannel):
    #     """Joins a voice channel"""

    #     if ctx.voice_client is not None:
    #         return await ctx.voice_client.move_to(channel)

    #     await channel.connect()

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

    # @commands.command()
    # async def local(self, ctx, *, query):
    #     """Plays a file from the local filesystem"""

    #     source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio("local_mp3/" + query + ".mp3", **ffmpeg_options))
    #     ctx.voice_client.play(source, after=lambda e: print('Player error: %s' % e) if e else None)

    #     await ctx.send('Now playing: {}'.format(query))

    # @commands.command()
    # async def download(self, ctx, *, url):
    #     """Plays from a url (almost anything youtube_dl supports)"""
    
    #     async with ctx.typing():
    #         player = await YTDLSource.from_url(url, loop=self.bot.loop)
    #         ctx.voice_client.play(player, after=lambda e: print('Player error: %s' % e) if e else None)

    #     await ctx.send('Now playing: {}'.format(player.title))
    #     await ctx.send('WARN: This command consumes significant disk space. Use play() instead whenever possible!')

    # @commands.command()
    # async def play(self, ctx, *, url):
    #     """Streams from a url (same as yt, but doesn't predownload)"""

    #     async with ctx.typing():
    #         player = await YTDLSource.from_url(ctx, url, loop=self.bot.loop, stream=True)
    #         song = Song(player)
    #         ctx.voice_client.play(player, after=lambda e: print('Player error: %s' % e) if e else None)

    #     await ctx.send('Now playing: {}'.format(player.title))
    #     await ctx.send(embed=song.create_embed())
        # await ctx.send('Hint: If stream abruptly stop, try using download() instead.')

    # @commands.command()
    # async def volume(self, ctx, volume: int):
    #     """Changes the player's volume"""

    #     if ctx.voice_client is None:
    #         return await ctx.send("Not connected to a voice channel.")

    #     ctx.voice_client.source.volume = volume / 100
    #     await ctx.send("Changed volume to {}%".format(volume))

    # @commands.command()
    # async def stop(self, ctx):
    #     """Stops and disconnects the bot from voice"""

    #     await ctx.voice_client.disconnect()

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


    # @play.before_invoke
    # # @download.before_invoke
    # @local.before_invoke
    # async def ensure_voice(self, ctx):
    #     if ctx.voice_client is None:
    #         if ctx.author.voice:
    #             await ctx.author.voice.channel.connect()
    #         else:
    #             await ctx.send("You are not connected to a voice channel.")
    #             raise commands.CommandError("Author not connected to a voice channel.")
    #     elif ctx.voice_client.is_playing():
    #         ctx.voice_client.stop()

bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"),
                   description='BananiumLabs Discord Bot. Script by EnumC and 64bitpanda')

@bot.event
async def on_ready():
    print('Logged in as {0} ({0.id})'.format(bot.user))
    print('------')
    await bot.get_channel(751662103483383838).send('Logged in as {0} ({0.id})'.format(bot.user))
    await bot.change_presence(activity=discord.Activity(name=' for !help | Coded by EnumC and 64bitpanda', type=3)) # Displays 'Watching !help'

bot.add_cog(Bananium(bot))
bot.add_cog(Music(bot))
bot.run(discord_credentials)

# classTest = Bananium(bot)
# classTest.text_to_wav('en-US-Wavenet-A', "This is a test clip.")
