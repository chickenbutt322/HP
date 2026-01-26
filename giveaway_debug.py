import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
import json
from datetime import datetime
from pymongo import MongoClient

# Load environment variables
load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")

# Global variables
mongo_client = None
giveaways_collection = None

# MongoDB Connection
if MONGODB_URI:
    try:
        mongo_client = MongoClient(MONGODB_URI)
        db = mongo_client['hp_bot']
        giveaways_collection = db['giveaways']
        print("[SUCCESS] Connected to MongoDB")
    except Exception as e:
        print(f"[ERROR] MongoDB connection failed: {e}")
        mongo_client = None
else:
    print("[WARNING] MONGODB_URI not set - using local JSON storage")

# Check for active giveaways
def check_active_giveaways():
    """Check for active giveaways in the database"""
    global mongo_client
    if mongo_client:
        # Query for giveaways that should have ended but might not have processed
        from datetime import datetime
        ended_giveaways = list(giveaways_collection.find({
            'end_time': {'$lt': datetime.utcnow().isoformat()},
            'ended': {'$ne': True}  # Not marked as ended
        }))
        
        active_giveaways = list(giveaways_collection.find({
            'end_time': {'$gt': datetime.utcnow().isoformat()},
            'ended': {'$ne': True}  # Not marked as ended
        }))
        
        print(f"Ended giveaways that may not have processed: {len(ended_giveaways)}")
        print(f"Active giveaways: {len(active_giveaways)}")
        
        # Show details of ended giveaways that might not have processed
        for giveaway in ended_giveaways:
            end_time = giveaway.get('end_time')
            prize = giveaway.get('prize', 'Unknown')
            print(f"- Giveaway ID: {giveaway.get('message_id')} | Prize: {prize} | Ended: {end_time}")
    
    # Also check local JSON file if it exists
    import os
    GIVEAWAYS_FILE = "bot_data/active_giveaways.json"  # Adjust path as needed
    
    if os.path.exists(GIVEAWAYS_FILE):
        with open(GIVEAWAYS_FILE, 'r') as f:
            try:
                data = json.load(f)
                print(f"\nLocal giveaways file has {len(data)} entries")
                
                for msg_id, giveaway_data in data.items():
                    end_time_str = giveaway_data.get('end_time')
                    prize = giveaway_data.get('prize', 'Unknown')
                    ended_status = giveaway_data.get('ended', False)
                    
                    # Parse end time
                    try:
                        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                        time_diff = (datetime.utcnow() - end_time).total_seconds()
                        
                        status = "ENDED" if ended_status else "NOT ENDED"
                        overdue = "OVERDUE" if time_diff > 0 and not ended_status else ""
                        
                        print(f"- Message ID: {msg_id} | Prize: {prize} | Status: {status} {overdue}")
                        if time_diff > 0 and not ended_status:
                            print(f"  [WARNING] This giveaway ended {(time_diff/60):.1f} minutes ago but hasn't been processed!")
                            
                    except Exception as e:
                        print(f"- Message ID: {msg_id} | Error parsing time: {e}")
                        
            except json.JSONDecodeError:
                print("Error reading giveaways file - invalid JSON")

if __name__ == "__main__":
    check_active_giveaways()