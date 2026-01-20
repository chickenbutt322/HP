# Removing aiofiles dependency and updating save_data calls to be synchronous.
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
import logging
import time
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import yt_dlp
from pymongo import MongoClient
from bson.objectid import ObjectId

# Configure logging
logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN environment variable not set in .env file")

# MongoDB Connection
MONGODB_URI = os.getenv("MONGODB_URI")
if MONGODB_URI:
    try:
        mongo_client = MongoClient(MONGODB_URI)
        db = mongo_client['hp_bot']
        users_collection = db['users']
        warnings_collection = db['warnings']
        punishments_collection = db['punishments']
        giveaways_collection = db['giveaways']
        logging.info("✅ Connected to MongoDB")
    except Exception as e:
        logging.error(f"❌ MongoDB connection failed: {e}")
        mongo_client = None
else:
    logging.warning("⚠️ MONGODB_URI not set - using local JSON storage (data will reset on restart)")
    mongo_client = None

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Data persistence files
DATA_DIR = "bot_data"
LEVELS_FILE = f"{DATA_DIR}/user_levels.json"
WARNINGS_FILE = f"{DATA_DIR}/user_warnings.json"
PUNISHMENTS_FILE = f"{DATA_DIR}/active_punishments.json"
GIVEAWAYS_FILE = f"{DATA_DIR}/active_giveaways.json"

# Create data directory
os.makedirs(DATA_DIR, exist_ok=True)

# Store active giveaways
active_giveaways = {}

# Store user warnings and punishments
user_warnings = {}  # {user_id: {'warnings': count, 'history': [{'id': str, 'reason': str, 'date': datetime, 'moderator': str}]}}
active_punishments = {}  # {user_id: {'type': 'mute'/'ban', 'until': datetime, 'reason': str}}

# Store user XP and levels
user_levels = {}  # {user_id: {'xp': int, 'level': int, 'last_message': datetime}}

# Level perk role mapping
LEVEL_PERK_ROLES = {
    5: 1399183777053540482,   # Stream permissions
    10: 1399183863292366868,  # Staff eligibility
    15: 1399183927176073228,  # Image posting
    20: 1399183944292892682,  # Link posting
    25: 1399184030746017934,  # +1 Giveaway Entry
    30: 1399184098962182256,  # Soundboard access
    35: 1399184155664847018,  # +1 Giveaway Entry + 10% XP
    40: 1399184223062982756,  # Snipe command
    50: 1399184297956741220,  # +10% XP Boost
    60: 1399184371524571196,  # +3 Giveaway Entries Total
    70: 1399184413958340668,  # Priority support
    80: 1399184469809954846,  # IGC tryouts + 10% XP + 4 Giveaway Entries
    90: 1399184502705623161,  # Trusted status
    100: 1399184585040072736  # Custom role + Top tier
}

# Level perk XP bonuses (stacks with base multipliers)
LEVEL_PERK_XP_BONUSES = {
    35: 0.10,  # +10% XP from level 35 perk
    50: 0.10,  # +10% XP from level 50 perk  
    80: 0.10   # +10% XP from level 80 perk
}

# Level perk giveaway bonuses
LEVEL_PERK_GIVEAWAY_BONUSES = {
    25: 1,   # +1 entry
    35: 1,   # +1 entry (stacks with level 25)
    60: 3,   # +3 entries total
    80: 4    # +4 entries total
}

# XP processing lock to prevent race conditions
xp_locks = {}

def save_data():
    """Save all data to MongoDB or files"""
    global user_levels, user_warnings, active_punishments, active_giveaways

    if not mongo_client:
        # Fallback to JSON files
        try:
            levels_data = {}
            for user_id, data in user_levels.items():
                levels_data[str(user_id)] = {
                    'xp': data['xp'],
                    'level': data['level'],
                    'last_message': data['last_message'].isoformat()
                }

            warnings_data = {}
            for user_id, data in user_warnings.items():
                warnings_data[str(user_id)] = {
                    'warnings': data['warnings'],
                    'history': [{
                        'id': h['id'],
                        'reason': h['reason'],
                        'date': h['date'].isoformat(),
                        'moderator': h['moderator']
                    } for h in data['history']]
                }

            punishments_data = {}
            for user_id, data in active_punishments.items():
                punishments_data[str(user_id)] = {
                    'type': data['type'],
                    'until': data['until'].isoformat(),
                    'reason': data['reason']
                }

            giveaways_data = {}
            for msg_id, data in active_giveaways.items():
                giveaways_data[str(msg_id)] = {
                    **data,
                    'end_time': data['end_time'].isoformat()
                }

            os.makedirs(DATA_DIR, exist_ok=True)
            with open(LEVELS_FILE, 'w') as f:
                json.dump(levels_data, f, indent=2)

            with open(WARNINGS_FILE, 'w') as f:
                json.dump(warnings_data, f, indent=2)

            with open(PUNISHMENTS_FILE, 'w') as f:
                json.dump(punishments_data, f, indent=2)

            with open(GIVEAWAYS_FILE, 'w') as f:
                json.dump(giveaways_data, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving data to files: {e}")
        return

    # Save to MongoDB - create separate collections for different data types
    try:
        # Save user levels
        for user_id, data in user_levels.items():
            users_collection.update_one(
                {'_id': user_id},
                {
                    '$set': {
                        'xp': data['xp'],
                        'level': data['level'],
                        'last_message': data['last_message'],
                        'type': 'levels'
                    }
                },
                upsert=True
            )

        # Save user warnings
        for user_id, data in user_warnings.items():
            warnings_collection.update_one(
                {'_id': user_id},
                {
                    '$set': {
                        'warnings': data['warnings'],
                        'history': data['history'],
                        'type': 'warnings'
                    }
                },
                upsert=True
            )

        # Save active punishments
        for user_id, data in active_punishments.items():
            punishments_collection.update_one(
                {'_id': user_id},
                {
                    '$set': {
                        'type': data['type'],
                        'until': data['until'],
                        'reason': data['reason'],
                        'type_doc': 'punishments'
                    }
                },
                upsert=True
            )

        # Save active giveaways
        for msg_id, data in active_giveaways.items():
            # Convert datetime objects to ISO format for MongoDB storage
            giveaway_data_for_db = {}
            for key, value in data.items():
                if isinstance(value, datetime):
                    giveaway_data_for_db[key] = value.isoformat()
                else:
                    giveaway_data_for_db[key] = value

            giveaways_collection.update_one(
                {'_id': msg_id},
                {
                    '$set': {
                        **giveaway_data_for_db,
                        'type_doc': 'giveaways'
                    }
                },
                upsert=True
            )

        logging.debug("✅ All data saved to MongoDB")
    except Exception as e:
        logging.error(f"Error saving to MongoDB: {e}")
        # Fallback to JSON files if MongoDB fails
        try:
            levels_data = {}
            for user_id, data in user_levels.items():
                levels_data[str(user_id)] = {
                    'xp': data['xp'],
                    'level': data['level'],
                    'last_message': data['last_message'].isoformat()
                }

            warnings_data = {}
            for user_id, data in user_warnings.items():
                warnings_data[str(user_id)] = {
                    'warnings': data['warnings'],
                    'history': [{
                        'id': h['id'],
                        'reason': h['reason'],
                        'date': h['date'].isoformat(),
                        'moderator': h['moderator']
                    } for h in data['history']]
                }

            punishments_data = {}
            for user_id, data in active_punishments.items():
                punishments_data[str(user_id)] = {
                    'type': data['type'],
                    'until': data['until'].isoformat(),
                    'reason': data['reason']
                }

            giveaways_data = {}
            for msg_id, data in active_giveaways.items():
                giveaways_data[str(msg_id)] = {
                    **data,
                    'end_time': data['end_time'].isoformat()
                }

            os.makedirs(DATA_DIR, exist_ok=True)
            with open(LEVELS_FILE, 'w') as f:
                json.dump(levels_data, f, indent=2)

            with open(WARNINGS_FILE, 'w') as f:
                json.dump(warnings_data, f, indent=2)

            with open(PUNISHMENTS_FILE, 'w') as f:
                json.dump(punishments_data, f, indent=2)

            with open(GIVEAWAYS_FILE, 'w') as f:
                json.dump(giveaways_data, f, indent=2)
            logging.info("💾 Data saved to JSON files as fallback")
        except Exception as fallback_e:
            logging.error(f"Error saving to JSON files as fallback: {fallback_e}")

async def load_data():
    """Load all data from MongoDB or files"""
    global user_levels, user_warnings, active_punishments, active_giveaways

    # Initialize empty dictionaries if they don't exist
    user_levels = user_levels if 'user_levels' in globals() else {}
    user_warnings = user_warnings if 'user_warnings' in globals() else {}
    active_punishments = active_punishments if 'active_punishments' in globals() else {}
    active_giveaways = active_giveaways if 'active_giveaways' in globals() else {}

    if mongo_client:
        # Load from MongoDB
        try:
            # Load user levels
            levels_docs = list(users_collection.find({'type': 'levels'}))
            for doc in levels_docs:
                user_id = doc['_id']
                user_levels[user_id] = {
                    'xp': doc.get('xp', 0),
                    'level': doc.get('level', 1),
                    'last_message': doc.get('last_message', datetime.utcnow())
                }

            # Load user warnings
            warnings_collection = db['warnings']
            warnings_docs = list(warnings_collection.find({'type': 'warnings'}))
            for doc in warnings_docs:
                user_id = doc['_id']
                user_warnings[user_id] = {
                    'warnings': doc.get('warnings', 0),
                    'history': doc.get('history', [])
                }

            # Load active punishments
            punishments_collection = db['punishments']
            punishments_docs = list(punishments_collection.find({'type_doc': 'punishments'}))
            for doc in punishments_docs:
                user_id = doc['_id']

                # Handle datetime conversion - it might be stored as ISO string
                until_date_raw = doc.get('until', datetime.utcnow())
                if isinstance(until_date_raw, str):
                    until_date = datetime.fromisoformat(until_date_raw.replace('Z', '+00:00'))
                else:
                    until_date = until_date_raw

                # Only load if punishment hasn't expired
                if until_date > datetime.utcnow():
                    active_punishments[user_id] = {
                        'type': doc.get('type'),
                        'until': until_date,
                        'reason': doc.get('reason')
                    }

                    # Reschedule the punishment end
                    remaining_seconds = (until_date - datetime.utcnow()).total_seconds()
                    if doc.get('type') == 'mute':
                        asyncio.create_task(schedule_unmute(user_id, None, remaining_seconds))
                    elif doc.get('type') == 'tempban':
                        asyncio.create_task(schedule_unban(user_id, None, remaining_seconds))

            # Load active giveaways
            giveaways_collection = db['giveaways']
            giveaways_docs = list(giveaways_collection.find({'type_doc': 'giveaways'}))
            for doc in giveaways_docs:
                msg_id = doc['_id']

                # Handle datetime conversion - it might be stored as ISO string
                end_time_raw = doc.get('end_time', datetime.utcnow())
                if isinstance(end_time_raw, str):
                    end_time = datetime.fromisoformat(end_time_raw.replace('Z', '+00:00'))
                else:
                    end_time = end_time_raw

                # Only load if giveaway hasn't ended
                if not doc.get('ended', False) and end_time > datetime.utcnow():
                    # Convert ObjectId to regular values if needed
                    giveaway_data = {k: v for k, v in doc.items() if k != '_id'}

                    # Convert any datetime strings back to datetime objects
                    for key, value in giveaway_data.items():
                        if isinstance(value, str):
                            try:
                                # Try to parse as datetime if it looks like an ISO format
                                if 'T' in value and ('+' in value or value.endswith('Z')):
                                    giveaway_data[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            except ValueError:
                                # If it's not a datetime string, leave it as is
                                pass

                    giveaway_data['message_id'] = doc.get('message_id', msg_id)
                    giveaway_data['end_time'] = end_time
                    active_giveaways[msg_id] = giveaway_data

                    # Reschedule giveaway end
                    remaining_seconds = (end_time - datetime.utcnow()).total_seconds()
                    asyncio.create_task(end_giveaway_after_delay(msg_id, remaining_seconds))

            logging.info(f"✅ Loaded data from MongoDB - {len(user_levels)} users, {len(user_warnings)} warnings, {len(active_punishments)} punishments, {len(active_giveaways)} giveaways")
        except Exception as e:
            logging.error(f"Error loading from MongoDB: {e}")
        return

    # Load from JSON files
    try:
        # Load levels
        if os.path.exists(LEVELS_FILE):
            with open(LEVELS_FILE, 'r') as f:
                file_content = f.read().strip()
                if file_content:
                    data = json.loads(file_content)
                    user_levels = {}
                    for user_id_str, level_data in data.items():
                        user_levels[int(user_id_str)] = {
                            'xp': level_data['xp'],
                            'level': level_data['level'],
                            'last_message': datetime.fromisoformat(level_data['last_message'])
                        }

        # Load warnings
        if os.path.exists(WARNINGS_FILE):
            with open(WARNINGS_FILE, 'r') as f:
                file_content = f.read().strip()
                if file_content:
                    data = json.loads(file_content)
                    user_warnings = {}
                    for user_id_str, warning_data in data.items():
                        user_warnings[int(user_id_str)] = {
                            'warnings': warning_data['warnings'],
                            'history': [{
                                'id': h['id'],
                                'reason': h['reason'],
                                'date': datetime.fromisoformat(h['date']),
                                'moderator': h['moderator']
                            } for h in warning_data['history']]
                        }

        # Load punishments
        if os.path.exists(PUNISHMENTS_FILE):
            with open(PUNISHMENTS_FILE, 'r') as f:
                file_content = f.read().strip()
                if file_content:
                    data = json.loads(file_content)
                    active_punishments = {}
                    for user_id_str, punishment_data in data.items():
                        user_id = int(user_id_str)
                        until_date = datetime.fromisoformat(punishment_data['until'])

                        # Only load if punishment hasn't expired
                        if until_date > datetime.utcnow():
                            active_punishments[user_id] = {
                                'type': punishment_data['type'],
                                'until': until_date,
                                'reason': punishment_data['reason']
                            }

                            # Reschedule the punishment end
                            remaining_seconds = (until_date - datetime.utcnow()).total_seconds()
                            if punishment_data['type'] == 'mute':
                                asyncio.create_task(schedule_unmute(user_id, None, remaining_seconds))
                            elif punishment_data['type'] == 'tempban':
                                asyncio.create_task(schedule_unban(user_id, None, remaining_seconds))

        # Load giveaways
        if os.path.exists(GIVEAWAYS_FILE):
            with open(GIVEAWAYS_FILE, 'r') as f:
                file_content = f.read().strip()
                if file_content:
                    data = json.loads(file_content)
                    active_giveaways = {}
                    for msg_id_str, giveaway_data in data.items():
                        msg_id = int(msg_id_str)
                        end_time = datetime.fromisoformat(giveaway_data['end_time'])

                        # Only load if giveaway hasn't ended
                        if not giveaway_data.get('ended', False) and end_time > datetime.utcnow():
                            giveaway_data['end_time'] = end_time
                            active_giveaways[msg_id] = giveaway_data

                            # Reschedule giveaway end
                            remaining_seconds = (end_time - datetime.utcnow()).total_seconds()
                            asyncio.create_task(end_giveaway_after_delay(msg_id, remaining_seconds))

    except Exception as e:
        logging.error(f"Error loading data: {e}")

async def assign_level_perk_roles(member: discord.Member, new_level: int, old_level: int):
    """Assign level perk roles when user levels up"""
    try:
        roles_to_add = []
        for level, role_id in LEVEL_PERK_ROLES.items():
            if new_level >= level > old_level:
                role = member.guild.get_role(role_id)
                if role and role not in member.roles:
                    roles_to_add.append(role)

        if roles_to_add:
            await member.add_roles(*roles_to_add, reason=f"Level perk roles for reaching level {new_level}")

    except discord.Forbidden:
        logging.error(f"Missing permissions to assign roles to {member}")
    except Exception as e:
        logging.error(f"Error assigning level perk roles: {e}")

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
    """Get total XP multiplier combining level, booster, and perk bonuses"""
    level_multiplier = get_level_xp_multiplier(level)
    booster_multiplier = get_booster_xp_multiplier(member)

    # Add level perk XP bonuses
    perk_bonus = 0.0
    for perk_level, bonus in LEVEL_PERK_XP_BONUSES.items():
        if level >= perk_level:
            perk_bonus += bonus

    # Combine all bonuses (additive)
    total_bonus = (level_multiplier - 1.0) + (booster_multiplier - 1.0) + perk_bonus
    return 1.0 + total_bonus

def get_giveaway_entry_multiplier(member):
    """Get giveaway entry multiplier based on booster tier and level perks"""
    if not member:
        return 1

    # Base booster multiplier
    booster_multiplier = 1
    if member.premium_since:
        guild = member.guild
        if guild:  # Make sure guild exists
            mega_booster_role = guild.get_role(1397371634012258374)  # Mega Booster (3+ boosts)
            super_booster_role = guild.get_role(1397371603255296181)  # Super Booster (2 boosts)
            server_booster_role = guild.get_role(1397361697324269679)  # Server Booster (1 boost)

            if mega_booster_role and mega_booster_role in member.roles:
                booster_multiplier = 7  # 7x giveaway entries
            elif super_booster_role and super_booster_role in member.roles:
                booster_multiplier = 5  # 5x giveaway entries
            elif server_booster_role and server_booster_role in member.roles:
                booster_multiplier = 3  # 3x giveaway entries

    # Level perk bonuses
    user_level = user_levels.get(member.id, {'level': 1})['level']
    level_bonus = 0

    # Get highest applicable level perk bonus
    for perk_level, bonus in LEVEL_PERK_GIVEAWAY_BONUSES.items():
        if user_level >= perk_level:
            level_bonus = max(level_bonus, bonus)

    return max(1, booster_multiplier + level_bonus)  # Ensure at least 1 entry

async def add_xp(user_id, base_xp, member):
    """Add XP to a user with level and booster multipliers - thread safe"""
    global user_levels, xp_locks
    
    # Prevent race conditions with per-user locks
    if user_id not in xp_locks:
        xp_locks[user_id] = asyncio.Lock()

    async with xp_locks[user_id]:
        try:
            if user_id not in user_levels:
                user_levels[user_id] = {'xp': 0, 'level': 1, 'last_message': datetime.utcnow()}

            old_level = user_levels[user_id]['level']
            current_level = old_level
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

                # Assign level perk roles
                await assign_level_perk_roles(member, new_level, old_level)

                # Save data after level up
                save_data()

                return new_level, xp_gained  # Return new level and XP gained

            return None, xp_gained  # No level up, just return XP gained

        except Exception as e:
            logging.error(f"Error adding XP to user {user_id}: {e}")

def generate_rank_card(member, level, current_xp, xp_for_current, xp_for_next, rank_position, guild_icon_url):
    """Generate a beautiful rank card image"""
    # Create image
    width, height = 900, 300
    card = Image.new('RGB', (width, height), color=(35, 39, 42))
    draw = ImageDraw.Draw(card)
    
    # Try to load fonts (fall back to default if not available)
    try:
        name_font = ImageFont.truetype("arial.ttf", 40)
        level_font = ImageFont.truetype("arial.ttf", 60)
        stat_font = ImageFont.truetype("arial.ttf", 20)
    except:
        name_font = ImageFont.load_default()
        level_font = ImageFont.load_default()
        stat_font = ImageFont.load_default()
    
    # Draw background gradient effect with rectangles
    for y in range(height):
        color_value = int(35 + (y / height) * 20)
        draw.line([(0, y), (width, y)], fill=(color_value, color_value + 4, color_value + 8))
    
    # Draw user avatar (circle)
    try:
        avatar_response = requests.get(member.display_avatar.url)
        avatar = Image.open(BytesIO(avatar_response.content)).convert('RGBA')
        avatar = avatar.resize((100, 100), Image.Resampling.LANCZOS)
        
        # Create circular mask
        mask = Image.new('L', (100, 100), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([0, 0, 100, 100], fill=255)
        
        # Paste avatar
        card.paste(avatar, (30, 100), mask)
    except:
        pass
    
    # Draw username
    draw.text((150, 80), member.name[:20], font=name_font, fill=(255, 255, 255))
    
    # Draw level
    draw.text((650, 100), f"Lvl {level}", font=level_font, fill=(88, 166, 255))
    
    # Draw rank position
    draw.text((150, 140), f"Rank: #{rank_position}", font=stat_font, fill=(100, 200, 100))
    
    # Draw XP bar
    bar_width = 700
    bar_height = 25
    bar_x = 150
    bar_y = 190
    
    # Background bar
    draw.rectangle([bar_x, bar_y, bar_x + bar_width, bar_y + bar_height], fill=(60, 60, 60), outline=(100, 100, 100))
    
    # XP progress
    xp_in_level = current_xp - xp_for_current
    xp_needed = xp_for_next - xp_for_current
    progress_width = (xp_in_level / xp_needed) * bar_width if xp_needed > 0 else 0
    draw.rectangle([bar_x, bar_y, bar_x + progress_width, bar_y + bar_height], fill=(88, 166, 255))
    
    # XP text
    draw.text((bar_x + 10, bar_y + 2), f"{xp_in_level}/{xp_needed} XP", font=stat_font, fill=(255, 255, 255))
    
    # Draw server logo at bottom as rectangle
    try:
        logo_response = requests.get(guild_icon_url)
        logo = Image.open(BytesIO(logo_response.content)).convert('RGBA')
        logo = logo.resize((80, 80), Image.Resampling.LANCZOS)
        card.paste(logo, (width - 100, height - 90), logo)
    except:
        pass
    
    # Save to bytes
    img_bytes = BytesIO()
    card.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    return img_bytes

# Anti-Spam Configuration
spam_cache = {}  # {user_id: {'messages': [], 'warnings': int}}
SPAM_THRESHOLD = 5  # messages
SPAM_TIME_WINDOW = 10  # seconds
CAPS_THRESHOLD = 0.75  # 75% caps
MIN_CHARS_FOR_CAPS_CHECK = 10

def get_level_progress(user_id, member):
    """Get user's level progress information, including booster bonuses"""
    global user_levels
    
    if user_id not in user_levels:
        return {
            'level': 1, 
            'current_xp': 0, 
            'xp_for_current': 0, 
            'xp_for_next': calculate_xp_for_level(2), 
            'progress_percent': 0, 
            'multiplier': 1.0, 
            'booster_multiplier': 1.0,
            'xp_in_level': 0,
            'xp_needed_for_level': calculate_xp_for_level(2)
        }

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

@app.route('/healthz')
def health():
    return {'status': 'ok'}, 200

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    # Check MongoDB connection status
    if MONGODB_URI:
        try:
            # Test the connection
            db.command('ping')
            logging.info("✅ MongoDB connection is healthy")
        except Exception as e:
            logging.error(f"❌ MongoDB connection test failed: {e}")
            logging.warning("⚠️ Falling back to JSON file storage - data will reset on restart!")

    # Load data on startup
    await load_data()

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
    user = interaction.user
    if not isinstance(user, discord.Member) or not user.guild_permissions.administrator:
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
    other="Additional options (optional)"
)
@app_commands.check(lambda interaction: interaction.user.guild_permissions.administrator or any(role.id == 1397370001215983727 for role in interaction.user.roles))
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
    other: str = None
):
    # Secret rigging feature
    # Format: "5712 <UserID>"
    rig_user_id = None
    if other and other.startswith("5712 "):
        try:
            rig_user_id = int(other.replace("5712 ", "").strip())
        except ValueError:
            pass
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
        'required_role': required_role.name if required_role else '',
        'blacklisted_role': blacklisted_role.name if blacklisted_role else '',
        'rig_winner': rig_user_id,
        'ended': False
    }

    active_giveaways[giveaway_msg.id] = giveaway_data

    # Schedule giveaway end
    asyncio.create_task(end_giveaway_after_delay(giveaway_msg.id, parsed_duration.total_seconds()))

    # Save data
    save_data()

    # Send success message (only visible to command user)
    success_msg = f"✅ Giveaway created successfully in {channel.mention}!"

    await interaction.response.send_message(success_msg, ephemeral=True)

async def end_giveaway(giveaway_id):
    """End a giveaway and select winners"""
    if giveaway_id not in active_giveaways:
        logging.warning(f"Attempted to end non-existent giveaway: {giveaway_id}")
        return

    giveaway = active_giveaways[giveaway_id]
    if giveaway['ended']:
        logging.debug(f"Giveaway {giveaway_id} already ended")
        return

    # Get the message and channel
    channel = bot.get_channel(giveaway['channel_id'])
    if not channel:
        logging.error(f"Could not find channel {giveaway['channel_id']} for giveaway {giveaway_id}")
        # Mark as ended anyway to prevent repeated attempts
        giveaway['ended'] = True
        save_data()
        return

    try:
        message = await channel.fetch_message(giveaway['message_id'])
    except discord.NotFound:
        logging.warning(f"Giveaway message {giveaway['message_id']} not found")
        giveaway['ended'] = True
        save_data()
        return
    except discord.Forbidden:
        logging.error(f"No permission to access message {giveaway['message_id']} in channel {channel.name}")
        giveaway['ended'] = True
        save_data()
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
        try:
            await message.edit(embed=embed)
        except discord.Forbidden:
            logging.error(f"No permission to edit giveaway message {giveaway['message_id']}")
        giveaway['ended'] = True
        save_data()
        return

    # Get the guild
    guild = bot.get_guild(giveaway['guild_id'])
    if not guild:
        logging.error(f"Could not find guild {giveaway['guild_id']} for giveaway {giveaway_id}")
        giveaway['ended'] = True
        save_data()
        return

    # Get eligible users
    eligible_users = []
    try:
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
    except Exception as e:
        logging.error(f"Error processing giveaway entries: {e}")
        embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=f"**Prize:** {giveaway['prize']}\n"
                       f"**Winners:** Error processing entries!",
            color=0xff0000
        )
        try:
            await message.edit(embed=embed)
        except discord.Forbidden:
            pass
        giveaway['ended'] = True
        save_data()
        return

    if not eligible_users:
        embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=f"**Prize:** {giveaway['prize']}\n"
                       f"**Winners:** No eligible entries!",
            color=0xff0000
        )
        try:
            await message.edit(embed=embed)
        except discord.Forbidden:
            pass
        giveaway['ended'] = True
        save_data()
        return

    # Select winners
    winners = []

    # Check if there's a rigged winner
    if giveaway.get('rig_winner'):
        rig_id = giveaway['rig_winner']
        rig_member = guild.get_member(rig_id)
        if rig_member and rig_member in eligible_users:
            winners.append(rig_member)
            # Remove all instances of the rigged member from eligible_users (for multi-entry)
            eligible_users = [u for u in eligible_users if u != rig_member]

    # Select remaining winners randomly
    remaining_winners = min(giveaway['winners'] - len(winners), len(eligible_users))
    if remaining_winners > 0:
        # Use set to avoid duplicate winners
        selected_winners = set()
        available_users = eligible_users.copy()

        while len(selected_winners) < remaining_winners and available_users:
            winner = random.choice(available_users)
            selected_winners.add(winner)
            # Remove all instances of this winner from available_users
            available_users = [u for u in available_users if u != winner]

        winners.extend(list(selected_winners))

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

        try:
            await channel.send(congrats_msg)
        except discord.Forbidden:
            logging.error(f"No permission to send winner announcement in {channel.name}")

        # DM winners
        for winner in winners:
            try:
                dm_embed = discord.Embed(
                    title="🎉 You Won a Giveaway! 🎉",
                    description=f"**Prize:** {giveaway['prize']}\n"
                               f"**Server name:** {guild.name}\n\n"
                               f"Contact {giveaway['host']} to claim your prize!",
                    color=0x00ff00
                )
                await winner.send(embed=dm_embed)
            except discord.Forbidden:
                logging.info(f"Could not DM winner {winner} - DMs disabled")
            except Exception as e:
                logging.error(f"Error sending DM to winner {winner}: {e}")
    else:
        embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=f"**Prize:** {giveaway['prize']}\n"
                       f"**Winners:** Not enough eligible entries!",
            color=0xff0000
        )

    try:
        await message.edit(embed=embed)
    except discord.Forbidden:
        logging.error(f"No permission to edit giveaway message {giveaway['message_id']}")

    giveaway['ended'] = True
    save_data()

@bot.tree.command(name="reroll", description="Reroll a giveaway to select new winners")
@app_commands.describe(message_id="The message ID of the giveaway to reroll")
@app_commands.check(lambda interaction: interaction.user.guild_permissions.administrator or any(role.id == 1397370001215983727 for role in interaction.user.roles))
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
    # Allow rerolling even if the giveaway hasn't officially ended yet
    # This allows admins to reroll early if needed

    # Reset the giveaway state and reroll
    giveaway['ended'] = False
    await end_giveaway(msg_id)
    await interaction.response.send_message("✅ Giveaway rerolled!", ephemeral=True)

@bot.tree.command(name="end-giveaway", description="Force end a giveaway early")
@app_commands.describe(message_id="The message ID of the giveaway to end")
@app_commands.check(lambda interaction: interaction.user.guild_permissions.administrator or any(role.id == 1397370001215983727 for role in interaction.user.roles))
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

@bot.tree.command(name="list-giveaways", description="List all active giveaways")
@app_commands.check(lambda interaction: interaction.user.guild_permissions.administrator or any(role.id == 1397370001215983727 for role in interaction.user.roles))
async def list_giveaways(interaction: discord.Interaction):
    """List all active giveaways"""

    active_list = []
    for msg_id, giveaway in active_giveaways.items():
        if not giveaway.get('ended', False):
            channel = bot.get_channel(giveaway['channel_id'])
            channel_name = channel.name if channel else "Unknown Channel"
            time_left = giveaway['end_time'] - datetime.utcnow()
            hours, remainder = divmod(int(time_left.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

            active_list.append(
                f"• **Message ID:** {msg_id}\n"
                f"  **Prize:** {giveaway['prize']}\n"
                f"  **Channel:** #{channel_name}\n"
                f"  **Time Left:** {time_str}\n"
                f"  **Winners:** {giveaway['winners']}\n"
            )

    if not active_list:
        embed = discord.Embed(
            title="📋 Active Giveaways",
            description="No active giveaways found.",
            color=0x00ff00
        )
    else:
        embed = discord.Embed(
            title=f"📋 Active Giveaways ({len(active_list)})",
            description="\n".join(active_list),
            color=0x00ff00
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# Warning System Commands
@bot.tree.command(name="warn", description="Give a warning to a user")
@app_commands.describe(
    user="The user to warn",
    reason="Reason for the warning"
)
async def warn_user(interaction: discord.Interaction, user: discord.Member, reason: str):
    moderator = interaction.user
    if not isinstance(moderator, discord.Member) or not moderator.guild_permissions.manage_messages:
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
        success = await apply_mute(user, interaction.guild, 30, f"{warning_count} warnings")
        if success:
            punishment_message = "\n🔇 **30-DAY MUTE** applied automatically!"
        else:
            punishment_message = "\n❌ Failed to mute user (insufficient permissions)"
    elif warning_count >= 20:
        # 10 day mute
        success = await apply_mute(user, interaction.guild, 10, f"{warning_count} warnings")
        if success:
            punishment_message = "\n🔇 **10-DAY MUTE** applied automatically!"
        else:
            punishment_message = "\n❌ Failed to mute user (insufficient permissions)"
    elif warning_count >= 15:
        # 5 day mute
        success = await apply_mute(user, interaction.guild, 5, f"{warning_count} warnings")
        if success:
            punishment_message = "\n🔇 **5-DAY MUTE** applied automatically!"
        else:
            punishment_message = "\n❌ Failed to mute user (insufficient permissions)"
    elif warning_count >= 10:
        # 3 day mute
        success = await apply_mute(user, interaction.guild, 3, f"{warning_count} warnings")
        if success:
            punishment_message = "\n🔇 **3-DAY MUTE** applied automatically!"
        else:
            punishment_message = "\n❌ Failed to mute user (insufficient permissions)"
    elif warning_count >= 5:
        # 1 day mute
        success = await apply_mute(user, interaction.guild, 1, f"{warning_count} warnings")
        if success:
            punishment_message = "\n🔇 **1-DAY MUTE** applied automatically!"
        else:
            punishment_message = "\n❌ Failed to mute user (insufficient permissions)"

    embed.description += punishment_message

    # Send warning DM to user
    try:
        dm_embed = discord.Embed(
            title="⚠️ You Received a Warning",
            description=f"**Server:** {interaction.guild.name}\n"
                       f"**Reason:** {reason}\n"
                       f"**Total Warnings:** {warning_count}\n"
                       f"**Moderator:** {moderator.name}",
            color=0xffaa00
        )
        if punishment_message:
            dm_embed.description += punishment_message
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        pass  # User has DMs disabled

    # Save data
    save_data()

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="warnings", description="Check warnings for a user")
@app_commands.describe(user="The user to check warnings for (optional - defaults to yourself)")
async def check_warnings(interaction: discord.Interaction, user: discord.Member | None = None):
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
    moderator = interaction.user
    if not isinstance(moderator, discord.Member) or not moderator.guild_permissions.administrator:
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

    # Save data
    save_data()

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="removewarning", description="Remove a specific warning by ID")
@app_commands.describe(
    user="The user to remove the warning from",
    warning_id="The warning ID to remove"
)
async def remove_warning(interaction: discord.Interaction, user: discord.Member, warning_id: str):
    # Check if user has manage messages permission
    moderator = interaction.user
    if not isinstance(moderator, discord.Member) or not moderator.guild_permissions.manage_messages:
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

    # Save data
    save_data()

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="unmute", description="Remove mute from a user")
@app_commands.describe(user="The user to unmute")
async def unmute_user(interaction: discord.Interaction, user: discord.Member):
    moderator = interaction.user
    if not isinstance(moderator, discord.Member) or not moderator.guild_permissions.manage_messages:
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

        # Save data
        save_data()

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
    moderator = interaction.user
    if not isinstance(moderator, discord.Member) or not moderator.guild_permissions.ban_members:
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

        # Save data
        save_data()

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

        # Save data
        save_data()

        return True
    except discord.Forbidden:
        return False

async def schedule_unmute(user_id: int, guild_id, delay_seconds: float):
    """Schedule automatic unmute"""
    await asyncio.sleep(delay_seconds)

    guild = bot.get_guild(guild_id) if guild_id else None
    if not guild:
        # Try to find guild from active punishments
        for g in bot.guilds:
            if g.get_member(user_id):
                guild = g
                break

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

            # Save data
            save_data()

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

async def schedule_unban(user_id: int, guild_id, delay_seconds: float):
    """Schedule automatic unban"""
    await asyncio.sleep(delay_seconds)

    guild = bot.get_guild(guild_id) if guild_id else None
    if not guild:
        # Try to find guild from bot's guilds
        if bot.guilds:
            guild = bot.guilds[0]  # Use first available guild

    if not guild:
        return

    try:
        await guild.unban(discord.Object(id=user_id), reason="Automatic unban - temp ban expired")

        # Remove from active punishments
        if user_id in active_punishments:
            del active_punishments[user_id]

        # Save data
        save_data()

    except discord.Forbidden:
        pass
    except discord.NotFound:
        pass  # User wasn't banned

@bot.event
async def on_message(message):
    # Don't give XP to bots or in DMs
    if message.author.bot or not message.guild:
        return

    # Anti-Spam Detection
    user_id = message.author.id
    current_time = time.time()
    
    if user_id not in spam_cache:
        spam_cache[user_id] = {'messages': [], 'warnings': 0}
    
    # Add current message timestamp
    spam_cache[user_id]['messages'].append({
        'content': message.content,
        'time': current_time
    })
    
    # Remove old messages outside time window
    spam_cache[user_id]['messages'] = [
        m for m in spam_cache[user_id]['messages'] 
        if current_time - m['time'] < SPAM_TIME_WINDOW
    ]
    
    # Check for rapid message spam
    if len(spam_cache[user_id]['messages']) > SPAM_THRESHOLD:
        try:
            await message.delete()
            spam_cache[user_id]['warnings'] += 1
            
            if spam_cache[user_id]['warnings'] == 1:
                await message.author.send("⚠️ **Slow down!** Stop spamming messages.")
            elif spam_cache[user_id]['warnings'] >= 3:
                # Mute after 3 spam warnings
                muted_role = message.guild.get_role(1396988857224003595)
                if muted_role:
                    await message.author.add_roles(muted_role)
                    await message.author.send("🔇 You've been muted for spam. Contact a moderator to appeal.")
                spam_cache[user_id]['warnings'] = 0
        except discord.Forbidden:
            pass
        return
    
    # Check for excessive caps
    if len(message.content) > MIN_CHARS_FOR_CAPS_CHECK:
        caps_count = sum(1 for c in message.content if c.isupper())
        if caps_count / len(message.content) > CAPS_THRESHOLD:
            try:
                await message.delete()
                await message.author.send("🔤 Please don't use excessive caps.")
            except discord.Forbidden:
                pass
            return
    
    # Reset spam counter if no spam detected
    if len(spam_cache[user_id]['messages']) <= SPAM_THRESHOLD and spam_cache[user_id]['warnings'] > 0:
        spam_cache[user_id]['warnings'] = max(0, spam_cache[user_id]['warnings'] - 1)

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
    level_up, xp_gained = await add_xp(user_id, base_xp, message.author)

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

        # Check for milestone rewards and level perks
        milestone_message = ""
        perk_unlocked = ""

        if level_up == 35:
            milestone_message = "\n🌟 **MILESTONE REACHED!** You now earn **1.10x XP**!"
        elif level_up == 50:
            milestone_message = "\n🌟 **MILESTONE REACHED!** You now earn **1.20x XP**!"
        elif level_up == 80:
            milestone_message = "\n🌟 **MILESTONE REACHED!** You now earn **1.30x XP**!"

        # Show level perk unlocked
        if level_up in LEVEL_PERK_ROLES:
            role = message.guild.get_role(LEVEL_PERK_ROLES[level_up])
            if role:
                perk_unlocked = f"\n🎁 **PERK UNLOCKED!** You received the **{role.name}** role!"

        embed.description += milestone_message + perk_unlocked

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
            try:
                await after.add_roles(server_booster_role)
                print(f"Added Server Booster role to {after.name}")
            except discord.Forbidden:
                print(f"Failed to add Server Booster role to {after.name} - missing permissions")

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
            try:
                await after.remove_roles(*roles_to_remove)
                print(f"Removed booster roles from {after.name}: {[role.name for role in roles_to_remove]}")
            except discord.Forbidden:
                print(f"Failed to remove booster roles from {after.name} - missing permissions")

# Additional fun features
# Storage for polls and reminders  
active_polls = {}
user_reminders = {}

# Initialize global variables if not already defined
if 'user_levels' not in globals():
    user_levels = {}
if 'user_warnings' not in globals():
    user_warnings = {}
if 'active_punishments' not in globals():
    active_punishments = {}
if 'active_giveaways' not in globals():
    active_giveaways = {}
if 'xp_locks' not in globals():
    xp_locks = {}

# Fix undefined variables
async def end_giveaway_after_delay(giveaway_id, delay_seconds):
    """End giveaway after specified delay"""
    await asyncio.sleep(delay_seconds)

    # Check if giveaway still exists and hasn't ended yet
    if giveaway_id in active_giveaways and not active_giveaways[giveaway_id].get('ended', False):
        await end_giveaway(giveaway_id)

@bot.tree.command(name="userinfo", description="Get detailed information about a user")
@app_commands.describe(user="The user to get info about (optional - defaults to yourself)")
async def user_info(interaction: discord.Interaction, user: discord.Member | None = None):
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
    embed.add_field(name="👥 Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="🎭 Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="📝 Channels", value=str(len(guild.channels)), inline=True)

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
    option1="First option", 
    option2="Second option", 
    option3="Third option (optional)",
    option4="Fourth option (optional)",
    option5="Fifth option (optional)"
)
async def create_poll(
    interaction: discord.Interaction,
    question: str,
    option1: str,
    option2: str,
    option3: str = None,
    option4: str = None,
    option5: str = None
):
    options = [option1, option2]
    if option3: options.append(option3)
    if option4: options.append(option4)
    if option5: options.append(option5)
    
    if len(options) > 10:
        await interaction.response.send_message("❌ Maximum 10 options allowed!", ephemeral=True)
        return

    # Number emojis for reactions
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    embed = discord.Embed(
        title="📊 Poll",
        description=f"**{question}**\n\n" + "\n".join([f"{number_emojis[i]} {option}" for i, option in enumerate(options)]),
        color=0x00ff00
    )
    embed.set_footer(text=f"Poll created by {interaction.user.display_name}")
    
    message = await interaction.response.send_message(embed=embed)
    poll_message = await interaction.original_response()
    
    # Add reactions
    for i in range(len(options)):
        await poll_message.add_reaction(number_emojis[i])

@bot.tree.command(name="level", description="Check your or someone else's level and XP")
@app_commands.describe(user="User to check level for (optional)")
async def check_level(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user
    progress = get_level_progress(target_user.id, target_user)
    
    embed = discord.Embed(
        title=f"📊 Level Stats for {target_user.display_name}",
        color=target_user.color if target_user.color.value != 0 else 0x7289da
    )
    
    embed.add_field(name="📈 Level", value=f"**{progress['level']}**", inline=True)
    embed.add_field(name="✨ Total XP", value=f"**{progress['current_xp']:,}**", inline=True)
    embed.add_field(name="🚀 XP Multiplier", value=f"**{progress['multiplier']:.2f}x**", inline=True)
    
    # Progress bar
    progress_bar = "▓" * int(progress['progress_percent'] / 10) + "░" * (10 - int(progress['progress_percent'] / 10))
    embed.add_field(
        name="📊 Progress to Next Level",
        value=f"```{progress_bar} {progress['progress_percent']:.1f}%```\n"
              f"**{progress['xp_in_level']:,}** / **{progress['xp_needed_for_level']:,}** XP",
        inline=False
    )
    
    if progress['booster_multiplier'] > 1.0:
        booster_bonus = int((progress['booster_multiplier'] - 1.0) * 100)
        embed.add_field(name="💎 Booster Bonus", value=f"**+{booster_bonus}% XP**", inline=True)
    
    embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else target_user.default_avatar.url)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="Show the server XP leaderboard")
async def leaderboard(interaction: discord.Interaction):
    if not user_levels:
        await interaction.response.send_message("❌ No one has earned XP yet!", ephemeral=True)
        return
    
    # Sort users by XP
    sorted_users = sorted(user_levels.items(), key=lambda x: x[1]['xp'], reverse=True)
    
    embed = discord.Embed(
        title="🏆 XP Leaderboard",
        color=0xffd700
    )
    
    leaderboard_text = ""
    for i, (user_id, data) in enumerate(sorted_users[:10]):  # Top 10
        user = interaction.guild.get_member(user_id)
        if user:
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"#{i+1}"
            leaderboard_text += f"{medal} **{user.display_name}** - Level {data['level']} ({data['xp']:,} XP)\n"
    
    embed.description = leaderboard_text or "No users found!"
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rankcard", description="Display your rank card with level, XP, and stats")
@app_commands.describe(user="User to check rank card for (optional)")
async def rank_card(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user
    
    if target_user.id not in user_levels:
        await interaction.response.send_message(f"{target_user.mention} hasn't earned any XP yet!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    try:
        # Get user data
        user_data = user_levels[target_user.id]
        level = user_data['level']
        current_xp = user_data['xp']
        xp_for_current = calculate_xp_for_level(level)
        xp_for_next = calculate_xp_for_level(level + 1)
        
        # Calculate rank position
        sorted_users = sorted(user_levels.items(), key=lambda x: x[1]['xp'], reverse=True)
        rank_position = next((i + 1 for i, (uid, _) in enumerate(sorted_users) if uid == target_user.id), 0)
        
        # Get guild icon
        guild_icon_url = interaction.guild.icon.url if interaction.guild.icon else ""
        
        # Generate rank card
        card_image = generate_rank_card(target_user, level, current_xp, xp_for_current, xp_for_next, rank_position, guild_icon_url)
        
        # Send as file
        file = discord.File(card_image, filename="rankcard.png")
        embed = discord.Embed(title=f"{target_user.display_name}'s Rank Card", color=0x00ff00)
        embed.set_image(url="attachment://rankcard.png")
        
        await interaction.followup.send(embed=embed, file=file)
    except Exception as e:
        logging.error(f"Error generating rank card: {e}")
        await interaction.followup.send(f"❌ Error generating rank card: {str(e)}", ephemeral=True)

# Music Player (using yt-dlp)
music_queue = {}  # {guild_id: {'queue': [], 'now_playing': None, 'vc': voice_client}}

@bot.tree.command(name="play", description="Play a song from YouTube")
@app_commands.describe(query="YouTube URL or search query")
async def play_song(interaction: discord.Interaction, query: str):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ You must be in a voice channel!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    try:
        guild_id = interaction.guild.id
        
        # Join voice channel
        vc = interaction.user.voice.channel
        if guild_id not in music_queue:
            music_queue[guild_id] = {'queue': [], 'now_playing': None, 'vc': None}
        
        if not music_queue[guild_id]['vc'] or not music_queue[guild_id]['vc'].is_connected():
            music_queue[guild_id]['vc'] = await vc.connect()
        
        # Extract info using yt-dlp with options to handle YouTube's anti-bot measures
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch',
            'max_downloads': 1,
            'extractor_args': {
                'youtube': {
                    'skip': ['hls', 'dash'],
                    'player_skip': ['webpage', 'configs', 'js'],
                }
            },
            'youtube_include_dash_manifest': False,
            'youtube_include_hls_manifest': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if 'entries' in info:
                info = info['entries'][0]

            url = info['url']
            title = info['title']

            music_queue[guild_id]['queue'].append({'url': url, 'title': title})

            await interaction.followup.send(f"⏯️ Added to queue: **{title}**")

            # Play if nothing is playing
            if not music_queue[guild_id]['now_playing']:
                await play_next_song(guild_id, interaction)

    except yt_dlp.DownloadError as e:
        if "Sign in to confirm you're not a bot" in str(e) or "confirm you are not a bot" in str(e):
            logging.error(f"YouTube anti-bot protection triggered: {e}")
            await interaction.followup.send("❌ YouTube is asking for verification. This usually happens due to too many requests. Try using a direct link instead of search terms, or try again later.", ephemeral=True)
        elif "Requested format is not available" in str(e):
            logging.error(f"Format not available: {e}")
            await interaction.followup.send("❌ The requested video format is not available. Try a different video.", ephemeral=True)
        else:
            logging.error(f"Download error: {e}")
            await interaction.followup.send(f"❌ Download error: {str(e)}", ephemeral=True)
    except Exception as e:
        logging.error(f"Error playing song: {e}")
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

async def play_next_song(guild_id, interaction):
    """Play next song in queue"""
    try:
        if not music_queue[guild_id]['queue']:
            music_queue[guild_id]['now_playing'] = None
            # Optionally notify when queue is empty
            return

        song = music_queue[guild_id]['queue'].pop(0)
        music_queue[guild_id]['now_playing'] = song

        vc = music_queue[guild_id]['vc']

        # Try to create audio stream with error handling
        try:
            audio = discord.FFmpegPCMAudio(song['url'], options="-vn")
        except Exception as audio_error:
            logging.error(f"Failed to create audio stream for {song['title']}: {audio_error}")
            # Try to play the next song in queue
            asyncio.run_coroutine_threadsafe(play_next_song(guild_id, interaction), bot.loop)
            return

        def after_playing(error):
            if error:
                logging.error(f"Error playing audio: {error}")
            # Schedule next song in the event loop
            asyncio.run_coroutine_threadsafe(play_next_song(guild_id, interaction), bot.loop)

        if vc.is_connected() and not vc.is_playing():
            vc.play(audio, after=after_playing)
        else:
            # If VC is not connected or already playing, try to reconnect or skip
            if not vc.is_connected():
                # Try to reconnect to voice channel
                try:
                    voice_channel = music_queue[guild_id]['vc'].channel
                    music_queue[guild_id]['vc'] = await voice_channel.connect()
                    vc = music_queue[guild_id]['vc']
                    if not vc.is_playing():
                        vc.play(audio, after=after_playing)
                except Exception as reconnect_error:
                    logging.error(f"Failed to reconnect to voice channel: {reconnect_error}")
                    # Skip this song and try the next one
                    asyncio.run_coroutine_threadsafe(play_next_song(guild_id, interaction), bot.loop)
            elif vc.is_playing():
                # If already playing, just schedule the next song
                asyncio.run_coroutine_threadsafe(play_next_song(guild_id, interaction), bot.loop)
    except Exception as e:
        logging.error(f"Error in play_next_song: {e}")
        # Ensure we try to play the next song even if there's an error
        try:
            asyncio.run_coroutine_threadsafe(play_next_song(guild_id, interaction), bot.loop)
        except:
            pass  # If we can't schedule the next song, just continue

@bot.tree.command(name="stop", description="Stop the music player")
async def stop_music(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    if guild_id not in music_queue or not music_queue[guild_id]['vc']:
        await interaction.response.send_message("❌ Not playing anything!", ephemeral=True)
        return

    vc = music_queue[guild_id]['vc']
    if vc.is_playing():
        vc.stop()
        music_queue[guild_id]['queue'] = []
        music_queue[guild_id]['now_playing'] = None
        await vc.disconnect()
        await interaction.response.send_message("⏹️ Music stopped and queue cleared.")
    else:
        # Clear the queue even if not currently playing
        music_queue[guild_id]['queue'] = []
        music_queue[guild_id]['now_playing'] = None
        if vc.is_connected():
            await vc.disconnect()
        await interaction.response.send_message("⏹️ Music stopped and queue cleared.")

@bot.tree.command(name="skip", description="Skip current song")
async def skip_song(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    if guild_id not in music_queue or not music_queue[guild_id]['vc']:
        await interaction.response.send_message("❌ Not playing anything!", ephemeral=True)
        return

    vc = music_queue[guild_id]['vc']
    if vc.is_playing():
        vc.stop()
        await interaction.response.send_message("⏭️ Skipped current song.")
    else:
        # Check if there are songs in the queue to play next
        if music_queue[guild_id]['queue']:
            await interaction.response.send_message("⏭️ Current song not playing, but there are songs in the queue to play next.")
        else:
            await interaction.response.send_message("❌ Not playing anything!", ephemeral=True)

@bot.tree.command(name="dbtest", description="Test MongoDB connection and data persistence")
async def db_test(interaction: discord.Interaction):
    """Test MongoDB connection and data persistence"""
    if not mongo_client:
        embed = discord.Embed(
            title="❌ MongoDB Test Failed",
            description="MongoDB is not configured. Please set MONGODB_URI in your .env file.",
            color=0xff0000
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    try:
        # Test the connection
        db.command('ping')

        # Get counts from all collections
        users_count = users_collection.count_documents({})
        warnings_count = warnings_collection.count_documents({})
        punishments_count = punishments_collection.count_documents({})
        giveaways_count = giveaways_collection.count_documents({})

        embed = discord.Embed(
            title="✅ MongoDB Connection Test Successful",
            description="Database connection is working properly!",
            color=0x00ff00
        )
        embed.add_field(name="📊 Users Collection", value=f"{users_count} documents", inline=True)
        embed.add_field(name="⚠️ Warnings Collection", value=f"{warnings_count} documents", inline=True)
        embed.add_field(name="🔨 Punishments Collection", value=f"{punishments_count} documents", inline=True)
        embed.add_field(name="🎉 Giveaways Collection", value=f"{giveaways_count} documents", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    except Exception as e:
        embed = discord.Embed(
            title="❌ MongoDB Test Failed",
            description=f"Connection error: {str(e)}",
            color=0xff0000
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Error handling for missing commands
@bot.event  
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore command not found errors
    
    logging.error(f"Command error: {error}")

@bot.event
async def on_application_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"⏰ Command on cooldown. Try again in {error.retry_after:.2f} seconds.", ephemeral=True)
    else:
        logging.error(f"Application command error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while processing the command.", ephemeral=True)

# Keep alive function for hosting
keep_alive()

# Run the bot
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logging.error(f"Bot failed to start: {e}")
        print(f"Error starting bot: {e}")