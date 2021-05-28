import random
import re
import traceback
from typing import Optional

import requests
import discord
from discord.ext import commands, menus
from quart import Quart, request, Response


ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ip = requests.get("https://api.ipify.org").text
DOMAIN = f"{ip}:7000"
DOT = "·"
HORI_LINE = " "
THICK_HORI_LINE = "═"
VERT_LINE = " "
THICK_VERT_LINE = "║"
ZWSP = "\u200b"
LINE_URL = f"http://{DOMAIN}/{{x}}/{{y}}"


class DotsAndBoxes:
    def __init__(self, players, width, height):
        self.players = players
        self.width = width
        self.height = height
        self.current_player = 0
        self.finished = False
        self.points = [0] * players
        self.lines = 0
        self.boxes = [0] * (width * height)
        self.hori_lines = [False] * (width * (height+1))
        self.vert_lines = [False] * (height * (width+1))

    def _fix_index(self, idx):
        return idx - idx // (self.width+1)

    def _update_boxes(self, idxs):
        completed = False
        for i in idxs:
            i = self._fix_index(i)
            self.boxes[i] += 1
            if self.boxes[i] == 4:
                # store who won it. a hack but who cares
                self.boxes[i] = 4, self.current_player
                self.points[self.current_player] += 1
                completed = True
        return completed

    def draw_line(self, x, y):
        x, y = sorted((x, y))
        if (invalid := discord.utils.find(lambda n: not 0 <= n < (self.width+1) * (self.height+1), (x, y))):
            raise ValueError(f"position {invalid} is out of bounds")

        if y == x + 1:
            if self.hori_lines[self._fix_index(x)]:
                raise ValueError(f"{x} to {y} was already drawn")
            self.hori_lines[self._fix_index(x)] = True
            idxs = [x-self.height-1] * (x >= self.width) + [x] * (x < (self.width+1) * self.height)
            repeat = self._update_boxes(idxs)
        elif y == x + self.width + 1:
            if self.vert_lines[x]:
                raise ValueError(f"{x} to {y} was already drawn")
            self.vert_lines[x] = True
            idxs = [x] * ((x+1) % (self.width+1) != 0) + [x-1] * (x % (self.width+1) != 0)
            repeat = self._update_boxes(idxs)
        else:
            raise ValueError(f"{x} to {y} is not a valid line")

        self.lines += 1
        if self.lines == self.width * (self.height+1) * 2:
            self.finished = True
        if not repeat:
            self.current_player = (self.current_player + 1) % self.players

    def _render_hori_line(self, i, fancy):
        segments = []
        for j in range(i*self.width, (i+1)*self.width):
            if fancy:
                if self.hori_lines[j]:
                    s = f"**`{THICK_HORI_LINE}`**"
                else:
                    k = j + j // self.width
                    s = f"[`{HORI_LINE}`]({LINE_URL})".format(x=k, y=k+1)
            else:
                s = "-" if self.hori_lines[j] else " "
            segments.append(s)
        sep = f"`{DOT}`" if fancy else "*"
        o = "".join(sep + s for s in segments) + sep
        if not fancy:
            o = str(i+1).rjust(2) + " " + o
        return o.replace("``", f"`{ZWSP}`")

    def _render_vert_line(self, i, fancy, icons):
        segments = []
        for j in range(i*(self.width+1), (i+1)*(self.width+1)):
            if fancy:
                if self.vert_lines[j]:
                    s = f"**`{THICK_VERT_LINE}`**"
                else:
                    s = f"[`{VERT_LINE}`]({LINE_URL})".format(x=j, y=j+self.width+1)
            else:
                s = "|" if self.vert_lines[j] else " "
            segments.append(s)
        o = []
        if not fancy:
            o.append("   ")
        o.append(segments[0])
        for j, s in enumerate(segments[1:]):
            box = self.boxes[i*self.width + j]
            space = f"`{icons[box[1]]}`" if isinstance(box, tuple) else "` `"
            if not fancy:
                space = space.replace("`", "")
            o.append(space)
            o.append(s)
        return "".join(o).replace("``", f"`{ZWSP}`")

    def render(self, icons, fancy):
        output = []
        if not fancy:
            output.append("```")
            output.append("   " + " ".join(ALPHABET[:self.width+1]))
        for i in range(self.height):
            output.append(self._render_hori_line(i, fancy))
            output.append(self._render_vert_line(i, fancy, icons))
        output.append(self._render_hori_line(i+1, fancy))
        if not fancy:
            output.append("```")
        return "\n".join(output)


class DiscordGame(menus.Menu):
    def __init__(self, players, width, height):
        super().__init__(timeout=None)
        self.players = players
        self.icons = []
        self.fancy_players = []
        for player in players:
            c = player.name[0]
            while c in self.icons:
                c = chr(ord(c)+1)
            self.icons.append(c)
            self.fancy_players.append(not player.is_on_mobile())
        self.game = DotsAndBoxes(len(players), width, height)

    def render_embed(self):
        embed = discord.Embed(
            title=self.players[self.game.current_player].display_name + "'s turn",
            description=self.game.render(self.icons, self.fancy_players[self.game.current_player]),
        )
        if self.game.finished:
            most = 0
            winner = None
            for player, points in zip(self.players, self.game.points):
                if points > most:
                    most = points
                    winner = player
                elif points == most:
                    # would be a tie
                    winner = None
            embed.title = f"{winner.display_name} wins!" if winner is not None else "It's a tie!"
            self.end()
        scores = "\n".join(f"{m.mention} [{i}] - {p}" for m, i, p in zip(self.players, self.icons, self.game.points))
        embed.add_field(name="Scores", value=scores)
        embed.set_footer(text="`a0-b0` syntax for chat moves. 📱 toggles mobile mode. 🔽 re-sends this message.")
        return embed

    async def make_move(self, x, y):
        self.game.draw_line(x, y)
        await self.message.edit(embed=self.render_embed())

    async def send_initial_message(self, ctx, channel):
        return await channel.send(embed=self.render_embed())

    def reaction_check(self, payload):
        if payload.message_id != self.message.id:
            return False
        if not discord.utils.get(self.players, id=payload.user_id):
            return False

        return payload.emoji in self.buttons

    def end(self):
        for player in self.players:
            player_games.pop(player)
        self.stop()

    @menus.button("📱")
    async def toggle_mobile(self, payload):
        index = next(i for i, p in enumerate(self.players) if p.id == payload.user_id)
        self.fancy_players[index] = not self.fancy_players[index]
        if index == self.game.current_player:
            await self.message.edit(embed=self.render_embed())

    @menus.button("🔽")
    async def resend_message(self, payload):
        await self.message.delete()
        self.message = None
        await self.start(self.ctx)

    @menus.button("\N{BLACK SQUARE FOR STOP}\ufe0f")
    async def cancel(self, payload):
        user = discord.utils.get(self.players, id=payload.user_id)
        e = self.message.embeds[0]
        e.title = f"Game cancelled by {user.display_name}. Go boo them!"
        await self.message.edit(embed=e)
        self.end()


bot = commands.Bot(command_prefix="tii!", intents=discord.Intents(guilds=True, messages=True, members=True, reactions=True), help_command=None)
bot.load_extension("jishaku")
player_games = {}

@commands.max_concurrency(1, commands.BucketType.channel)
@commands.guild_only()
@bot.command(aliases=["d&b"])
async def dab(ctx, width: Optional[int] = 4, height: Optional[int] = 4, *others: discord.Member):
    if ctx.author in player_games:
        return await ctx.send("Hey, you're already playing a game!")
    if already := [other.display_name for other in others if other in player_games]:
        if len(already) == 1:
            group = already[0] + " is"
        elif len(already) == 2:
            group = f"{already[0]} and {already[1]} are"
        else:
            group = ", ".join(already[:-1]) + f", and {already[-1]} are"
        return await ctx.send(f"{group} already playing Dots and Boxes.")

    players = [ctx.author, *others]
    random.shuffle(players)
    game = DiscordGame(players, width, height)
    try:
        await game.start(ctx)
    except discord.HTTPException:
        return await ctx.send("That board is too large to render. Sorry!")

    for player in players:
        player_games[player] = game

@bot.command()
async def link(ctx):
    try:
        await ctx.author.send(embed=discord.Embed(description=f"Click [here](http://{DOMAIN}/link/{ctx.author.id}) to link your account."))
    except discord.Forbidden:
        await ctx.send("I need to send you a DM. Please fix your settings.")

@bot.event
async def on_message(message):
    game = player_games.get(message.author)
    if game and message.channel == game.message.channel:
        if m := re.fullmatch("([a-z][0-9]+)-([a-z][0-9]+)", message.content, re.IGNORECASE):
            x, y = [ALPHABET.index(coord[0].upper()) + (game.game.width+1) * (int(coord[1:])-1) for coord in m.group(1, 2)]
            try:
                await game.make_move(x, y)
            except ValueError:
                await message.channel.send("Invalid move.", delete_after=2)
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MaxConcurrencyReached):
        await ctx.send("A game is already being played in this channel.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        traceback.print_exception(type(error), error, error.__traceback__)
        await ctx.send(f"Uh... hey, <@319753218592866315>? Sorry, {ctx.author.display_name}, just a minute. Something's gone wrong...")


app = Quart(__name__)

@app.route("/<int:x>/<int:y>")
async def move(x, y):
    user_id = request.cookies.get("id")
    if not user_id:
        return "I don't know who you are. Use `Ke2!!link` to link your browser with your Discord account.", 404
    user = bot.get_user(int(user_id))
    game = player_games.get(user)
    if not game:
        return "Uh, you're not playing a game.", 404
    if game.players[game.game.current_player] != user:
        return "Hey, you're not the current player.", 403
    try:
        await game.make_move(x, y)
    except ValueError:
        return "That's an invalid move.", 400
    return "", 204

@app.route("/link/<int:id>")
async def link(id):
    resp = Response("All good. You can exit this page now.")
    resp.set_cookie("id", str(id), max_age=2**31-1)
    return resp

bot.loop.create_task(app.run_task("0.0.0.0", 7000))

with open("token.txt") as t:
    token = t.read()

bot.run(token.strip())
