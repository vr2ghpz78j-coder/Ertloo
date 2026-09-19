# ============================================================
# main.py - Discord Bot شامل: بنك + اقتصاد + نقاط + لفلات + ألعاب
# + إدارة + سجن + تكتات + ترحيب + Auto + Logs + تقرير أسبوعي
#
# المتطلبات:
#   pip install -U discord.py aiosqlite
#
# في Wispbyte:
#   Startup file: main.py
#   Environment variable: DISCORD_TOKEN = توكن البوت
#
# لا تضع التوكن داخل هذا الملف ولا ترسله لأي شخص.
# ============================================================

import os
import random
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

# ---------------- CONFIG ----------------

TOKEN = os.getenv("DISCORD_TOKEN")
DB_FILE = "bot.db"
PREFIX = "-"

DAILY_AMOUNT = 3_000
WEEKLY_AMOUNT = 15_000
SALARY_AMOUNT = 10_000

ROB_COOLDOWN = 3600
WORK_COOLDOWN = 1800
DAILY_COOLDOWN = 86400
WEEKLY_COOLDOWN = 604800
SALARY_COOLDOWN = 86400

DEFAULT_GAME_POINTS = 3
ORGANIZER_MIN_REWARD = 50
MAX_GROUP_PLAYERS = 100

CHAT_XP_PER_MESSAGE = 5
VOICE_XP_PER_MINUTE = 2
XP_COOLDOWN = 30

JAIL_ROLE_NAME = "السجن"

# ---------------- BOT ----------------

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)

# ---------------- DATABASE ----------------

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

def db_exec(sql, params=(), fetch=False, many=False):
    cur = db.cursor()
    if many:
        cur.executemany(sql, params)
    else:
        cur.execute(sql, params)
    db.commit()
    if fetch:
        return cur.fetchall()
    return cur.lastrowid

def init_db():
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        cash INTEGER DEFAULT 0,
        bank INTEGER DEFAULT 0,
        game_points INTEGER DEFAULT 0,
        chat_xp INTEGER DEFAULT 0,
        voice_xp INTEGER DEFAULT 0,
        admin_xp INTEGER DEFAULT 0,
        admin_points INTEGER DEFAULT 0,
        total_earned INTEGER DEFAULT 0,
        total_spent INTEGER DEFAULT 0,
        total_transferred INTEGER DEFAULT 0,
        total_stolen INTEGER DEFAULT 0,
        times_stolen INTEGER DEFAULT 0,
        weekly_stolen INTEGER DEFAULT 0,
        weekly_stolen_amount INTEGER DEFAULT 0,
        last_daily INTEGER DEFAULT 0,
        last_weekly INTEGER DEFAULT 0,
        last_salary INTEGER DEFAULT 0,
        last_rob INTEGER DEFAULT 0,
        last_work INTEGER DEFAULT 0,
        last_chat_xp INTEGER DEFAULT 0,
        frozen INTEGER DEFAULT 0,
        job TEXT DEFAULT '',
        loan INTEGER DEFAULT 0,
        spouse_id INTEGER DEFAULT 0,
        property TEXT DEFAULT '',
        level_reward_claimed INTEGER DEFAULT 0,
        PRIMARY KEY(guild_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS settings (
        guild_id INTEGER PRIMARY KEY,
        welcome_channel INTEGER DEFAULT 0,
        rules_channel INTEGER DEFAULT 0,
        jail_channel INTEGER DEFAULT 0,
        jail_role INTEGER DEFAULT 0,
        ticket_category INTEGER DEFAULT 0,
        ticket_log_channel INTEGER DEFAULT 0,
        weekly_channel INTEGER DEFAULT 0,
        weekly_mention INTEGER DEFAULT 1,
        game_organizer_role INTEGER DEFAULT 0,
        settings_roles TEXT DEFAULT '',
        log_channels TEXT DEFAULT '{}',
        auto_rules TEXT DEFAULT '[]',
        level_rewards TEXT DEFAULT '{}',
        game_images TEXT DEFAULT '{}',
        point_shop TEXT DEFAULT '[]'
    );

    CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        user_id INTEGER,
        moderator_id INTEGER,
        reason TEXT,
        created_at INTEGER
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        user_id INTEGER,
        kind TEXT,
        amount INTEGER,
        note TEXT,
        created_at INTEGER
    );

    CREATE TABLE IF NOT EXISTS tickets (
        channel_id INTEGER PRIMARY KEY,
        guild_id INTEGER,
        owner_id INTEGER,
        claimed_by INTEGER DEFAULT 0,
        ticket_type TEXT,
        created_at INTEGER
    );

    CREATE TABLE IF NOT EXISTS admin_tasks (
        guild_id INTEGER,
        user_id INTEGER,
        task_key TEXT,
        progress INTEGER DEFAULT 0,
        PRIMARY KEY(guild_id,user_id,task_key)
    );
    """)
    db.commit()

def ensure_user(guild_id, user_id):
    db_exec(
        "INSERT OR IGNORE INTO users(guild_id,user_id) VALUES(?,?)",
        (guild_id, user_id)
    )

def get_user(guild_id, user_id):
    ensure_user(guild_id, user_id)
    return db_exec(
        "SELECT * FROM users WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
        True
    )[0]

def update_user(guild_id, user_id, field, value):
    allowed = {
        "cash", "bank", "game_points", "chat_xp", "voice_xp",
        "admin_xp", "admin_points", "total_earned", "total_spent",
        "total_transferred", "total_stolen", "times_stolen",
        "weekly_stolen", "weekly_stolen_amount", "last_daily",
        "last_weekly", "last_salary", "last_rob", "last_work",
        "last_chat_xp", "frozen", "job", "loan", "spouse_id",
        "property", "level_reward_claimed"
    }
    if field not in allowed:
        raise ValueError("Invalid database field")
    db_exec(f"UPDATE users SET {field}=? WHERE guild_id=? AND user_id=?",
            (value, guild_id, user_id))

def add_user(guild_id, user_id, field, amount):
    row = get_user(guild_id, user_id)
    update_user(guild_id, user_id, field, row[field] + amount)

def get_settings(guild_id):
    row = db_exec("SELECT * FROM settings WHERE guild_id=?", (guild_id,), True)
    if row:
        return row[0]
    db_exec("INSERT INTO settings(guild_id) VALUES(?)", (guild_id,))
    return db_exec("SELECT * FROM settings WHERE guild_id=?", (guild_id,), True)[0]

def log_transaction(guild_id, user_id, kind, amount, note=""):
    db_exec(
        """INSERT INTO transactions(guild_id,user_id,kind,amount,note,created_at)
           VALUES(?,?,?,?,?,?)""",
        (guild_id, user_id, kind, amount, note, int(datetime.now().timestamp()))
    )

def now_ts():
    return int(datetime.now(timezone.utc).timestamp())

def cooldown_left(last, cooldown):
    return max(0, cooldown - (now_ts() - last))

def fmt_money(n):
    return f"{int(n):,}$"

async def send_log(guild, log_type, title, description, color=discord.Color.blurple()):
    try:
        s = get_settings(guild.id)
        import json
        channels = json.loads(s["log_channels"] or "{}")
        channel_id = channels.get(log_type) or channels.get("general")
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
        if not channel:
            return
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        await channel.send(embed=embed)
    except Exception:
        pass

def is_admin(member: discord.Member):
    return member.guild_permissions.administrator or member.guild_permissions.manage_guild

# ---------------- EVENTS ----------------

@bot.event
async def on_ready():
    init_db()
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Slash sync:", e)

    if not weekly_report_loop.is_running():
        weekly_report_loop.start()

    print(f"Logged in as {bot.user} | Guilds: {len(bot.guilds)}")

@bot.event
async def on_guild_join(guild):
    get_settings(guild.id)

@bot.event
async def on_member_join(member):
    ensure_user(member.guild.id, member.id)
    s = get_settings(member.guild.id)
    channel = member.guild.get_channel(s["welcome_channel"])
    if not channel:
        return

    rules = ""
    if s["rules_channel"]:
        rules = f"\n📜 القوانين: <#{s['rules_channel']}>"

    embed = discord.Embed(
        title="👋 أهلاً وسهلاً!",
        description=f"نورتنا {member.mention}\n"
                    f"أنت العضو رقم **{member.guild.member_count}**{rules}",
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    await send_log(
        member.guild,
        "member",
        "📤 خروج عضو",
        f"العضو: {member.mention}\nID: `{member.id}`",
        discord.Color.orange()
    )

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    ensure_user(message.guild.id, message.author.id)

    # Auto reactions / replies
    s = get_settings(message.guild.id)
    try:
        import json
        rules = json.loads(s["auto_rules"] or "[]")
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            if rule.get("channel_id") and int(rule["channel_id"]) != message.channel.id:
                continue
            keyword = str(rule.get("keyword", "")).lower()
            if keyword and keyword in message.content.lower():
                if rule.get("reaction"):
                    await message.add_reaction(rule["reaction"])
                if rule.get("reply"):
                    await message.reply(rule["reply"])
    except Exception:
        pass

    # Chat XP with anti-spam
    user = get_user(message.guild.id, message.author.id)
    if now_ts() - user["last_chat_xp"] >= XP_COOLDOWN:
        add_user(message.guild.id, message.author.id, "chat_xp", CHAT_XP_PER_MESSAGE)
        update_user(message.guild.id, message.author.id, "last_chat_xp", now_ts())

    await bot.process_commands(message)

# ---------------- BASIC BANK COMMANDS ----------------

@bot.hybrid_command(name="رصيد", description="عرض رصيدك")
async def balance(ctx, member: Optional[discord.Member] = None):
    member = member or ctx.author
    u = get_user(ctx.guild.id, member.id)
    total = u["cash"] + u["bank"]

    embed = discord.Embed(title=f"💳 حساب {member.display_name}", color=discord.Color.gold())
    embed.add_field(name="💵 الكاش", value=fmt_money(u["cash"]))
    embed.add_field(name="🏦 البنك", value=fmt_money(u["bank"]))
    embed.add_field(name="💰 الثروة", value=fmt_money(total))
    embed.add_field(name="⭐ نقاط الألعاب", value=f"{u['game_points']:,}")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="حساب", description="معلومات حسابك")
async def account(ctx):
    u = get_user(ctx.guild.id, ctx.author.id)
    await ctx.send(
        f"👤 **{ctx.author.display_name}**\n"
        f"💵 الكاش: {fmt_money(u['cash'])}\n"
        f"🏦 البنك: {fmt_money(u['bank'])}\n"
        f"💰 الثروة: {fmt_money(u['cash'] + u['bank'])}\n"
        f"🆙 Chat XP: {u['chat_xp']:,}\n"
        f"🎙️ Voice XP: {u['voice_xp']:,}"
    )

@bot.hybrid_command(name="يومي", description="المكافأة اليومية")
async def daily(ctx):
    u = get_user(ctx.guild.id, ctx.author.id)
    left = cooldown_left(u["last_daily"], DAILY_COOLDOWN)
    if left:
        return await ctx.send(f"⏳ باقي {left//3600}س {(left%3600)//60}د.")
    add_user(ctx.guild.id, ctx.author.id, "cash", DAILY_AMOUNT)
    add_user(ctx.guild.id, ctx.author.id, "total_earned", DAILY_AMOUNT)
    update_user(ctx.guild.id, ctx.author.id, "last_daily", now_ts())
    log_transaction(ctx.guild.id, ctx.author.id, "daily", DAILY_AMOUNT, "مكافأة يومية")
    await ctx.send(f"🎁 أخذت مكافأتك اليومية: **{fmt_money(DAILY_AMOUNT)}**")

@bot.hybrid_command(name="اسبوعي", description="المكافأة الأسبوعية")
async def weekly(ctx):
    u = get_user(ctx.guild.id, ctx.author.id)
    left = cooldown_left(u["last_weekly"], WEEKLY_COOLDOWN)
    if left:
        return await ctx.send(f"⏳ باقي {left//86400}ي.")
    add_user(ctx.guild.id, ctx.author.id, "cash", WEEKLY_AMOUNT)
    add_user(ctx.guild.id, ctx.author.id, "total_earned", WEEKLY_AMOUNT)
    update_user(ctx.guild.id, ctx.author.id, "last_weekly", now_ts())
    await ctx.send(f"🎁 أخذت المكافأة الأسبوعية: **{fmt_money(WEEKLY_AMOUNT)}**")

@bot.hybrid_command(name="راتب", description="استلام الراتب")
async def salary(ctx):
    u = get_user(ctx.guild.id, ctx.author.id)
    left = cooldown_left(u["last_salary"], SALARY_COOLDOWN)
    if left:
        return await ctx.send(f"⏳ الراتب القادم بعد {left//3600}س.")
    add_user(ctx.guild.id, ctx.author.id, "cash", SALARY_AMOUNT)
    add_user(ctx.guild.id, ctx.author.id, "total_earned", SALARY_AMOUNT)
    update_user(ctx.guild.id, ctx.author.id, "last_salary", now_ts())
    await ctx.send(f"💼 استلمت راتبك: **{fmt_money(SALARY_AMOUNT)}**")

@bot.hybrid_command(name="ايداع", description="إيداع من الكاش إلى البنك")
@app_commands.describe(amount="المبلغ")
async def deposit(ctx, amount: int):
    if amount <= 0:
        return await ctx.send("❌ المبلغ غير صحيح.")
    u = get_user(ctx.guild.id, ctx.author.id)
    if u["cash"] < amount:
        return await ctx.send("❌ ما عندك هذا المبلغ كاش.")
    add_user(ctx.guild.id, ctx.author.id, "cash", -amount)
    add_user(ctx.guild.id, ctx.author.id, "bank", amount)
    await ctx.send(f"🏦 تم إيداع **{fmt_money(amount)}**.")

@bot.hybrid_command(name="سحب", description="سحب من البنك إلى الكاش")
@app_commands.describe(amount="المبلغ")
async def withdraw(ctx, amount: int):
    if amount <= 0:
        return await ctx.send("❌ المبلغ غير صحيح.")
    u = get_user(ctx.guild.id, ctx.author.id)
    if u["bank"] < amount:
        return await ctx.send("❌ رصيد البنك غير كافٍ.")
    add_user(ctx.guild.id, ctx.author.id, "bank", -amount)
    add_user(ctx.guild.id, ctx.author.id, "cash", amount)
    await ctx.send(f"💵 تم سحب **{fmt_money(amount)}**.")

@bot.hybrid_command(name="تحويل", description="تحويل كاش لعضو")
@app_commands.describe(member="المستلم", amount="المبلغ")
async def transfer(ctx, member: discord.Member, amount: int):
    if member.bot or member.id == ctx.author.id or amount <= 0:
        return await ctx.send("❌ البيانات غير صحيحة.")
    u = get_user(ctx.guild.id, ctx.author.id)
    if u["cash"] < amount:
        return await ctx.send("❌ رصيدك الكاش غير كافٍ.")
    add_user(ctx.guild.id, ctx.author.id, "cash", -amount)
    add_user(ctx.guild.id, member.id, "cash", amount)
    add_user(ctx.guild.id, ctx.author.id, "total_transferred", amount)
    log_transaction(ctx.guild.id, ctx.author.id, "transfer", -amount, f"إلى {member.id}")
    await ctx.send(f"💸 تم تحويل **{fmt_money(amount)}** إلى {member.mention}.")

@bot.hybrid_command(name="سرقة", description="سرقة من كاش عضو آخر")
@app_commands.describe(member="الهدف")
async def rob(ctx, member: discord.Member):
    if member.bot or member.id == ctx.author.id:
        return await ctx.send("❌ لا يمكن.")
    u = get_user(ctx.guild.id, ctx.author.id)
    left = cooldown_left(u["last_rob"], ROB_COOLDOWN)
    if left:
        return await ctx.send(f"⏳ انتظر {left//60} دقيقة.")
    target = get_user(ctx.guild.id, member.id)
    if target["cash"] <= 0:
        return await ctx.send("❌ الهدف ما عنده كاش.")
    update_user(ctx.guild.id, ctx.author.id, "last_rob", now_ts())
    if random.random() < 0.45:
        amount = random.randint(1, max(1, min(target["cash"], 5000)))
        add_user(ctx.guild.id, member.id, "cash", -amount)
        add_user(ctx.guild.id, ctx.author.id, "cash", amount)
        add_user(ctx.guild.id, ctx.author.id, "total_stolen", amount)
        add_user(ctx.guild.id, ctx.author.id, "weekly_stolen", 1)
        add_user(ctx.guild.id, ctx.author.id, "weekly_stolen_amount", amount)
        add_user(ctx.guild.id, ctx.author.id, "times_stolen", 1)
        await ctx.send(f"🕵️ نجحت السرقة! أخذت **{fmt_money(amount)}** من {member.mention}.")
    else:
        await ctx.send("🚨 فشلت السرقة.")

@bot.hybrid_command(name="حظ", description="لعبة حظ بسيطة بدون مراهنات")
async def luck(ctx):
    reward = random.randint(100, 1500)
    if random.random() < 0.5:
        add_user(ctx.guild.id, ctx.author.id, "cash", reward)
        await ctx.send(f"🍀 حظك اليوم! ربحت **{fmt_money(reward)}**.")
    else:
        await ctx.send("🍀 ما ضبطت هذه المرة.")

# ---------------- GAME POINTS ----------------

@bot.hybrid_command(name="نقاط", description="عرض نقاط الألعاب")
async def points(ctx, member: Optional[discord.Member] = None):
    member = member or ctx.author
    u = get_user(ctx.guild.id, member.id)
    await ctx.send(f"⭐ نقاط {member.mention}: **{u['game_points']:,}**")

@bot.hybrid_command(name="تحويل_نقاط", description="تحويل نقاط ألعاب")
@app_commands.describe(member="المستلم", amount="عدد النقاط")
async def transfer_points(ctx, member: discord.Member, amount: int):
    if amount <= 0 or member.bot or member.id == ctx.author.id:
        return await ctx.send("❌ البيانات غير صحيحة.")
    u = get_user(ctx.guild.id, ctx.author.id)
    if u["game_points"] < amount:
        return await ctx.send("❌ نقاطك غير كافية.")
    add_user(ctx.guild.id, ctx.author.id, "game_points", -amount)
    add_user(ctx.guild.id, member.id, "game_points", amount)
    await ctx.send(f"⭐ تم تحويل **{amount}** نقطة إلى {member.mention}.")

@bot.hybrid_command(name="توب_النقاط", description="أفضل اللاعبين بالنقاط")
async def top_points(ctx):
    rows = db_exec(
        "SELECT user_id, game_points FROM users WHERE guild_id=? ORDER BY game_points DESC LIMIT 10",
        (ctx.guild.id,), True
    )
    text = "\n".join(
        f"**{i}.** <@{r['user_id']}> — {r['game_points']:,} نقطة"
        for i, r in enumerate(rows, 1)
    ) or "لا يوجد بيانات."
    await ctx.send("🏆 **توب نقاط الألعاب**\n" + text)

# ---------------- SIMPLE GAMES ----------------

active_games = {}

async def game_lock(ctx):
    if ctx.channel.id in active_games:
        await ctx.send("🎮 يوجد لعبة شغالة في هذا الروم بالفعل.")
        return False
    active_games[ctx.channel.id] = True
    return True

def game_unlock(ctx):
    active_games.pop(ctx.channel.id, None)

@bot.hybrid_command(name="نرد", description="رمي النرد")
async def dice(ctx):
    if not await game_lock(ctx):
        return
    try:
        n = random.randint(1, 6)
        add_user(ctx.guild.id, ctx.author.id, "game_points", DEFAULT_GAME_POINTS)
        await ctx.send(f"🎲 {ctx.author.mention} رمى النرد وطلع **{n}**.\n⭐ +{DEFAULT_GAME_POINTS} نقاط")
    finally:
        game_unlock(ctx)

@bot.hybrid_command(name="حجرة", description="حجرة ورقة مقص")
@app_commands.describe(choice="حجر أو ورق أو مقص")
async def rps(ctx, choice: str):
    choices = ["حجر", "ورق", "مقص"]
    if choice not in choices:
        return await ctx.send("اكتب: حجر أو ورق أو مقص.")
    bot_choice = random.choice(choices)
    wins = {("حجر","مقص"), ("ورق","حجر"), ("مقص","ورق")}
    if choice == bot_choice:
        result = "تعادل."
    elif (choice, bot_choice) in wins:
        add_user(ctx.guild.id, ctx.author.id, "game_points", DEFAULT_GAME_POINTS)
        result = f"فزت! ⭐ +{DEFAULT_GAME_POINTS}"
    else:
        result = "فزت عليك 😄"
    await ctx.send(f"🪨 اختيارك: **{choice}**\n🤖 اختياري: **{bot_choice}**\n{result}")

@bot.hybrid_command(name="اسرع", description="أول شخص يكتب الكلمة يفوز")
async def fastest(ctx):
    word = random.choice(["تفاحة", "سيارة", "مدرسة", "برمجة", "مغامرة", "مجرة"])
    await ctx.send(f"⚡ **أسرع!** اكتب الكلمة التالية:\n# {word}")
    def check(m):
        return m.channel.id == ctx.channel.id and not m.author.bot and m.content.strip() == word
    try:
        winner = await bot.wait_for("message", timeout=20, check=check)
        add_user(ctx.guild.id, winner.author.id, "game_points", DEFAULT_GAME_POINTS)
        await ctx.send(f"🏆 أسرع شخص: {winner.author.mention} — ⭐ +{DEFAULT_GAME_POINTS}")
    except asyncio.TimeoutError:
        await ctx.send("⌛ انتهى الوقت بدون فائز.")

@bot.hybrid_command(name="خمن", description="خمن الرقم")
async def guess(ctx):
    number = random.randint(1, 10)
    await ctx.send("🔢 خمن رقمًا من 1 إلى 10. لديك 15 ثانية.")
    def check(m):
        return m.channel.id == ctx.channel.id and m.author.id == ctx.author.id
    try:
        m = await bot.wait_for("message", timeout=15, check=check)
        if m.content.isdigit() and int(m.content) == number:
            add_user(ctx.guild.id, ctx.author.id, "game_points", 5)
            await ctx.send("🎉 صح! ⭐ +5")
        else:
            await ctx.send(f"❌ غلط، الرقم كان **{number}**.")
    except asyncio.TimeoutError:
        await ctx.send(f"⌛ انتهى الوقت. الرقم كان **{number}**.")

@bot.hybrid_command(name="xo", description="لعبة XO بسيطة")
async def xo(ctx):
    board = ["⬜"] * 9
    turn = ctx.author
    await ctx.send(
        "❌ **XO**\n" +
        "\n".join("".join(board[i:i+3]) for i in range(0,9,3)) +
        "\nاكتب رقم الخانة 1-9."
    )
    # نسخة أساسية: اللاعب ضد البوت.
    while True:
        def check(m):
            return m.channel.id == ctx.channel.id and m.author.id == turn.id and m.content.isdigit()
        try:
            m = await bot.wait_for("message", timeout=45, check=check)
        except asyncio.TimeoutError:
            return await ctx.send("⌛ انتهت اللعبة.")
        pos = int(m.content) - 1
        if pos not in range(9) or board[pos] != "⬜":
            await ctx.send("❌ خانة غير صالحة.")
            continue
        board[pos] = "❌"
        if check_win(board, "❌"):
            add_user(ctx.guild.id, ctx.author.id, "game_points", 5)
            return await ctx.send("🏆 فزت! ⭐ +5")
        if "⬜" not in board:
            return await ctx.send("🤝 تعادل.")
        choices = [i for i,v in enumerate(board) if v == "⬜"]
        board[random.choice(choices)] = "⭕"
        if check_win(board, "⭕"):
            return await ctx.send("🤖 البوت فاز.")
        await ctx.send("\n".join("".join(board[i:i+3]) for i in range(0,9,3)))

def check_win(board, mark):
    combos = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    return any(all(board[i] == mark for i in c) for c in combos)

# ---------------- ROULETTE ELIMINATION GAME ----------------

@bot.hybrid_command(name="روليت", description="لعبة إقصاء جماعية بدون مراهنات")
@app_commands.describe(reward="مكافأة نقاط الألعاب")
async def roulette(ctx, reward: Optional[int] = None):
    if reward is None:
        reward = DEFAULT_GAME_POINTS
    organizer_role = get_settings(ctx.guild.id)["game_organizer_role"]
    if reward >= ORGANIZER_MIN_REWARD and not (
        organizer_role and any(r.id == organizer_role for r in ctx.author.roles)
    ) and not is_admin(ctx.author):
        return await ctx.send(f"❌ المكافأة الكبيرة متاحة لمن لديه رتبة منظم الألعاب. الحد الأدنى لها {ORGANIZER_MIN_REWARD} نقطة.")

    members = [m for m in ctx.guild.members if not m.bot]
    if len(members) < 2:
        return await ctx.send("❌ نحتاج لاعبين على الأقل.")

    members = members[:MAX_GROUP_PLAYERS]
    await ctx.send(
        f"🎯 **روليت الإقصاء بدأت!**\n"
        f"اللاعبون: **{len(members)}**\n"
        f"المكافأة: **{reward} نقطة**\n"
        f"في كل جولة يتم اختيار لاعب عشوائي، وهو يختار لاعبًا آخر للإقصاء."
    )

    alive = members[:]
    while len(alive) > 1:
        selected = random.choice(alive)
        await ctx.send(f"🎲 تم اختيار {selected.mention} عشوائيًا. اختر شخصًا لإقصائه بالمنشن.")
        def check(m):
            return (
                m.channel.id == ctx.channel.id and
                m.author.id == selected.id and
                m.mentions and
                m.mentions[0] in alive and
                m.mentions[0].id != selected.id
            )
        try:
            msg = await bot.wait_for("message", timeout=60, check=check)
        except asyncio.TimeoutError:
            eliminated = random.choice([x for x in alive if x.id != selected.id])
            await ctx.send(f"⌛ انتهى الوقت، وتم إقصاء {eliminated.mention}.")
        else:
            eliminated = msg.mentions[0]
            await ctx.send(f"❌ {eliminated.mention} خرج من اللعبة.")
        if eliminated in alive:
            alive.remove(eliminated)

    winner = alive[0]
    add_user(ctx.guild.id, winner.id, "game_points", reward)
    await ctx.send(f"🏆 الفائز في الروليت: {winner.mention}\n⭐ حصل على **{reward} نقطة**.")

# ---------------- MODERATION ----------------

@bot.hybrid_command(name="تحذير", description="تحذير عضو")
@app_commands.describe(member="العضو", reason="سبب التحذير")
@commands.has_permissions(moderate_members=True)
async def warn(ctx, member: discord.Member, reason: str):
    db_exec(
        "INSERT INTO warnings(guild_id,user_id,moderator_id,reason,created_at) VALUES(?,?,?,?,?)",
        (ctx.guild.id, member.id, ctx.author.id, reason, now_ts())
    )
    add_user(ctx.guild.id, ctx.author.id, "admin_xp", 5)
    await ctx.send(f"⚠️ تم تحذير {member.mention}\nالسبب: {reason}")
    await send_log(ctx.guild, "moderation", "⚠️ تحذير", f"{member.mention}\nالمشرف: {ctx.author.mention}\nالسبب: {reason}")

@bot.hybrid_command(name="تايم_اوت", description="تايم اوت لعضو")
@app_commands.describe(member="العضو", minutes="الدقائق")
@commands.has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, minutes: int):
    if minutes <= 0 or minutes > 40320:
        return await ctx.send("❌ المدة يجب أن تكون بين 1 و40320 دقيقة.")
    await member.timeout(timedelta(minutes=minutes), reason=f"بواسطة {ctx.author}")
    add_user(ctx.guild.id, ctx.author.id, "admin_xp", 5)
    await ctx.send(f"🔇 تم إعطاء {member.mention} تايم اوت لمدة {minutes} دقيقة.")
    await send_log(ctx.guild, "moderation", "🔇 Timeout", f"{member.mention}\nبواسطة: {ctx.author.mention}\nالمدة: {minutes} دقيقة")

@bot.hybrid_command(name="كيك", description="طرد عضو")
@app_commands.describe(member="العضو", reason="السبب")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, reason: str = "بدون سبب"):
    await member.kick(reason=reason)
    add_user(ctx.guild.id, ctx.author.id, "admin_xp", 10)
    await ctx.send(f"👢 تم طرد {member.mention}.")
    await send_log(ctx.guild, "moderation", "👢 Kick", f"العضو: {member.mention}\nالسبب: {reason}")

@bot.hybrid_command(name="باند", description="حظر عضو")
@app_commands.describe(member="العضو", reason="السبب")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, reason: str = "بدون سبب"):
    await member.ban(reason=reason)
    add_user(ctx.guild.id, ctx.author.id, "admin_xp", 15)
    await ctx.send(f"🔨 تم حظر {member.mention}.")
    await send_log(ctx.guild, "moderation", "🔨 Ban", f"العضو: {member.mention}\nالسبب: {reason}")

@bot.hybrid_command(name="مسح", description="مسح رسائل")
@app_commands.describe(amount="عدد الرسائل")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    if amount < 1 or amount > 100:
        return await ctx.send("❌ العدد من 1 إلى 100.")
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 تم مسح **{len(deleted)-1}** رسالة.", delete_after=5)
    add_user(ctx.guild.id, ctx.author.id, "admin_xp", 3)

# ---------------- JAIL ----------------

@bot.hybrid_command(name="سجن", description="سجن عضو")
@app_commands.describe(member="العضو", reason="السبب")
@commands.has_permissions(manage_roles=True)
async def jail(ctx, member: discord.Member, reason: str = "بدون سبب"):
    s = get_settings(ctx.guild.id)
    role = ctx.guild.get_role(s["jail_role"]) if s["jail_role"] else None
    if not role:
        role = discord.utils.get(ctx.guild.roles, name=JAIL_ROLE_NAME)
    if not role:
        return await ctx.send("❌ لم يتم تحديد/إنشاء رتبة السجن.")

    await member.add_roles(role, reason=reason)
    jail_channel = ctx.guild.get_channel(s["jail_channel"]) if s["jail_channel"] else None
    if jail_channel:
        try:
            await jail_channel.set_permissions(member, view_channel=True, send_messages=True)
        except Exception:
            pass

    await ctx.send(f"🔒 تم سجن {member.mention}.")
    await send_log(ctx.guild, "moderation", "🔒 سجن", f"{member.mention}\nالمشرف: {ctx.author.mention}\nالسبب: {reason}")

@bot.hybrid_command(name="فك_السجن", description="فك سجن عضو")
@app_commands.describe(member="العضو")
@commands.has_permissions(manage_roles=True)
async def unjail(ctx, member: discord.Member):
    s = get_settings(ctx.guild.id)
    role = ctx.guild.get_role(s["jail_role"]) if s["jail_role"] else None
    if not role:
        role = discord.utils.get(ctx.guild.roles, name=JAIL_ROLE_NAME)
    if not role:
        return await ctx.send("❌ لم يتم تحديد رتبة السجن.")
    await member.remove_roles(role)
    await ctx.send(f"🔓 تم فك السجن عن {member.mention}.")

# ---------------- WARNINGS ----------------

@bot.hybrid_command(name="تحذيراتي", description="عرض تحذيراتك")
async def my_warnings(ctx, member: Optional[discord.Member] = None):
    member = member or ctx.author
    rows = db_exec(
        "SELECT reason, moderator_id, created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 20",
        (ctx.guild.id, member.id), True
    )
    if not rows:
        return await ctx.send("✅ لا توجد تحذيرات.")
    text = []
    for i, r in enumerate(rows, 1):
        text.append(f"{i}. {r['reason']} — <@{r['moderator_id']}>")
    await ctx.send(f"⚠️ تحذيرات {member.mention}:\n" + "\n".join(text))

# ---------------- LEADERBOARDS / LEVELS ----------------

@bot.hybrid_command(name="توب", description="أفضل الأعضاء")
async def top(ctx):
    rows = db_exec(
        """SELECT user_id, chat_xp, voice_xp, cash, bank
           FROM users WHERE guild_id=? ORDER BY (cash+bank) DESC LIMIT 10""",
        (ctx.guild.id,), True
    )
    text = "\n".join(
        f"**{i}.** <@{r['user_id']}> — 💰 {fmt_money(r['cash']+r['bank'])} | 🆙 {r['chat_xp']:,} XP"
        for i,r in enumerate(rows,1)
    )
    await ctx.send("🏆 **توب السيرفر**\n" + text)

@bot.hybrid_command(name="لفلي", description="عرض لفلك")
async def my_level(ctx):
    u = get_user(ctx.guild.id, ctx.author.id)
    chat_level = u["chat_xp"] // 100 + 1
    voice_level = u["voice_xp"] // 100 + 1
    await ctx.send(
        f"🆙 **مستواك**\n"
        f"💬 الشات: Level **{chat_level}** — {u['chat_xp']:,} XP\n"
        f"🎙️ الفويس: Level **{voice_level}** — {u['voice_xp']:,} XP"
    )

# ---------------- ADMIN ECONOMY ----------------

@bot.hybrid_command(name="اعطاء", description="إعطاء فلوس لعضو")
@app_commands.describe(member="العضو", amount="المبلغ")
@commands.has_permissions(administrator=True)
async def give(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send("❌ المبلغ غير صحيح.")
    add_user(ctx.guild.id, member.id, "cash", amount)
    await ctx.send(f"💰 تم إعطاء {member.mention} **{fmt_money(amount)}**.")

@bot.hybrid_command(name="خصم", description="خصم فلوس من عضو")
@app_commands.describe(member="العضو", amount="المبلغ")
@commands.has_permissions(administrator=True)
async def take(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send("❌ المبلغ غير صحيح.")
    u = get_user(ctx.guild.id, member.id)
    amount = min(amount, u["cash"])
    add_user(ctx.guild.id, member.id, "cash", -amount)
    await ctx.send(f"💸 تم خصم **{fmt_money(amount)}** من {member.mention}.")

@bot.hybrid_command(name="تجميد", description="تجميد حساب")
@commands.has_permissions(administrator=True)
async def freeze(ctx, member: discord.Member):
    update_user(ctx.guild.id, member.id, "frozen", 1)
    await ctx.send(f"🧊 تم تجميد حساب {member.mention}.")

@bot.hybrid_command(name="فك_تجميد", description="فك تجميد حساب")
@commands.has_permissions(administrator=True)
async def unfreeze(ctx, member: discord.Member):
    update_user(ctx.guild.id, member.id, "frozen", 0)
    await ctx.send(f"🔥 تم فك تجميد حساب {member.mention}.")

# ---------------- TICKETS ----------------

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="استفسار", style=discord.ButtonStyle.primary, custom_id="ticket_question")
    async def question(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket(interaction, "استفسار")

    @discord.ui.button(label="شكوى", style=discord.ButtonStyle.danger, custom_id="ticket_complaint")
    async def complaint(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket(interaction, "شكوى")

    @discord.ui.button(label="إدارة عليا", style=discord.ButtonStyle.secondary, custom_id="ticket_high")
    async def high(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket(interaction, "إدارة عليا")

async def create_ticket(interaction, ticket_type):
    guild = interaction.guild
    s = get_settings(guild.id)
    category = guild.get_channel(s["ticket_category"]) if s["ticket_category"] else None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }

    channel = await guild.create_text_channel(
        f"ticket-{interaction.user.name}".lower()[:90],
        category=category if isinstance(category, discord.CategoryChannel) else None,
        overwrites=overwrites
    )

    db_exec(
        "INSERT INTO tickets(channel_id,guild_id,owner_id,ticket_type,created_at) VALUES(?,?,?,?,?)",
        (channel.id, guild.id, interaction.user.id, ticket_type, now_ts())
    )

    view = CloseTicketView()
    await channel.send(
        f"🎫 {interaction.user.mention}\n"
        f"**نوع التكت:** {ticket_type}\n"
        f"اكتب مشكلتك هنا وسيتم خدمتك.\n"
        f"استخدم الزر أدناه للإغلاق.",
        view=view
    )
    await interaction.response.send_message(f"🎫 تم فتح التكت: {channel.mention}", ephemeral=True)
    await send_log(guild, "tickets", "🎫 فتح تكت", f"العضو: {interaction.user.mention}\nالنوع: {ticket_type}")

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="إغلاق", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction, button):
        row = db_exec("SELECT * FROM tickets WHERE channel_id=?", (interaction.channel.id,), True)
        if not row:
            return await interaction.response.send_message("❌ هذا ليس تكت.", ephemeral=True)
        await interaction.response.send_message("🔒 سيتم إغلاق التكت بعد 3 ثوانٍ.")
        await asyncio.sleep(3)
        await send_log(interaction.guild, "tickets", "🔒 إغلاق تكت", f"القناة: {interaction.channel.mention}\nبواسطة: {interaction.user.mention}")
        await interaction.channel.delete()

@bot.hybrid_command(name="تكت", description="إرسال لوحة التكت")
@commands.has_permissions(manage_channels=True)
async def ticket_panel(ctx):
    embed = discord.Embed(
        title="🎫 الدعم",
        description="اختر نوع التكت المناسب لك.",
        color=discord.Color.blurple()
    )
    await ctx.send(embed=embed, view=TicketView())

# ---------------- SETTINGS ----------------

@bot.hybrid_command(name="اعدادات", description="لوحة إعدادات البوت")
@commands.has_permissions(administrator=True)
async def settings(ctx):
    embed = discord.Embed(
        title="⚙️ إعدادات البوت",
        description=(
            "هذه لوحة الإعدادات الأساسية.\n\n"
            "📌 الأنظمة الموجودة داخل الملف:\n"
            "💰 البنك والاقتصاد\n"
            "🎮 الألعاب ونقاطها\n"
            "🆙 XP الشات والفويس\n"
            "🏆 التقرير الأسبوعي\n"
            "👋 الترحيب\n"
            "🎫 التكتات\n"
            "🛡️ الإدارة والسجن\n"
            "🤖 Auto System\n"
            "📜 Logs\n\n"
            "يمكن توسيع الأزرار لإدارة كل قيمة من Discord."
        ),
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

# ---------------- COMMAND ALIASES ----------------

@bot.command(name="اوامر")
async def prefix_help(ctx):
    await ctx.send(
        "📚 **الأوامر الأساسية:**\n"
        "-رصيد | -حساب | -يومي | -اسبوعي | -راتب | -ايداع | -سحب | -تحويل\n"
        "-سرقة | -حظ | -نقاط | -تحويل_نقاط | -توب_النقاط\n"
        "-نرد | -حجرة | -اسرع | -خمن | -xo | -روليت\n"
        "-تحذير | -تايم_اوت | -كيك | -باند | -مسح | -سجن | -فك_السجن\n"
        "-تكت | -اعدادات | -توب | -لفلي"
    )

@bot.command(name="اغلاق")
@commands.has_permissions(manage_channels=True)
async def close_prefix(ctx):
    if ctx.channel.name.startswith("ticket-"):
        await ctx.send("🔒 سيتم إغلاق التكت.")
        await asyncio.sleep(2)
        await ctx.channel.delete()

@bot.command(name="مهامي")
async def admin_tasks(ctx):
    u = get_user(ctx.guild.id, ctx.author.id)
    await ctx.send(
        f"📋 **مهامك الإدارية**\n"
        f"🆙 Admin XP: **{u['admin_xp']}**\n"
        f"⭐ Admin Points: **{u['admin_points']}**\n\n"
        "يمكن إضافة مهام قابلة للتعديل من لوحة الإعدادات."
    )

# ---------------- WEEKLY REPORT ----------------

@tasks.loop(minutes=1)
async def weekly_report_loop():
    now = datetime.now()
    # الخميس الساعة 00:00 - تنفيذ خلال أول دقيقة.
    if now.weekday() != 3 or now.hour != 0 or now.minute != 0:
        return

    for guild in bot.guilds:
        s = get_settings(guild.id)
        channel = guild.get_channel(s["weekly_channel"]) if s["weekly_channel"] else None
        if not channel:
            continue

        chat = db_exec(
            "SELECT user_id,chat_xp FROM users WHERE guild_id=? ORDER BY chat_xp DESC LIMIT 10",
            (guild.id,), True
        )
        voice = db_exec(
            "SELECT user_id,voice_xp FROM users WHERE guild_id=? ORDER BY voice_xp DESC LIMIT 10",
            (guild.id,), True
        )

        chat_text = "\n".join(
            f"{i}. <@{r['user_id']}> — {r['chat_xp']} XP"
            for i,r in enumerate(chat,1)
        ) or "لا يوجد"

        voice_text = "\n".join(
            f"{i}. <@{r['user_id']}> — {r['voice_xp']} XP"
            for i,r in enumerate(voice,1)
        ) or "لا يوجد"

        embed = discord.Embed(
            title="🏆 التقرير الأسبوعي",
            description="إحصائيات الأسبوع الماضي",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="💬 أفضل 10 في الشات", value=chat_text[:1024], inline=False)
        embed.add_field(name="🎙️ أفضل 10 في الفويس", value=voice_text[:1024], inline=False)

        mention = "@everyone" if s["weekly_mention"] else ""
        await channel.send(content=mention, embed=embed)

        # تصفير إحصائيات الأسبوع فقط.
        db_exec(
            "UPDATE users SET weekly_stolen=0, weekly_stolen_amount=0 WHERE guild_id=?",
            (guild.id,)
        )

# ---------------- ERROR HANDLING ----------------

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        return await ctx.send("❌ ما عندك الصلاحية المطلوبة.")
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send("❌ ناقصك اختيار/معلومة مطلوبة.")
    if isinstance(error, commands.BadArgument):
        return await ctx.send("❌ نوع البيانات غير صحيح.")
    print("Command error:", repr(error))

# ---------------- START ----------------

if __name__ == "__main__":
    init_db()
    if not TOKEN:
        print("ERROR: ضع DISCORD_TOKEN في Environment Variables في الاستضافة.")
    else:
        bot.run(TOKEN)
