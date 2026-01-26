import sys
import os
sys.path.append('DeepInfamousDirectories')

# Since we can't directly access the bot's memory, let's create a command you can add to your main bot file
# to help troubleshoot giveaways in the future

troubleshooting_commands = """
# Add this command to your main.py file to help troubleshoot giveaways

@bot.tree.command(name="debug-giveaways", description="Debug active giveaways (admin only)")
@app_commands.check(lambda interaction: interaction.user.guild_permissions.administrator)
async def debug_giveaways(interaction: discord.Interaction):
    '''Debug command to see active giveaways'''
    if not active_giveaways:
        await interaction.response.send_message("❌ No active giveaways found.", ephemeral=True)
        return
    
    embed = discord.Embed(title="🔍 Active Giveaways Debug", color=0x5865F2)
    
    for msg_id, giveaway in active_giveaways.items():
        status = "ENDED" if giveaway.get('ended', False) else "ACTIVE"
        time_left = "N/A" if giveaway.get('ended', False) else giveaway.get('end_time', 'Unknown')
        
        value = f"**Prize:** {giveaway.get('prize', 'Unknown')}\n"
        value += f"**Channel:** <#{giveaway.get('channel_id', 'Unknown')}>\n"
        value += f"**Status:** {status}\n"
        value += f"**End Time:** {time_left}\n"
        value += f"**Host:** {giveaway.get('host', 'Unknown')}"
        
        embed.add_field(name=f"ID: {msg_id}", value=value, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


# Also add this command to force end a giveaway if needed

@bot.tree.command(name="force-end-giveaway", description="Force end a giveaway immediately (admin only)")
@app_commands.describe(message_id="The message ID of the giveaway to force end")
@app_commands.check(lambda interaction: interaction.user.guild_permissions.administrator)
async def force_end_giveaway_now(interaction: discord.Interaction, message_id: str):
    '''Force end a giveaway immediately'''
    try:
        msg_id = int(message_id)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID format!", ephemeral=True)
        return
    
    if msg_id not in active_giveaways:
        await interaction.response.send_message("❌ Giveaway not found in active giveaways!", ephemeral=True)
        return
    
    giveaway = active_giveaways[msg_id]
    
    # Force end the giveaway
    giveaway['ended'] = True
    await end_giveaway(msg_id)
    
    await interaction.response.send_message(f"✅ Giveaway {msg_id} has been force-ended!", ephemeral=True)
"""

print("To troubleshoot your giveaway issue:")
print("1. Check if anyone reacted to your giveaway message with :tada: (emoji reaction)")
print("2. Verify the bot has permissions to send messages in the channel")
print("3. Check if participants met the message requirements (default 100 messages)")
print()
print("Add these commands to your main.py file for future troubleshooting:")
print(troubleshooting_commands)