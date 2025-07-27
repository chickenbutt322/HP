import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
import asyncio
import random
import json
from datetime import datetime, timedelta
import re
import uuid

load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Store active giveaways
active_giveaways = {}

# Store user warnings and punishments
user_warnings = {}  # {user_id: {'warnings': count, 'history': [{'id': str, 'reason': str, 'date': datetime, 'moderator': str}]}}
active_punishments = {}  # {user_id: {'type': 'mute'/'ban', 'until': datetime, 'reason': str}}

# Store user XP and levels
user_levels = {}  # {user_id: {'xp': int, 'level': int, 'last_message': datetime}}

def calculate_xp_for_level(level):
    """Calculate total XP needed to reach a specific level"""
    if level <= 1:
        return 0
    # XP formula: level^2 * 100 + (level * 50)
    return level * level * 100 + (level * 50)

def get_booster_xp_multiplier(member):
    """Get XP multiplier based on booster tier"""
    if not member or not member.premium_since:
        return 1.0

    guild = member.guild
    mega_booster_role = guild.get_role(1397371634012258374)  # Mega Booster (3+ boosts)
    super_booster_role = guild.get_role(1397371603255296181)  # Super Booster (2 boosts)
    server_booster_role = guild.get_role(1397361697324269679)  # Server Booster (1 boost)

    if mega_booster_role and mega_booster_role in member.roles:
        return 1.30  # 30% XP boost
    elif super_booster_role and super_booster_role in member.roles:
        return 1.20  # 20% XP boost
    elif server_booster_role and server_booster_role in member.roles:
        return 1.10  # 10% XP boost
    else:
        return 1.0

def get_level_xp_multiplier(level):
    """Get XP multiplier based on level"""
    if level >= 80:
        return 1.30
    elif level >= 50:
        return 1.20
    elif level >= 35:
        return 1.10
    else:
        return 1.0

def get_total_xp_multiplier(member, level):
    """Get total XP multiplier combining level and booster bonuses"""
    level_multiplier = get_level_xp_multiplier(level)
    booster_multiplier = get_booster_xp_multiplier(member)

    # Combine multipliers (additive bonuses)
    total_bonus = (level_multiplier - 1.0) + (booster_multiplier - 1.0)
    return 1.0 + total_bonus

def get_giveaway_entry_multiplier(member):
    """Get giveaway entry multiplier based on booster tier"""
    if not member or not member.premium_since:
        return 1

    guild = member.guild
    mega_booster_role = guild.get_role(1397371634012258374)  # Mega Booster (3+ boosts)
    super_booster_role = guild.get_role(1397371603255296181)  # Super Booster (2 boosts)
    server_booster_role = guild.get_role(1397361697324269679)  # Server Booster (1 boost)

    if mega_booster_role and mega_booster_role in member.roles:
        return 7  # 7x giveaway entries
    elif super_booster_role and super_booster_role in member.roles:
        return 5  # 5x giveaway entries
    elif server_booster_role and server_booster_role in member.roles:
        return 3  # 3x giveaway entries
    else:
        return 1

def add_xp(user_id, base_xp, member):
    """Add XP to a user with level and booster multipliers"""
    if user_id not in user_levels:
        user_levels[user_id] = {'xp': 0, 'level': 1, 'last_message': datetime.utcnow()}

    current_level = user_levels[user_id]['level']
    multiplier = get_total_xp_multiplier(member, current_level)
    xp_gained = int(base_xp * multiplier)

    user_levels[user_id]['xp'] += xp_gained
    user_levels[user_id]['last_message'] = datetime.utcnow()

    # Check for level up
    current_xp = user_levels[user_id]['xp']
    new_level = current_level

    while current_xp >= calculate_xp_for_level(new_level + 1):
        new_level += 1

    if new_level > current_level:
        user_levels[user_id]['level'] = new_level
        return new_level, xp_gained  # Return new level and XP gained

    return None, xp_gained  # No level up, just return XP gained

def get_level_progress(user_id, member):
    """Get user's level progress information, including booster bonuses"""
    if user_id not in user_levels:
        return {'level': 1, 'current_xp': 0, 'xp_for_current': 0, 'xp_for_next': calculate_xp_for_level(2), 'progress_percent': 0, 'multiplier': 1.0, 'booster_multiplier': 1.0}

    user_data = user_levels[user_id]
    level = user_data['level']
    current_xp = user_data['xp']

    xp_for_current = calculate_xp_for_level(level)
    xp_for_next = calculate_xp_for_level(level + 1)

    xp_in_level = current_xp - xp_for_current
    xp_needed_for_level = xp_for_next - xp_for_current

    progress_percent = (xp_in_level / xp_needed_for_level) * 100 if xp_needed_for_level > 0 else 100
    
    total_multiplier = get_total_xp_multiplier(member, level)
    booster_multiplier = get_booster_xp_multiplier(member)

    return {
        'level': level,
        'current_xp': current_xp,
        'xp_for_current': xp_for_current,
        'xp_for_next': xp_for_next,
        'xp_in_level': xp_in_level,
        'xp_needed_for_level': xp_needed_for_level,
        'progress_percent': min(progress_percent, 100),
        'multiplier': total_multiplier,
        'booster_multiplier': booster_multiplier
    }

app = Flask('')


@app.route('/')
def home():
    return "Bot is alive!"


def run():
    app.run(host='0.0.0.0', port=8080)


def keep_alive():
    t = Thread(target=run)
    t.start()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")

        # Print all registered commands for debugging
        for command in bot.tree.get_commands():
            print(f"- {command.name}: {command.description}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.tree.command(name="sync", description="Manually sync slash commands (Admin only)")
async def sync_commands(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You need administrator permission to sync commands!", ephemeral=True)
        return

    try:
        synced = await bot.tree.sync()
        await interaction.response.send_message(f"✅ Successfully synced {len(synced)} commands!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to sync commands: {str(e)}", ephemeral=True)

@bot.tree.command(name="listcommands", description="List all registered slash commands")
async def list_commands(interaction: discord.Interaction):
    commands = bot.tree.get_commands()

    if not commands:
        await interaction.response.send_message("❌ No commands found!", ephemeral=True)
        return

    command_list = []
    for cmd in commands:
        command_list.append(f"**/{cmd.name}** - {cmd.description}")

    embed = discord.Embed(
        title="🤖 Registered Slash Commands",
        description="\n".join(command_list),
        color=0x00ff00
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


def parse_duration(duration_str):
    """Parse duration string like '5 hours', '2 days', '30 minutes'"""
    duration_str = duration_str.lower()

    # Extract number and unit
    match = re.match(r'(\d+)\s*(second|minute|hour|day|week|month)s?', duration_str)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)

    if unit == 'second':
        return timedelta(seconds=amount)
    elif unit == 'minute':
        return timedelta(minutes=amount)
    elif unit == 'hour':
        return timedelta(hours=amount)
    elif unit == 'day':
        return timedelta(days=amount)
    elif unit == 'week':
        return timedelta(weeks=amount)
    elif unit == 'month':
        return timedelta(days=amount * 30)

    return None

@bot.tree.command(name="giveaway", description="Create a giveaway with customizable options")
@app_commands.describe(
    channel="The channel to post the giveaway in",
    prize="The prize name/description",
    duration="Duration (e.g., '5 hours', '2 days', '30 minutes')",
    winners="Number of winners (default: 1)",
    host="Custom host mention (optional)",
    image="Image URL for the giveaway (optional)",
    thumbnail="Thumbnail URL for the giveaway (optional)",
    color="Hex color code (e.g., #ff0000) (optional)",
    required_role="Role required to enter (optional)",
    blacklisted_role="Role that cannot enter (optional)",
    rig_winner="User to guarantee wins (optional - keeps it secret!)"
)
async def giveaway_slash(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    prize: str,
    duration: str,
    winners: int = 1,
    host: discord.Member = None,
    image: str = None,
    thumbnail: str = None,
    color: str = None,
    required_role: discord.Role = None,
    blacklisted_role: discord.Role = None,
    rig_winner: discord.Member = None
):
    # Parse duration
    parsed_duration = parse_duration(duration)
    if not parsed_duration:
        await interaction.response.send_message("❌ Invalid duration format! Use format like '5 hours', '2 days', '30 minutes'", ephemeral=True)
        return

    # Validate winners count
    if winners < 1 or winners > 50:
        await interaction.response.send_message("❌ Winners must be between 1 and 50!", ephemeral=True)
        return

    # Set defaults
    host_mention = host.mention if host else interaction.user.mention
    embed_color = 0x00ff00  # Default green

    # Parse custom color if provided
    if color:
        try:
            if color.startswith('#'):
                embed_color = int(color[1:], 16)
            else:
                embed_color = int(color, 16)
        except ValueError:
            await interaction.response.send_message("❌ Invalid color format! Use hex format like #ff0000", ephemeral=True)
            return

    # Calculate end time
    end_time = datetime.utcnow() + parsed_duration

    # Create embed
    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        description=f"**Prize:** {prize}\n"
                   f"**Winners:** {winners}\n"
                   f"**Host:** {host_mention}\n"
                   f"**Ends:** <t:{int(end_time.timestamp())}:R>\n\n"
                   f"React with 🎉 to enter!",
        color=embed_color
    )

    if image:
        embed.set_image(url=image)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    embed.set_footer(text="Giveaway ends at")
    embed.timestamp = end_time

    # Send giveaway message
    try:
        giveaway_msg = await channel.send(embed=embed)
        await giveaway_msg.add_reaction("🎉")
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to send messages in that channel!", ephemeral=True)
        return
    except Exception as e:
        await interaction.response.send_message(f"❌ Error creating giveaway: {str(e)}", ephemeral=True)
        return

    # Store giveaway data
    giveaway_data = {
        'message_id': giveaway_msg.id,
        'channel_id': channel.id,
        'guild_id': interaction.guild.id,
        'prize': prize,
        'winners': winners,
        'host': host_mention,
        'end_time': end_time,
        'entries': [],
        'required_role': required_role.name if required_role else None,
        'blacklisted_role': blacklisted_role.name if blacklisted_role else None,
        'rig_winner': rig_winner.mention if rig_winner else None,
        'ended': False
    }

    active_giveaways[giveaway_msg.id] = giveaway_data

    # Schedule giveaway end
    asyncio.create_task(end_giveaway_after_delay(giveaway_msg.id, parsed_duration.total_seconds()))

    # Send success message (only visible to command user)
    success_msg = f"✅ Giveaway created successfully in {channel.mention}!"

    await interaction.response.send_message(success_msg, ephemeral=True)

async def end_giveaway_after_delay(giveaway_id, delay_seconds):
    """End giveaway after specified delay"""
    await asyncio.sleep(delay_seconds)
    await end_giveaway(giveaway_id)

async def end_giveaway(giveaway_id):
    """End a giveaway and select winners"""
    if giveaway_id not in active_giveaways:
        return

    giveaway = active_giveaways[giveaway_id]
    if giveaway['ended']:
        return

    # Get the message and channel
    channel = bot.get_channel(giveaway['channel_id'])
    if not channel:
        return

    try:
        message = await channel.fetch_message(giveaway['message_id'])
    except discord.NotFound:
        return

    # Get all users who reacted with 🎉
    reaction = discord.utils.get(message.reactions, emoji="🎉")
    if not reaction:
        # No entries
        embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=f"**Prize:** {giveaway['prize']}\n"
                       f"**Winners:** No valid entries!",
            color=0xff0000
        )
        await message.edit(embed=embed)
        giveaway['ended'] = True
        return

    # Get eligible users
    eligible_users = []
    guild = bot.get_guild(giveaway['guild_id'])

    async for user in reaction.users():
        if user.bot:
            continue

        member = guild.get_member(user.id)
        if not member:
            continue

        # Check role requirements
        if giveaway.get('required_role'):
            required_role_name = giveaway['required_role'].replace('@', '').replace('<', '').replace('>', '')
            required_role = discord.utils.get(guild.roles, name=required_role_name)
            if required_role and required_role not in member.roles:
                continue

        # Check blacklisted roles
        if giveaway.get('blacklisted_role'):
            blacklisted_role_name = giveaway['blacklisted_role'].replace('@', '').replace('<', '').replace('>', '')
            blacklisted_role = discord.utils.get(guild.roles, name=blacklisted_role_name)
            if blacklisted_role and blacklisted_role in member.roles:
                continue

        # Apply giveaway entry multiplier
        entry_multiplier = get_giveaway_entry_multiplier(member)
        eligible_users.extend([member] * entry_multiplier)

    if not eligible_users:
        embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=f"**Prize:** {giveaway['prize']}\n"
                       f"**Winners:** No eligible entries!",
            color=0xff0000
        )
        await message.edit(embed=embed)
        giveaway['ended'] = True
        return

    # Select winners
    winners = []

    # Check if there's a rigged winner
    if giveaway.get('rig_winner'):
        rig_mention = giveaway['rig_winner']
        # Extract user ID from mention
        if rig_mention.startswith('<@') and rig_mention.endswith('>'):
            user_id = int(rig_mention[2:-1].replace('!', ''))
            rigged_member = guild.get_member(user_id)
            if rigged_member and rigged_member in eligible_users:
                winners.append(rigged_member)
                eligible_users.remove(rigged_member)

    # Select remaining winners randomly
    remaining_winners = min(giveaway['winners'] - len(winners), len(eligible_users))
    if remaining_winners > 0:
        winners.extend(random.sample(eligible_users, remaining_winners))

    # Create winner announcement
    if winners:
        winner_mentions = [winner.mention for winner in winners]
        embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=f"**Prize:** {giveaway['prize']}\n"
                       f"**Winners:** {', '.join(winner_mentions)}\n"
                       f"**Host:** {giveaway['host']}\n\n"
                       f"Congratulations! 🎊",
            color=0x00ff00
        )

        # Send congratulations message
        congrats_msg = f"🎉 Congratulations {', '.join(winner_mentions)}! You won **{giveaway['prize']}**!\n"
        congrats_msg += f"Contact {giveaway['host']} to claim your prize!"

        await channel.send(congrats_msg)

        # DM winners
        for winner in winners:
            try:
                dm_embed = discord.Embed(
                    title="🎉 You Won a Giveaway! 🎉",
                    description=f"**Prize:** {giveaway['prize']}\n"
                               f"**Server:** {guild.name}\n\n"
                               f"Contact {giveaway['host']} to claim your prize!",
                    color=0x00ff00
                )
                await winner.send(embed=dm_embed)
            except discord.Forbidden:
                pass  # User has DMs disabled
    else:
        embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=f"**Prize:** {giveaway['prize']}\n"
                       f"**Winners:** Not enough eligible entries!",
            color=0xff0000
        )

    await message.edit(embed=embed)
    giveaway['ended'] = True

@bot.tree.command(name="reroll", description="Reroll a giveaway to select new winners")
@app_commands.describe(message_id="The message ID of the giveaway to reroll")
async def reroll_giveaway(interaction: discord.Interaction, message_id: str):
    try:
        msg_id = int(message_id)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID format!", ephemeral=True)
        return

    if msg_id not in active_giveaways:
        await interaction.response.send_message("❌ Giveaway not found!", ephemeral=True)
        return

    giveaway = active_giveaways[msg_id]
    if not giveaway['ended']:
        await interaction.response.send_message("❌ Giveaway hasn't ended yet!", ephemeral=True)
        return

    # Reset the giveaway state and reroll
    giveaway['ended'] = False
    await end_giveaway(msg_id)
    await interaction.response.send_message("✅ Giveaway rerolled!", ephemeral=True)

@bot.tree.command(name="end-giveaway", description="Force end a giveaway early")
@app_commands.describe(message_id="The message ID of the giveaway to end")
async def force_end_giveaway(interaction: discord.Interaction, message_id: str):
    try:
        msg_id = int(message_id)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID format!", ephemeral=True)
        return

    if msg_id not in active_giveaways:
        await interaction.response.send_message("❌ Giveaway not found!", ephemeral=True)
        return

    giveaway = active_giveaways[msg_id]
    if giveaway['ended']:
        await interaction.response.send_message("❌ Giveaway already ended!", ephemeral=True)
        return

    await end_giveaway(msg_id)
    await interaction.response.send_message("✅ Giveaway ended!", ephemeral=True)

# Warning System Commands
@bot.tree.command(name="warn", description="Give a warning to a user")
@app_commands.describe(
    user="The user to warn",
    reason="Reason for the warning"
)
async def warn_user(interaction: discord.Interaction, user: discord.Member, reason: str):
    # Check if user has manage messages permission
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ You don't have permission to warn users!", ephemeral=True)
        return

    # Can't warn yourself or bots
    if user == interaction.user:
        await interaction.response.send_message("❌ You can't warn yourself!", ephemeral=True)
        return

    if user.bot:
        await interaction.response.send_message("❌ You can't warn bots!", ephemeral=True)
        return

    # Initialize user warnings if not exists
    if user.id not in user_warnings:
        user_warnings[user.id] = {'warnings': 0, 'history': []}

    # Generate unique warning ID
    warning_id = str(uuid.uuid4())[:8]  # Short 8-character ID

    # Add warning
    user_warnings[user.id]['warnings'] += 1
    user_warnings[user.id]['history'].append({
        'id': warning_id,
        'reason': reason,
        'date': datetime.utcnow(),
        'moderator': interaction.user.name
    })

    warning_count = user_warnings[user.id]['warnings']

    # Create warning embed
    embed = discord.Embed(
        title="⚠️ Warning Issued",
        description=f"**User:** {user.mention}\n"
                   f"**Warning ID:** `{warning_id}`\n"
                   f"**Reason:** {reason}\n"
                   f"**Total Warnings:** {warning_count}\n"
                   f"**Moderator:** {interaction.user.mention}",
        color=0xffaa00
    )

    # Check for automatic punishment
    punishment_message = ""
    if warning_count >= 40:
        # Permanent ban
        try:
            await user.ban(reason=f"Automatic ban - {warning_count} warnings")
            punishment_message = "\n🔨 **PERMANENT BAN** applied automatically!"
        except discord.Forbidden:
            punishment_message = "\n❌ Failed to ban user (insufficient permissions)"
    elif warning_count >= 30:
        # 30 day temp ban
        try:
            await user.ban(reason=f"Automatic 30-day ban - {warning_count} warnings")
            active_punishments[user.id] = {
                'type': 'tempban',
                'until': datetime.utcnow() + timedelta(days=30),
                'reason': f'30-day ban for {warning_count} warnings'
            }
            punishment_message = "\n🔨 **30-DAY BAN** applied automatically!"
            # Schedule unban
            asyncio.create_task(schedule_unban(user.id, interaction.guild.id, 30 * 24 * 3600))
        except discord.Forbidden:
            punishment_message = "\n❌ Failed to ban user (insufficient permissions)"
    elif warning_count >= 25:
        # 30 day mute
        await apply_mute(user, interaction.guild, 30, f"{warning_count} warnings")
        punishment_message = "\n🔇 **30-DAY MUTE** applied automatically!"
    elif warning_count >= 20:
        # 10 day mute
        await apply_mute(user, interaction.guild, 10, f"{warning_count} warnings")
        punishment_message = "\n🔇 **10-DAY MUTE** applied automatically!"
    elif warning_count >= 15:
        # 5 day mute
        await apply_mute(user, interaction.guild, 5, f"{warning_count} warnings")
        punishment_message = "\n🔇 **5-DAY MUTE** applied automatically!"
    elif warning_count >= 10:
        # 3 day mute
        await apply_mute(user, interaction.guild, 3, f"{warning_count} warnings")
        punishment_message = "\n🔇 **3-DAY MUTE** applied automatically!"
    elif warning_count >= 5:
        # 1 day mute
        await apply_mute(user, interaction.guild, 1, f"{warning_count} warnings")
        punishment_message = "\n🔇 **1-DAY MUTE** applied automatically!"

    embed.description += punishment_message

    # Send warning DM to user
    try:
        dm_embed = discord.Embed(
            title="⚠️ You Received a Warning",
            description=f"**Server:** {interaction.guild.name}\n"
                       f"**Reason:** {reason}\n"
                       f"**Total Warnings:** {warning_count}\n"
                       f"**Moderator:** {interaction.user.name}",
            color=0xffaa00
        )
        if punishment_message:
            dm_embed.description += punishment_message
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        pass  # User has DMs disabled

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="warnings", description="Check warnings for a user")
@app_commands.describe(user="The user to check warnings for (optional - defaults to yourself)")
async def check_warnings(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user

    # Only allow checking other users if you have manage messages permission
    if user and user != interaction.user and not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ You can only check your own warnings!", ephemeral=True)
        return

    if target_user.id not in user_warnings or user_warnings[target_user.id]['warnings'] == 0:
        embed = discord.Embed(
            title="✅ Clean Record",
            description=f"{target_user.mention} has no warnings!",
            color=0x00ff00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    warning_data = user_warnings[target_user.id]
    warning_count = warning_data['warnings']

    embed = discord.Embed(
        title="⚠️ Warning History",
        description=f"**User:** {target_user.mention}\n**Total Warnings:** {warning_count}",
        color=0xffaa00
    )

    # Show recent warnings (last 5)
    recent_warnings = warning_data['history'][-5:]
    if recent_warnings:
        warning_list = ""
        for warning in recent_warnings:
            warning_list += f"**ID:** `{warning['id']}` - **{warning['reason']}**\n"
            warning_list += f"   *By {warning['moderator']} on {warning['date'].strftime('%Y-%m-%d')}*\n\n"

        embed.add_field(name="Recent Warnings", value=warning_list, inline=False)

    # Show next punishment
    next_punishment = ""
    if warning_count >= 30:
        next_punishment = "Next: **Permanent Ban** (40 warnings)"
    elif warning_count >= 25:
        next_punishment = "Next: **30-day Ban** (30 warnings)"
    elif warning_count >= 20:
        next_punishment = "Next: **30-day Mute** (25 warnings)"
    elif warning_count >= 15:
        next_punishment = "Next: **10-day Mute** (20 warnings)"
    elif warning_count >= 10:
        next_punishment = "Next: **5-day Mute** (15 warnings)"
    elif warning_count >= 5:
        next_punishment = "Next: **3-day Mute** (10 warnings)"
    else:
        next_punishment = "Next: **1-day Mute** (5 warnings)"

    embed.add_field(name="Punishment Ladder", value=next_punishment, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="clearwarnings", description="Clear all warnings for a user")
@app_commands.describe(user="The user to clear warnings for")
async def clear_warnings(interaction: discord.Interaction, user: discord.Member):
    # Check if user has administrator permission
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You need administrator permission to clear warnings!", ephemeral=True)
        return

    if user.id not in user_warnings or user_warnings[user.id]['warnings'] == 0:
        await interaction.response.send_message(f"❌ {user.mention} has no warnings to clear!", ephemeral=True)
        return

    old_count = user_warnings[user.id]['warnings']
    user_warnings[user.id] = {'warnings': 0, 'history': []}

    embed = discord.Embed(
        title="✅ Warnings Cleared",
        description=f"**User:** {user.mention}\n"
                   f"**Previous Warnings:** {old_count}\n"
                   f"**Cleared by:** {interaction.user.mention}",
        color=0x00ff00
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="removewarning", description="Remove a specific warning by ID")
@app_commands.describe(
    user="The user to remove the warning from",
    warning_id="The warning ID to remove"
)
async def remove_warning(interaction: discord.Interaction, user: discord.Member, warning_id: str):
    # Check if user has manage messages permission
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ You don't have permission to remove warnings!", ephemeral=True)
        return

    if user.id not in user_warnings or user_warnings[user.id]['warnings'] == 0:
        await interaction.response.send_message(f"❌ {user.mention} has no warnings!", ephemeral=True)
        return

    # Find and remove the warning
    warning_found = False
    removed_warning = None

    for i, warning in enumerate(user_warnings[user.id]['history']):
        if warning['id'] == warning_id:
            removed_warning = user_warnings[user.id]['history'].pop(i)
            user_warnings[user.id]['warnings'] -= 1
            warning_found = True
            break

    if not warning_found:
        await interaction.response.send_message(f"❌ Warning ID `{warning_id}` not found for {user.mention}!", ephemeral=True)
        return

    embed = discord.Embed(
        title="✅ Warning Removed",
        description=f"**User:** {user.mention}\n"
                   f"**Warning ID:** `{warning_id}`\n"
                   f"**Removed Warning:** {removed_warning['reason']}\n"
                   f"**Original Moderator:** {removed_warning['moderator']}\n"
                   f"**Remaining Warnings:** {user_warnings[user.id]['warnings']}\n"
                   f"**Removed by:** {interaction.user.mention}",
        color=0x00ff00
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="unmute", description="Remove mute from a user")
@app_commands.describe(user="The user to unmute")
async def unmute_user(interaction: discord.Interaction, user: discord.Member):
    # Check if user has manage messages permission
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ You don't have permission to unmute users!", ephemeral=True)
        return

    # Get muted role
    muted_role = interaction.guild.get_role(1396988857224003595)

    if not muted_role:
        await interaction.response.send_message("❌ Muted role not found!", ephemeral=True)
        return

    if muted_role not in user.roles:
        await interaction.response.send_message(f"❌ {user.mention} is not muted!", ephemeral=True)
        return

    try:
        await user.remove_roles(muted_role, reason=f"Manual unmute by {interaction.user.name}")

        # Remove from active punishments
        if user.id in active_punishments and active_punishments[user.id]['type'] == 'mute':
            del active_punishments[user.id]

        embed = discord.Embed(
            title="🔊 User Unmuted",
            description=f"**User:** {user.mention}\n"
                       f"**Unmuted by:** {interaction.user.mention}",
            color=0x00ff00
        )

        await interaction.response.send_message(embed=embed)

        # Send DM to user
        try:
            dm_embed = discord.Embed(
                title="🔊 You've Been Unmuted",
                description=f"You have been unmuted in **{interaction.guild.name}** by {interaction.user.mention}.",
                color=0x00ff00
            )
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to remove the muted role!", ephemeral=True)

@bot.tree.command(name="unban", description="Unban a user")
@app_commands.describe(user_id="The user ID to unban")
async def unban_user(interaction: discord.Interaction, user_id: str):
    # Check if user has ban members permission
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("❌ You don't have permission to unban users!", ephemeral=True)
        return

    try:
        user_id_int = int(user_id)
    except ValueError:
        await interaction.response.send_message("❌ Invalid user ID format!", ephemeral=True)
        return

    try:
        # Check if user is actually banned
        ban_entry = await interaction.guild.fetch_ban(discord.Object(id=user_id_int))
        user = ban_entry.user

        await interaction.guild.unban(user, reason=f"Manual unban by {interaction.user.name}")

        # Remove from active punishments
        if user_id_int in active_punishments:
            del active_punishments[user_id_int]

        embed = discord.Embed(
            title="🔓 User Unbanned",
            description=f"**User:** {user.name}#{user.discriminator}\n"
                       f"**User ID:** {user_id}\n"
                       f"**Unbanned by:** {interaction.user.mention}",
            color=0x00ff00
        )

        await interaction.response.send_message(embed=embed)

        # Try to send DM to unbanned user
        try:
            dm_embed = discord.Embed(
                title="🔓 You've Been Unbanned",
                description=f"You have been unbanned from **{interaction.guild.name}** by {interaction.user.mention}.\n"
                           f"You can now rejoin the server!",
                color=0x00ff00
            )
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    except discord.NotFound:
        await interaction.response.send_message(f"❌ User ID `{user_id}` is not banned from this server!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to unban users!", ephemeral=True)

async def apply_mute(user: discord.Member, guild: discord.Guild, days: int, reason: str):
    """Apply mute to a user for specified days"""
    # Get existing muted role by ID
    muted_role = guild.get_role(1396988857224003595)

    if not muted_role:
        return False  # Muted role doesn't exist

    try:
        await user.add_roles(muted_role, reason=reason)

        # Store mute data
        until_date = datetime.utcnow() + timedelta(days=days)
        active_punishments[user.id] = {
            'type': 'mute',
            'until': until_date,
            'reason': reason
        }

        # Schedule unmute
        asyncio.create_task(schedule_unmute(user.id, guild.id, days * 24 * 3600))
        return True
    except discord.Forbidden:
        return False

async def schedule_unmute(user_id: int, guild_id: int, delay_seconds: float):
    """Schedule automatic unmute"""
    await asyncio.sleep(delay_seconds)

    guild = bot.get_guild(guild_id)
    if not guild:
        return

    user = guild.get_member(user_id)
    if not user:
        return

    muted_role = guild.get_role(1396988857224003595)
    if muted_role and muted_role in user.roles:
        try:
            await user.remove_roles(muted_role, reason="Automatic unmute - punishment expired")

            # Remove from active punishments
            if user_id in active_punishments:
                del active_punishments[user_id]

            # Send DM notification
            try:
                embed = discord.Embed(
                    title="🔊 Mute Expired",
                    description=f"Your mute in **{guild.name}** has expired. You can now speak again!",
                    color=0x00ff00
                )
                await user.send(embed=embed)
            except discord.Forbidden:
                pass
        except discord.Forbidden:
            pass

async def schedule_unban(user_id: int, guild_id: int, delay_seconds: float):
    """Schedule automatic unban"""
    await asyncio.sleep(delay_seconds)

    guild = bot.get_guild(guild_id)
    if not guild:
        return

    try:
        await guild.unban(discord.Object(id=user_id), reason="Automatic unban - temp ban expired")

        # Remove from active punishments
        if user_id in active_punishments:
            del active_punishments[user_id]
    except discord.Forbidden:
        pass
    except discord.NotFound:
        pass  # User wasn't banned

@bot.event
async def on_message(message):
    # Don't give XP to bots or in DMs
    if message.author.bot or not message.guild:
        return

    # Check for spam (prevent XP farming)
    user_id = message.author.id
    if user_id in user_levels:
        last_message = user_levels[user_id]['last_message']
        if (datetime.utcnow() - last_message).total_seconds() < 10:
            return  # Must wait 10 seconds between XP gains

    # Base XP gain (15-25 XP per message)
    base_xp = random.randint(15, 25)

    # Bonus XP for longer messages
    if len(message.content) > 50:
        base_xp += random.randint(5, 10)
    if len(message.content) > 100:
        base_xp += random.randint(5, 15)

    # Add XP and check for level up
    level_up, xp_gained = add_xp(user_id, base_xp, message.author)

    if level_up:
        # User leveled up!
        progress = get_level_progress(user_id, message.author)
        embed = discord.Embed(
            title="🎉 LEVEL UP! 🎉",
            description=f"**{message.author.mention} reached Level {level_up}!**",
            color=0xffd700
        )

        booster_info = ""
        if progress['booster_multiplier'] > 1.0:
            booster_bonus = int((progress['booster_multiplier'] - 1.0) * 100)
            embed.add_field(name="💎 Booster Bonus", 
                           value=f"**+{booster_bonus}% XP** from boosting!",
                           inline=True)

        embed.add_field(name="📊 Stats", 
                       value=f"**Total XP:** {progress['current_xp']:,}\n"
                             f"**XP Multiplier:** {progress['multiplier']:.2f}x",
                       inline=True)

        # Check for milestone rewards
        milestone_message = ""
        if level_up == 35:
            milestone_message = "\n🌟 **MILESTONE REACHED!** You now earn **1.10x XP**!"
        elif level_up == 50:
            milestone_message = "\n🌟 **MILESTONE REACHED!** You now earn **1.20x XP**!"
        elif level_up == 80:
            milestone_message = "\n🌟 **MILESTONE REACHED!** You now earn **1.30x XP**!"

        if milestone_message:
            embed.description += milestone_message

        embed.set_thumbnail(url=message.author.avatar.url if message.author.avatar else message.author.default_avatar.url)

        try:
            await message.channel.send(embed=embed)
        except discord.Forbidden:
            pass

@bot.event
async def on_member_update(before, after):
    # Check if someone just started boosting
    if before.premium_since is None and after.premium_since is not None:
        guild = after.guild
        server_booster_role = guild.get_role(1397361697324269679)

        # Give Server Booster role if they don't have it
        if server_booster_role and server_booster_role not in after.roles:
            await after.add_roles(server_booster_role)
            print(f"Added Server Booster role to {after.name}")

    # Check if someone stopped boosting
    elif before.premium_since is not None and after.premium_since is None:
        guild = after.guild
        # Get all booster roles
        server_booster_role = guild.get_role(1397361697324269679)
        super_booster_role = guild.get_role(1397371603255296181)
        mega_booster_role = guild.get_role(1397371634012258374)

        booster_roles = [server_booster_role, super_booster_role, mega_booster_role]

        # Remove all booster roles they have
        roles_to_remove = [role for role in booster_roles if role and role in after.roles]
        if roles_to_remove:
            await after.remove_roles(*roles_to_remove)
            print(f"Removed booster roles from {after.name}: {[role.name for role in roles_to_remove]}")


# Additional fun features
import time

# Storage for polls and reminders
active_polls = {}
user_reminders = {}

@bot.tree.command(name="userinfo", description="Get detailed information about a user")
@app_commands.describe(user="The user to get info about (optional - defaults to yourself)")
async def user_info(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user

    embed = discord.Embed(
        title=f"👤 User Info: {target_user.display_name}",
        color=target_user.color if target_user.color.value != 0 else 0x7289da
    )

    embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else target_user.default_avatar.url)

    # Basic info
    embed.add_field(name="📛 Username", value=f"{target_user.name}#{target_user.discriminator}", inline=True)
    embed.add_field(name="🆔 User ID", value=target_user.id, inline=True)
    embed.add_field(name="🤖 Bot", value="Yes" if target_user.bot else "No", inline=True)

    # Dates
    embed.add_field(name="📅 Account Created", value=f"<t:{int(target_user.created_at.timestamp())}:F>", inline=False)
    embed.add_field(name="📥 Joined Server", value=f"<t:{int(target_user.joined_at.timestamp())}:F>", inline=False)

    # Roles (top 10)
    if target_user.roles[1:]:  # Exclude @everyone
        roles = [role.mention for role in sorted(target_user.roles[1:], key=lambda r: r.position, reverse=True)]
        role_text = ", ".join(roles[:10])
        if len(roles) > 10:
            role_text += f" and {len(roles) - 10} more..."
        embed.add_field(name=f"🎭 Roles ({len(roles)})", value=role_text, inline=False)

    # Boost info
    if target_user.premium_since:
        embed.add_field(name="💎 Server Booster", value=f"Since <t:{int(target_user.premium_since.timestamp())}:F>", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="serverinfo", description="Get information about this server")
async def server_info(interaction: discord.Interaction):
    guild = interaction.guild

    embed = discord.Embed(
        title=f"🏰 Server Info: {guild.name}",
        color=0x7289da
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    # Basic info
    embed.add_field(name="👑 Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
    embed.add_field(name="🆔 Server ID", value=guild.id, inline=True)
    embed.add_field(name="📅 Created", value=f"<t:{int(guild.created_at.timestamp())}:F>", inline=True)

    # Counts
    embed.add_field(name="👥 Members", value=guild.member_count, inline=True)
    embed.add_field(name="🎭 Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="📝 Channels", value=len(guild.channels), inline=True)

    # Boosts
    embed.add_field(name="💎 Boost Level", value=f"Level {guild.premium_tier}", inline=True)
    embed.add_field(name="🚀 Boosts", value=guild.premium_subscription_count, inline=True)
    embed.add_field(name="😊 Emojis", value=len(guild.emojis), inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="quote", description="Get a random inspirational quote")
async def random_quote(interaction: discord.Interaction):
    quotes = [
        "The only way to do great work is to love what you do. - Steve Jobs",
        "Innovation distinguishes between a leader and a follower. - Steve Jobs",
        "Life is what happens to you while you're busy making other plans. - John Lennon",
        "The future belongs to those who believe in the beauty of their dreams. - Eleanor Roosevelt",
        "It is during our darkest moments that we must focus to see the light. - Aristotle",
        "The only impossible journey is the one you never begin. - Tony Robbins",
        "Success is not final, failure is not fatal: it is the courage to continue that counts. - Winston Churchill",
        "The way to get started is to quit talking and begin doing. - Walt Disney",
        "Don't let yesterday take up too much of today. - Will Rogers",
        "You learn more from failure than from success. Don't let it stop you. Failure builds character. - Unknown",
        "It's not whether you get knocked down, it's whether you get up. - Vince Lombardi",
        "If you are working on something that you really care about, you don't have to be pushed. The vision pulls you. - Steve Jobs",
        "People who are crazy enough to think they can change the world, are the ones who do. - Rob Siltanen",
        "We don't make mistakes, just happy little accidents. - Bob Ross"
    ]

    quote = random.choice(quotes)

    embed = discord.Embed(
        title="💭 Inspirational Quote",
        description=f"*{quote}*",
        color=0x00ff00
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rps", description="Play Rock Paper Scissors against the bot!")
@app_commands.describe(choice="Your choice: rock, paper, or scissors")
@app_commands.choices(choice=[
    app_commands.Choice(name="🪨 Rock", value="rock"),
    app_commands.Choice(name="📄 Paper", value="paper"),
    app_commands.Choice(name="✂️ Scissors", value="scissors")
])
async def rock_paper_scissors(interaction: discord.Interaction, choice: app_commands.Choice[str]):
    user_choice = choice.value
    bot_choice = random.choice(["rock", "paper", "scissors"])

    choices_emoji = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}

    # Determine winner
    if user_choice == bot_choice:
        result = "🤝 It's a tie!"
        color = 0xffff00
    elif (user_choice == "rock" and bot_choice == "scissors") or \
         (user_choice == "paper" and bot_choice == "rock") or \
         (user_choice == "scissors" and bot_choice == "paper"):
        result = "🎉 You win!"
        color = 0x00ff00
    else:
        result = "😔 I win!"
        color = 0xff0000

    embed = discord.Embed(
        title="🎮 Rock Paper Scissors",
        description=f"**Your choice:** {choices_emoji[user_choice]} {user_choice.title()}\n"
                   f"**My choice:** {choices_emoji[bot_choice]} {bot_choice.title()}\n\n"
                   f"**Result:** {result}",
        color=color
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="poll", description="Create a poll with up to 10 options")
@app_commands.describe(
    question="The poll question",
    option1="First option", option2="Second option", option3="Third option (optional)",
    option4="Fourth option (optional)", option5="Fifth option (optional)",
    option6="Sixth option (optional)", option7="Seventh option (optional)",
    option8="Eighth option (optional)", option9="Ninth option (optional)",
    option10="Tenth option (optional)"
)
async def create_poll(interaction: discord.Interaction, question: str, option1: str, option2: str,
                     option3: str = None, option4: str = None, option5: str = None,
                     option6: str = None, option7: str = None, option8: str = None,
                     option9: str = None, option10: str = None):

    options = [option1, option2, option3, option4, option5, option6, option7, option8, option9, option10]
    options = [opt for opt in options if opt is not None]

    if len(options) < 2:
        await interaction.response.send_message("❌ You need at least 2 options for a poll!", ephemeral=True)
        return

    # Number emojis for reactions
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    embed = discord.Embed(
        title="📊 Poll",
        description=f"**{question}**\n\n" + "\n".join([f"{number_emojis[i]} {option}" for i, option in enumerate(options)]),
        color=0x3498db
    )

    embed.set_footer(text=f"Poll created by {interaction.user.display_name}")

    poll_message = await interaction.response.send_message(embed=embed)
    poll_message = await interaction.original_response()

    # Add reactions
    for i in range(len(options)):
        await poll_message.add_reaction(number_emojis[i])

@bot.tree.command(name="remind", description="Set a reminder for yourself")
@app_commands.describe(
    time="Time until reminder (e.g., '5 minutes', '2 hours', '1 day')",
    message="What to remind you about"
)
async def set_reminder(interaction: discord.Interaction, time: str, message: str):
    duration = parse_duration(time)
    if not duration:
        await interaction.response.send_message("❌ Invalid time format! Use format like '5 minutes', '2 hours', '1 day'", ephemeral=True)
        return

    if duration.total_seconds() > 7 * 24 * 3600:  # Max 7 days
        await interaction.response.send_message("❌ Reminders can't be longer than 7 days!", ephemeral=True)
        return

    reminder_time = datetime.utcnow() + duration

    # Store reminder
    if interaction.user.id not in user_reminders:
        user_reminders[interaction.user.id] = []

    reminder_data = {
        'message': message,
        'time': reminder_time,
        'channel_id': interaction.channel.id
    }

    user_reminders[interaction.user.id].append(reminder_data)

    embed = discord.Embed(
        title="⏰ Reminder Set",
        description=f"I'll remind you about: **{message}**\n"
                   f"Time: <t:{int(reminder_time.timestamp())}:F>",
        color=0x00ff00
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

    # Schedule reminder
    asyncio.create_task(send_reminder(interaction.user.id, reminder_data, duration.total_seconds()))

async def send_reminder(user_id: int, reminder_data: dict, delay_seconds: float):
    """Send reminder after delay"""
    await asyncio.sleep(delay_seconds)

    user = bot.get_user(user_id)
    channel = bot.get_channel(reminder_data['channel_id'])

    if user and channel:
        embed = discord.Embed(
            title="⏰ Reminder",
            description=f"**{reminder_data['message']}**",
            color=0xff9900
        )

        try:
            await channel.send(f"{user.mention}", embed=embed)
        except discord.Forbidden:
            # Try DM if can't send in channel
            try:
                await user.send(embed=embed)
            except discord.Forbidden:
                pass

    # Remove from reminders list
    if user_id in user_reminders:
        user_reminders[user_id] = [r for r in user_reminders[user_id] if r != reminder_data]

@bot.tree.command(name="8ball", description="Ask the magic 8-ball a question")
@app_commands.describe(question="Your yes/no question")
async def magic_8ball(interaction: discord.Interaction, question: str):
    responses = [
        "🔮 It is certain",
        "🔮 It is decidedly so",
        "🔮 Without a doubt",
        "🔮 Yes definitely",
        "🔮 You may rely on it",
        "🔮 As I see it, yes",
        "🔮 Most likely",
        "🔮 Outlook good",
        "🔮 Yes",
        "🔮 Signs point to yes",
        "🔮 Reply hazy, try again",
        "🔮 Ask again later",
        "🔮 Better not tell you now",
        "🔮 Cannot predict now",
        "🔮 Concentrate and ask again",
        "🔮 Don't count on it",
        "🔮 My reply is no",
        "🔮 My sources say no",
        "🔮 Outlook not so good",
        "🔮 Very doubtful"
    ]

    response = random.choice(responses)

    embed = discord.Embed(
        title="🎱 Magic 8-Ball",
        description=f"**Question:** {question}\n**Answer:** {response}",
        color=0x800080
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="coinflip", description="Flip a coin")
async def coin_flip(interaction: discord.Interaction):
    result = random.choice(["Heads", "Tails"])
    emoji = "🪙" if result == "Heads" else "🥇"

    embed = discord.Embed(
        title="🪙 Coin Flip",
        description=f"**Result:** {emoji} {result}!",
        color=0xffd700
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="dice", description="Roll a dice")
@app_commands.describe(sides="Number of sides on the dice (default: 6)")
async def roll_dice(interaction: discord.Interaction, sides: int = 6):
    if sides < 2 or sides > 100:
        await interaction.response.send_message("❌ Dice must have between 2 and 100 sides!", ephemeral=True)
        return

    result = random.randint(1, sides)

    embed = discord.Embed(
        title="🎲 Dice Roll",
        description=f"**You rolled a {sides}-sided dice**\n**Result:** {result}",
        color=0xff6b6b
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="level", description="Check your or someone else's level and XP")
@app_commands.describe(user="The user to check (optional - defaults to yourself)")
async def check_level(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user

    if target_user.bot:
        await interaction.response.send_message("❌ Bots don't have levels!", ephemeral=True)
        return

    progress = get_level_progress(target_user.id, target_user)

    # Create progress bar
    progress_bar_length = 20
    filled_length = int(progress_bar_length * progress['progress_percent'] / 100)
    progress_bar = "█" * filled_length + "░" * (progress_bar_length - filled_length)

    embed = discord.Embed(
        title=f"📈 Level Stats for {target_user.display_name}",
        color=target_user.color if target_user.color.value != 0 else 0x7289da
    )

    embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else target_user.default_avatar.url)

    # Show booster info if applicable
    booster_text = ""
    if progress['booster_multiplier'] > 1.0:
        booster_bonus = int((progress['booster_multiplier'] - 1.0) * 100)
        giveaway_multiplier = get_giveaway_entry_multiplier(target_user)

        # Determine booster tier
        guild = target_user.guild
        mega_booster_role = guild.get_role(1397371634012258374)
        super_booster_role = guild.get_role(1397371603255296181)
        server_booster_role = guild.get_role(1397361697324269679)

        tier = ""
        if mega_booster_role and mega_booster_role in target_user.roles:
            tier = "💎 Mega Booster"
        elif super_booster_role and super_booster_role in target_user.roles:
            tier = "💎 Super Booster"
        elif server_booster_role and server_booster_role in target_user.roles:
            tier = "💎 Server Booster"

        booster_text = f"\n{tier}\n🚀 +{booster_bonus}% XP Boost\n🎟️ {giveaway_multiplier}x Giveaway Entries"

    embed.add_field(
        name="📊 Current Level",
        value=f"**Level {progress['level']}**\n"
              f"XP Multiplier: **{progress['multiplier']:.2f}x**{booster_text}",
        inline=True
    )

    embed.add_field(
        name="⭐ Experience Points",
        value=f"**{progress['current_xp']:,}** total XP\n"
              f"**{progress['xp_in_level']:,}** / **{progress['xp_needed_for_level']:,}** XP",
        inline=True
    )

    embed.add_field(
        name="📈 Progress to Next Level",
        value=f"`{progress_bar}` {progress['progress_percent']:.1f}%\n"
              f"**{progress['xp_needed_for_level'] - progress['xp_in_level']:,}** XP needed",
        inline=False
    )

    # Show next milestones
    milestones = []
    current_level = progress['level']
    if current_level < 35:
        milestones.append("Level 35: 10% XP Boost")
    if current_level < 50:
        milestones.append("Level 50: 20% XP Boost")
    if current_level < 80:
        milestones.append("Level 80: 30% XP Boost")

    if milestones:
        embed.add_field(
            name="🎯 Next Milestones",
            value="\n".join(milestones),
            inline=False
        )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="Show the server XP leaderboard")
async def show_leaderboard(interaction: discord.Interaction):
    guild = interaction.guild

    # Get all users with levels in this server
    guild_members = {member.id: member for member in guild.members if not member.bot}

    # Filter user_levels to only include current guild members
    guild_user_levels = {
        user_id: data for user_id, data in user_levels.items() 
        if user_id in guild_members
    }

    if not guild_user_levels:
        embed = discord.Embed(
            title="📊 XP Leaderboard",
            description="No one has gained XP yet! Start chatting to earn XP!",
            color=0x7289da
        )
        await interaction.response.send_message(embed=embed)
        return

    # Sort by XP (descending)
    sorted_users = sorted(guild_user_levels.items(), key=lambda x: x[1]['xp'], reverse=True)

    embed = discord.Embed(
        title="🏆 XP Leaderboard",
        description=f"Top users in {guild.name}",
        color=0xffd700
    )

    # Show top 10 users
    leaderboard_text = ""
    for i, (user_id, data) in enumerate(sorted_users[:10], 1):
        user = guild_members.get(user_id)
        if not user:
            continue

        # Get rank emoji
        if i == 1:
            rank_emoji = "🥇"
        elif i == 2:
            rank_emoji = "🥈"
        elif i == 3:
            rank_emoji = "🥉"
        else:
            rank_emoji = f"`{i:2d}.`"

        ```python
        level = data['level']
        xp = data['xp']
        multiplier = get_total_xp_multiplier(user,level)

        leaderboard_text += f"{rank_emoji} **{user.display_name}**\n"
        leaderboard_text += f"     Level {level} • {xp:,} XP • {multiplier:.2f}x\n\n"

    embed.description += f"\n\n{leaderboard_text}"

    # Show user's rank if not in top 10
    user_rank = None
    for i, (user_id, data) in enumerate(sorted_users, 1):
        if user_id == interaction.user.id:
            user_rank = i
            break

    if user_rank and user_rank > 10:
        user_data = user_levels.get(interaction.user.id, {'level': 1, 'xp': 0})
        embed.add_field(
            name="Your Rank",
            value=f"**#{user_rank}** - Level {user_data['level']} ({user_data['xp']:,} XP)",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="givexp", description="Give XP to a user (Admin only)")
@app_commands.describe(
    user="The user to give XP to",
    amount="Amount of XP to give"
)
async def give_xp(interaction: discord.Interaction, user: discord.Member, amount: int):
    # Check if user has administrator permission
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You need administrator permission to give XP!", ephemeral=True)
        return

    if user.bot:
        await interaction.response.send_message("❌ You can't give XP to bots!", ephemeral=True)
        return

    if amount <= 0 or amount > 100000:
        await interaction.response.send_message("❌ XP amount must be between 1 and 100,000!", ephemeral=True)
        return

    # Add XP (without multiplier for admin commands)
    if user.id not in user_levels:
        user_levels[user.id] = {'xp': 0, 'level': 1, 'last_message': datetime.utcnow()}

    old_level = user_levels[user.id]['level']
    user_levels[user.id]['xp'] += amount
    user_levels[user.id]['last_message'] = datetime.utcnow()

    # Check for level up
    current_xp = user_levels[user.id]['xp']
    new_level = old_level

    while current_xp >= calculate_xp_for_level(new_level + 1):
        new_level += 1

    user_levels[user.id]['level'] = new_level

    embed = discord.Embed(
        title="✅ XP Given",
        description=f"**{user.mention}** received **{amount:,} XP**!",
        color=0x00ff00
    )

    if new_level > old_level:
        embed.description += f"\n🎉 They leveled up from **Level {old_level}** to **Level {new_level}**!"

    progress = get_level_progress(user.id, user)
    embed.add_field(
        name="📊 New Stats",
        value=f"Level: **{progress['level']}**\n"
              f"Total XP: **{progress['current_xp']:,}**\n"
              f"Multiplier: **{progress['multiplier']:.2f}x**",
        inline=False
    )

    await interaction.response.send_message(embed=embed)

if TOKEN is None:
    print("Error: TOKEN environment variable not found!")
    exit(1)

keep_alive()
bot.run(TOKEN)