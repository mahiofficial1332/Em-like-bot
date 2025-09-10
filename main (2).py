import os
import aiohttp
import asyncio
import json
from datetime import datetime, timedelta
import discord
from discord.ext import commands, tasks
from discord import app_commands
import pytz

# ==== BOT TOKEN AND API CONFIG ====
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_BASE = "https://jamilikeapi.vercel.app/like?uid={uid}&region={region}"

# Owner IDs
OWNER_IDS = [1380183114109947924]

# Data file for persistent storage
DATA_FILE = "data.json"

# Default daily limit for regular members
DEFAULT_DAILY_LIMIT = 2

# ==== GLOBAL STORAGE ====
user_limits = {}  # user_id: daily_limit
role_limits = {}  # role_id: daily_limit
user_usage = {}   # user_id: {"date": "2024-01-01", "count": 0}
like_channels = {}  # guild_id: channel_id
auto_like_uids = {}  # uid: {"region": "AUTO", "nickname": "Unknown"}
report_channels = {}  # guild_id: channel_id
auto_like_reports = {}  # date: [{"uid": "123", "status": "success", "likes": 5}]

# ==== INTENTS ====
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

class LikeBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Sync slash commands
        await self.tree.sync()
        print("✅ Slash commands synced!")

bot = LikeBot()

# ==== SESSION ====
session: aiohttp.ClientSession | None = None

# ==== LOAD/SAVE DATA ====
def load_data():
    global user_limits, role_limits, user_usage, like_channels, auto_like_uids, report_channels, auto_like_reports
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                user_limits = data.get("user_limits", {})
                role_limits = data.get("role_limits", {})
                user_usage = data.get("user_usage", {})
                like_channels = data.get("like_channels", {})
                auto_like_uids = data.get("auto_like_uids", {})
                report_channels = data.get("report_channels", {})
                auto_like_reports = data.get("auto_like_reports", {})
        except Exception as e:
            print(f"Error loading data: {e}")
            save_data()
    else:
        save_data()

def save_data():
    data = {
        "user_limits": user_limits,
        "role_limits": role_limits,
        "user_usage": user_usage,
        "like_channels": like_channels,
        "auto_like_uids": auto_like_uids,
        "report_channels": report_channels,
        "auto_like_reports": auto_like_reports,
    }
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving data: {e}")

# ==== HELPERS ====
async def fetch_like(uid, region="AUTO"):
    """Fetch like from API"""
    global session
    if session is None or session.closed:
        session = aiohttp.ClientSession()
    
    # Convert IND to IN for API compatibility
    api_region = "IN" if region == "IND" else region
    
    url = API_BASE.format(uid=uid, region=api_region)
    print(f"🔗 Connecting to API: {url}")
    print(f"🌍 Region: {region} -> API Region: {api_region}")
    
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            print(f"📡 API Response Status: {resp.status}")
            
            if resp.status == 200:
                data = await resp.json()
                print(f"📊 API Data: {data}")
                
                # Check if API response is valid
                if data and "status" in data:
                    print(f"✅ Valid API response received for UID {uid}")
                    
                    # The REAL check: How many likes were actually sent?
                    likes_sent = data.get("LikesGivenByAPI", 0)
                    print(f"🎯 Likes actually sent by API: {likes_sent}")
                    
                    # Create response data
                    response_data = {
                        "PlayerNickname": data.get("PlayerNickname", "Unknown"),
                        "UID": data.get("UID", uid),
                        "Region": region,  # Use original region (IND)
                        "LikesGivenByAPI": likes_sent,
                        "LikesbeforeCommand": data.get("LikesbeforeCommand", 0),
                        "LikesafterCommand": data.get("LikesafterCommand", 0)
                    }
                    
                    # Determine status based on ACTUAL likes sent, not API status code
                    if likes_sent > 0:
                        # SUCCESS! Likes were actually sent
                        converted_data = {
                            "status": "success",
                            "response": response_data
                        }
                        print(f"✅ SUCCESS: {likes_sent} likes sent to {data.get('PlayerNickname', 'Unknown')}")
                    else:
                        # NO LIKES SENT - Show "already received likes" message
                        converted_data = {
                            "status": "maxlike",
                            "response": response_data
                        }
                        print(f"🚫 NO LIKES SENT: UID {uid} has reached daily API limit")
                    
                    print(f"✅ Converted data: {converted_data}")
                    return converted_data
                else:
                    print(f"❌ Invalid API response format: {data}")
                    return None
            else:
                print(f"❌ API returned HTTP {resp.status}")
                response_text = await resp.text()
                print(f"📄 Response body: {response_text}")
                return None
                
    except asyncio.TimeoutError:
        print(f"⏱️ API request timed out for UID {uid} (Region: {region})")
        return None
    except Exception as e:
        print(f"💥 API connection error for UID {uid}: {e}")
        return None

async def test_api_connection():
    """Test API connection"""
    print("🧪 Testing API connection...")
    test_uid = "6427406194"
    test_region = "IND"
    
    result = await fetch_like(test_uid, test_region)
    
    if result:
        print(f"✅ API Test Success: {result}")
        return True
    else:
        print("❌ API Test Failed")
        return False

def get_today_date():
    return datetime.now().strftime("%Y-%m-%d")

def get_region_flag(region):
    """Get flag emoji for region"""
    flags = {
        "BD": "🇧🇩", "IND": "🇮🇳", "ID": "🇮🇩", "TH": "🇹🇭", 
        "VN": "🇻🇳", "SG": "🇸🇬", "MY": "🇲🇾", "PH": "🇵🇭",
        "BR": "🇧🇷", "RU": "🇷🇺", "US": "🇺🇸", "PK": "🇵🇰",
        "EG": "🇪🇬", "SA": "🇸🇦", "ME": "🇲🇪", "AUTO": "🌍"
    }
    return flags.get(region.upper(), "🌍")

def get_user_daily_limit(user):
    """Get the daily limit for a user based on roles and individual settings"""
    user_id = str(user.id)
    
    # Check if user has individual limit set
    if user_id in user_limits:
        return user_limits[user_id]
    
    # Check role-based limits (highest role limit takes precedence)
    max_role_limit = 0
    for role in user.roles:
        role_id = str(role.id)
        if role_id in role_limits:
            max_role_limit = max(max_role_limit, role_limits[role_id])
    
    if max_role_limit > 0:
        return max_role_limit
    
    # Return default limit
    return DEFAULT_DAILY_LIMIT

def get_user_usage_today(user_id):
    """Get user's usage count for today"""
    user_id = str(user_id)
    today = get_today_date()
    
    if user_id not in user_usage:
        user_usage[user_id] = {"date": today, "count": 0}
        return 0
    
    if user_usage[user_id]["date"] != today:
        user_usage[user_id] = {"date": today, "count": 0}
        return 0
    
    return user_usage[user_id]["count"]

def increment_user_usage(user_id):
    """Increment user's usage count for today"""
    user_id = str(user_id)
    today = get_today_date()
    
    if user_id not in user_usage or user_usage[user_id]["date"] != today:
        user_usage[user_id] = {"date": today, "count": 1}
    else:
        user_usage[user_id]["count"] += 1
    
    save_data()

# ==== SUCCESS EMBED ====
def make_success_embed(data, user, remaining_limit):
    r = data["response"]
    
    # Get current time in Nepal timezone
    tz = pytz.timezone("Asia/Kathmandu")
    current_time = datetime.now(tz)
    date_str = current_time.strftime("%Y-%m-%d")
    time_str = current_time.strftime("%H:%M:%S")
    
    region_flag = get_region_flag(r.get('Region', 'AUTO'))
    desc = f"""
```
✅ LIKES SENT SUCCESSFULLY!
┌─ PLAYER: {r['PlayerNickname']} ({r['UID']})
├─ REGION: {region_flag} {r.get('Region', 'AUTO')}
├─ LIKES ADDED: +{r['LikesGivenByAPI']}
├─ BEFORE: {r['LikesbeforeCommand']} → AFTER: {r['LikesafterCommand']}
└─ YOUR REMAINING LIMIT: {remaining_limit}
```
🎮 [JOIN COMMUNITY](https://discord.gg/CmMG2xryMX)
**DEVELOPER BY EM OFFICIAL TEAM** | {date_str} {time_str}
    """
    
    embed = discord.Embed(description=desc, color=discord.Color.green())
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_image(url="https://cdn.discordapp.com/attachments/1389124738395148391/1414487474788503662/static_1.png?ex=68bfbf9d&is=68be6e1d&hm=c3b04478724a952c020d61707c987e18aa4690b1ae05a129ef5f35f0b6d72af5&")
    return embed

# ==== LIMIT REACHED EMBED ====
def make_limit_embed(user, current_usage, daily_limit):
    # Get current time in Nepal timezone
    tz = pytz.timezone("Asia/Kathmandu")
    current_time = datetime.now(tz)
    date_str = current_time.strftime("%Y-%m-%d")
    time_str = current_time.strftime("%H:%M:%S")
    
    desc = f"""
**⚠️ Daily limit reached ({current_usage}/{daily_limit})**

To get 5 requests/day:
📺 [Subscribe](https://youtube.com/@emofficial1234?si=GgumInQC8DxjSHhK)
📸 [Send Screenshot](https://discord.com/channels/1394679922068422738/1415038725775294657)

🎮 [JOIN COMMUNITY](https://discord.gg/CmMG2xryMX)
**DEVELOPER BY EM OFFICIAL TEAM** | {date_str} {time_str}
    """
    
    embed = discord.Embed(description=desc, color=discord.Color.red())
    embed.set_thumbnail(url=user.display_avatar.url)
    return embed

# ==== MAX LIKE EMBED ====
def make_maxlike_embed(user):
    # Get current time in Nepal timezone
    tz = pytz.timezone("Asia/Kathmandu")
    current_time = datetime.now(tz)
    date_str = current_time.strftime("%Y-%m-%d")
    time_str = current_time.strftime("%H:%M:%S")
    
    desc = f"""
```
API LIMIT REACHED!
┌─ STATUS: FAILED
├─ REASON: UID has reached daily API limit
├─ SOLUTION: Try with different UID
└─ OR: Wait 24 hours for reset
```
💡 **Tip:** Use different UIDs or try again tomorrow

🎮 [JOIN COMMUNITY](https://discord.gg/CmMG2xryMX)
**DEVELOPER BY EM OFFICIAL TEAM** | {date_str} {time_str}
    """
    
    embed = discord.Embed(description=desc, color=discord.Color.orange())
    embed.set_thumbnail(url=user.display_avatar.url)
    return embed

# ==== PREFIX LIKE COMMAND ====
@bot.command()
@commands.cooldown(1, 30, commands.BucketType.user)
async def like(ctx, region: str = "AUTO", uid: str = ""):
    # Check if command is in allowed channel
    if ctx.guild and str(ctx.guild.id) in like_channels:
        allowed_channel_id = like_channels[str(ctx.guild.id)]
        if ctx.channel.id != allowed_channel_id:
            channel = ctx.guild.get_channel(allowed_channel_id)
            if channel:
                await ctx.send(f"❌ Use this command in {channel.mention} only.")
                return
    
    # Check if UID is provided
    if not uid:
        await ctx.send("❌ Please provide UID. Usage: `!like [region] <uid>`")
        return
    
    # Validate UID
    if not uid.isdigit() or len(uid) < 6:
        await ctx.send("❌ Invalid UID. Must be only numbers & at least 6 digits.")
        return
    
    # Validate region
    valid_regions = ["BD", "IND", "ID", "TH", "VN", "SG", "MY", "PH", "BR", "RU", "US", "PK", "EG", "SA", "ME", "AUTO"]
    if region.upper() not in valid_regions:
        await ctx.send(f"❌ Invalid region. Valid regions: {', '.join(valid_regions)}")
        return
    
    # Check user's daily limit
    daily_limit = get_user_daily_limit(ctx.author)
    current_usage = get_user_usage_today(ctx.author.id)
    
    if current_usage >= daily_limit:
        msg = await ctx.send(embed=make_limit_embed(ctx.author, current_usage, daily_limit))
        # Delete message after 20 seconds
        await asyncio.sleep(20)
        try:
            await msg.delete()
        except:
            pass
        return
    
    # Send processing message
    processing_msg = await ctx.send("⏳ Processing your request...")
    
    try:
        # Fetch likes from API
        data = await fetch_like(uid, region.upper())
        
        if data is None:
            await processing_msg.edit(content="❌ API connection failed. Please try again later.")
            return
        
        if data.get("status") == "success":
            # Increment user usage
            increment_user_usage(ctx.author.id)
            remaining_limit = daily_limit - (current_usage + 1)
            
            # Send success embed
            embed = make_success_embed(data, ctx.author, remaining_limit)
            await processing_msg.edit(content="", embed=embed)
        
        elif data.get("status") == "maxlike":
            # UID has reached daily limit
            embed = make_maxlike_embed(ctx.author)
            await processing_msg.edit(content="", embed=embed)
        
        else:
            await processing_msg.edit(content="❌ API returned an error. Please try again later.")
    
    except Exception as e:
        print(f"Error in like command: {e}")
        await processing_msg.edit(content="❌ An unexpected error occurred. Please try again later.")

# ==== SLASH COMMANDS FOR ADMIN ====
@bot.tree.command(name="setlimit", description="Set daily limit for user or role (Owner only)")
@app_commands.describe(
    target="User or role to set limit for",
    limit="Daily limit number"
)
async def setlimit_slash(interaction: discord.Interaction, target: discord.Member | discord.Role, limit: int):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ Only bot owners can use this command.", ephemeral=True)
        return
    
    if isinstance(target, discord.Member):
        user_limits[str(target.id)] = limit
        await interaction.response.send_message(f"✅ Set daily limit for **{target.display_name}** to **{limit}** requests.")
    else:
        role_limits[str(target.id)] = limit
        await interaction.response.send_message(f"✅ Set daily limit for role **{target.name}** to **{limit}** requests.")
    
    save_data()

@bot.tree.command(name="setchannel", description="Set allowed channel for like commands (Owner only)")
@app_commands.describe(channel="Channel to set as allowed channel")
async def setchannel_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ Only bot owners can use this command.", ephemeral=True)
        return
    
    if channel is None:
        channel = interaction.channel
    
    like_channels[str(interaction.guild.id)] = channel.id
    await interaction.response.send_message(f"✅ Set like channel to {channel.mention}")
    save_data()

@bot.tree.command(name="setreport", description="Set auto-like report channel (Owner only)")
@app_commands.describe(channel="Channel to send auto-like reports")
async def setreport_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ Only bot owners can use this command.", ephemeral=True)
        return
    
    if channel is None:
        channel = interaction.channel
    
    report_channels[str(interaction.guild.id)] = channel.id
    await interaction.response.send_message(f"✅ Set auto-like report channel to {channel.mention}")
    save_data()

@bot.tree.command(name="addauto", description="Add UID to auto-like system (Owner only)")
@app_commands.describe(
    uid="PUBG Mobile UID",
    region="Region for the UID",
    nickname="Nickname for the UID"
)
@app_commands.choices(region=[
    app_commands.Choice(name="🇧🇩 Bangladesh", value="BD"),
    app_commands.Choice(name="🇮🇳 India", value="IND"),
    app_commands.Choice(name="🇮🇩 Indonesia", value="ID"),
    app_commands.Choice(name="🇹🇭 Thailand", value="TH"),
    app_commands.Choice(name="🇻🇳 Vietnam", value="VN"),
    app_commands.Choice(name="🇸🇬 Singapore", value="SG"),
    app_commands.Choice(name="🇲🇾 Malaysia", value="MY"),
    app_commands.Choice(name="🇵🇭 Philippines", value="PH"),
    app_commands.Choice(name="🇧🇷 Brazil", value="BR"),
    app_commands.Choice(name="🇷🇺 Russia", value="RU"),
    app_commands.Choice(name="🇺🇸 United States", value="US"),
    app_commands.Choice(name="🇵🇰 Pakistan", value="PK"),
    app_commands.Choice(name="🇪🇬 Egypt", value="EG"),
    app_commands.Choice(name="🇸🇦 Saudi Arabia", value="SA"),
    app_commands.Choice(name="🇲🇪 Montenegro", value="ME"),
    app_commands.Choice(name="🌍 Auto Detect", value="AUTO")
])
async def addauto_slash(interaction: discord.Interaction, uid: str, region: str = "AUTO", nickname: str = "Unknown"):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ Only bot owners can use this command.", ephemeral=True)
        return
    
    # Validate UID
    if not uid.isdigit() or len(uid) < 6:
        await interaction.response.send_message("❌ Invalid UID. Must be only numbers & at least 6 digits.", ephemeral=True)
        return
    
    auto_like_uids[uid] = {
        "region": region.upper(),
        "nickname": nickname
    }
    
    await interaction.response.send_message(f"✅ Added **{nickname}** ({uid}) with region **{region.upper()}** to auto-like system.")
    save_data()

@bot.tree.command(name="removeauto", description="Remove UID from auto-like system (Owner only)")
@app_commands.describe(uid="UID to remove from auto-like")
async def removeauto_slash(interaction: discord.Interaction, uid: str):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ Only bot owners can use this command.", ephemeral=True)
        return
    
    if uid in auto_like_uids:
        nickname = auto_like_uids[uid]["nickname"]
        del auto_like_uids[uid]
        await interaction.response.send_message(f"✅ Removed **{nickname}** ({uid}) from auto-like system.")
        save_data()
    else:
        await interaction.response.send_message("❌ UID not found in auto-like system.", ephemeral=True)

@bot.tree.command(name="listauto", description="List all UIDs in auto-like system (Owner only)")
async def listauto_slash(interaction: discord.Interaction):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ Only bot owners can use this command.", ephemeral=True)
        return
    
    if not auto_like_uids:
        await interaction.response.send_message("📋 No UIDs in auto-like system.", ephemeral=True)
        return
    
    desc = "**Auto-Like UIDs:**\n"
    for uid, data in auto_like_uids.items():
        flag = get_region_flag(data["region"])
        desc += f"{flag} **{data['nickname']}** - `{uid}` ({data['region']})\n"
    
    embed = discord.Embed(description=desc, color=discord.Color.blue())
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="testapi", description="Test API connection (Owner only)")
async def testapi_slash(interaction: discord.Interaction):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ Only bot owners can use this command.", ephemeral=True)
        return
    
    await interaction.response.send_message("🧪 Testing API connection...", ephemeral=True)
    
    success = await test_api_connection()
    
    if success:
        await interaction.edit_original_response(content="✅ API connection test successful!")
    else:
        await interaction.edit_original_response(content="❌ API connection test failed!")

# ==== AUTO-LIKE TASK ====
@tasks.loop(hours=1)
async def auto_like_task():
    """Auto-like task that runs every hour"""
    try:
        if auto_like_uids:
            print(f"🤖 Starting auto-like for {len(auto_like_uids)} UIDs...")
            
            today = get_today_date()
            if today not in auto_like_reports:
                auto_like_reports[today] = []
            
            for uid, data in auto_like_uids.items():
                try:
                    result = await fetch_like(uid, data["region"])
                    
                    if result and result.get("status") == "success":
                        likes_given = result["response"].get("LikesGivenByAPI", 0)
                        print(f"✅ Auto-like success for {data['nickname']} ({uid}): +{likes_given} likes")
                        
                        auto_like_reports[today].append({
                            "uid": uid,
                            "nickname": data["nickname"],
                            "region": data["region"],
                            "status": "success",
                            "likes": likes_given,
                            "timestamp": datetime.now().strftime("%H:%M:%S")
                        })
                    else:
                        print(f"❌ Auto-like failed for {data['nickname']} ({uid})")
                        
                        auto_like_reports[today].append({
                            "uid": uid,
                            "nickname": data["nickname"],
                            "region": data["region"],
                            "status": "failed",
                            "likes": 0,
                            "timestamp": datetime.now().strftime("%H:%M:%S")
                        })
                    
                    # Wait 5 seconds between requests
                    await asyncio.sleep(5)
                    
                except Exception as e:
                    print(f"💥 Auto-like error for {uid}: {e}")
            
            # Send report to report channels
            await send_auto_like_report()
            save_data()
        
    except Exception as e:
        print(f"💥 Auto-like task error: {e}")

async def send_auto_like_report():
    """Send auto-like report to all report channels"""
    today = get_today_date()
    
    if today not in auto_like_reports or not auto_like_reports[today]:
        return
    
    # Create report embed
    tz = pytz.timezone("Asia/Kathmandu")
    current_time = datetime.now(tz)
    time_str = current_time.strftime("%H:%M:%S")
    
    desc = f"**🤖 Auto-Like Report - {today} {time_str}**\n\n"
    
    success_count = 0
    total_likes = 0
    
    for report in auto_like_reports[today]:
        status_emoji = "✅" if report["status"] == "success" else "❌"
        flag = get_region_flag(report["region"])
        
        desc += f"{status_emoji} {flag} **{report['nickname']}** - `{report['uid']}`\n"
        desc += f"   └─ Likes: +{report['likes']} | Time: {report['timestamp']}\n\n"
        
        if report["status"] == "success":
            success_count += 1
            total_likes += report["likes"]
    
    desc += f"**📊 Summary:**\n"
    desc += f"✅ Success: {success_count}/{len(auto_like_reports[today])}\n"
    desc += f"💖 Total Likes Given: {total_likes}\n"
    
    embed = discord.Embed(description=desc, color=discord.Color.blue())
    embed.set_footer(text="DEVELOPER BY EM OFFICIAL TEAM")
    
    # Send to all report channels
    for guild_id, channel_id in report_channels.items():
        try:
            guild = bot.get_guild(int(guild_id))
            if guild:
                channel = guild.get_channel(channel_id)
                if channel:
                    await channel.send(embed=embed)
        except Exception as e:
            print(f"Error sending report to {guild_id}/{channel_id}: {e}")

# ==== BOT EVENTS ====
@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online!")
    print(f"📊 Connected to {len(bot.guilds)} servers")
    print(f"🔗 API Endpoint: {API_BASE}")
    
    # Load data
    load_data()
    
    # Test API connection
    await test_api_connection()
    
    # Start auto-like task
    if not auto_like_task.is_running():
        auto_like_task.start()
        print("🤖 Auto-like task started!")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏱️ Command on cooldown. Try again in {error.retry_after:.1f} seconds.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing required argument. Usage: `!like [region] <uid>`")
    else:
        print(f"Command error: {error}")

# ==== RUN BOT ====
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN environment variable not set!")
        print("Please add your Discord bot token to environment variables.")
    else:
        try:
            bot.run(BOT_TOKEN)
        except Exception as e:
            print(f"❌ Failed to start bot: {e}")